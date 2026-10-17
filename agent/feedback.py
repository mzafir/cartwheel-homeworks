"""Feedback and trace logging system for LLM responses and tool calls.

Stores user feedback (thumbs up/down, annotations) against:
- Tool calls and their results
- LLM responses
- Session transactions
- Diffs/changes made by the agent

This feedback is used to improve prompts and create taxonomies of issues.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.config import REPO_ROOT


FEEDBACK_DB = Path(
    os.environ.get("CARTWHEEL_FEEDBACK_DB", REPO_ROOT / ".feedback.db")
)


@dataclass
class ToolCallTrace:
    """A tool invocation with its inputs and outputs."""
    id: str
    session_id: str
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    timestamp: datetime


@dataclass
class LLMTrace:
    """An LLM response with metadata."""
    id: str
    session_id: str
    prompt_version: str
    user_message: str
    assistant_response: str
    tool_calls: list[str]  # tool trace IDs
    timestamp: datetime


@dataclass
class Feedback:
    """User feedback on a trace or tool call."""
    id: str
    trace_id: str  # Can be tool_call_trace or llm_trace ID
    trace_type: str  # "tool_call" or "llm_response"
    session_id: str
    rating: int | None  # 1 (👍) or -1 (👎), or None
    annotation: str | None  # Free-form user comment
    tags: list[str]  # Categorization: ["hallucination", "error", "slow", etc.]
    created_at: datetime


def init_db() -> None:
    """Initialize feedback database schema."""
    conn = sqlite3.connect(FEEDBACK_DB)
    cursor = conn.cursor()
    
    # Tool call traces
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tool_call_traces (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            arguments TEXT NOT NULL,
            result TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES llm_traces(session_id)
        )
    """)
    
    # LLM response traces
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_traces (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            user_message TEXT NOT NULL,
            assistant_response TEXT NOT NULL,
            tool_calls TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    
    # Feedback/ratings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            trace_type TEXT NOT NULL CHECK (trace_type IN ('tool_call', 'llm_response')),
            session_id TEXT NOT NULL,
            rating INTEGER CHECK (rating IN (-1, 1, NULL)),
            annotation TEXT,
            tags TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (trace_id) REFERENCES tool_call_traces(id),
            FOREIGN KEY (trace_id) REFERENCES llm_traces(id),
            FOREIGN KEY (session_id) REFERENCES llm_traces(session_id)
        )
    """)
    
    # Diffs: track changes made by the agent
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS diffs (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            before_state TEXT NOT NULL,
            after_state TEXT NOT NULL,
            diff_type TEXT NOT NULL,
            tool_name TEXT,
            feedback_received INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()


def log_tool_call(
    session_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any]
) -> str:
    """Log a tool call invocation and return trace ID."""
    init_db()
    conn = sqlite3.connect(FEEDBACK_DB)
    cursor = conn.cursor()
    
    trace_id = f"tool_{session_id}_{tool_name}_{datetime.now().timestamp()}"
    timestamp = datetime.now().isoformat()
    
    cursor.execute("""
        INSERT INTO tool_call_traces 
        (id, session_id, tool_name, arguments, result, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        trace_id,
        session_id,
        tool_name,
        json.dumps(arguments),
        json.dumps(result),
        timestamp
    ))
    
    conn.commit()
    conn.close()
    
    return trace_id


def log_llm_response(
    session_id: str,
    prompt_version: str,
    user_message: str,
    assistant_response: str,
    tool_calls: list[str]
) -> str:
    """Log an LLM response and return trace ID."""
    init_db()
    conn = sqlite3.connect(FEEDBACK_DB)
    cursor = conn.cursor()
    
    trace_id = f"llm_{session_id}_{datetime.now().timestamp()}"
    timestamp = datetime.now().isoformat()
    
    cursor.execute("""
        INSERT INTO llm_traces 
        (id, session_id, prompt_version, user_message, assistant_response, tool_calls, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        trace_id,
        session_id,
        prompt_version,
        user_message,
        assistant_response,
        json.dumps(tool_calls),
        timestamp
    ))
    
    conn.commit()
    conn.close()
    
    return trace_id


def submit_feedback(
    trace_id: str,
    trace_type: str,
    session_id: str,
    rating: int | None = None,
    annotation: str | None = None,
    tags: list[str] | None = None
) -> str:
    """Upsert user feedback: one row per (trace_id, session_id), latest wins."""
    init_db()
    conn = sqlite3.connect(FEEDBACK_DB)
    cursor = conn.cursor()

    created_at = datetime.now().isoformat()
    row = cursor.execute(
        "SELECT id FROM feedback WHERE trace_id = ? AND session_id = ?",
        (trace_id, session_id),
    ).fetchone()

    if row:
        feedback_id = row[0]
        cursor.execute(
            "UPDATE feedback SET rating = ?, annotation = ?, tags = ?, created_at = ? WHERE id = ?",
            (rating, annotation, json.dumps(tags or []), created_at, feedback_id),
        )
    else:
        feedback_id = f"fb_{trace_id}_{datetime.now().timestamp()}"
        cursor.execute("""
            INSERT INTO feedback
            (id, trace_id, trace_type, session_id, rating, annotation, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            feedback_id,
            trace_id,
            trace_type,
            session_id,
            rating,
            annotation,
            json.dumps(tags or []),
            created_at
        ))

    conn.commit()
    conn.close()

    return feedback_id


def log_diff(
    session_id: str,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    diff_type: str,
    tool_name: str | None = None
) -> str:
    """Log a state change/diff made by the agent."""
    init_db()
    conn = sqlite3.connect(FEEDBACK_DB)
    cursor = conn.cursor()
    
    diff_id = f"diff_{session_id}_{datetime.now().timestamp()}"
    timestamp = datetime.now().isoformat()
    
    cursor.execute("""
        INSERT INTO diffs 
        (id, session_id, timestamp, before_state, after_state, diff_type, tool_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        diff_id,
        session_id,
        timestamp,
        json.dumps(before_state),
        json.dumps(after_state),
        diff_type,
        tool_name,
        datetime.now().isoformat()
    ))
    
    conn.commit()
    conn.close()
    
    return diff_id


def get_session_traces(session_id: str) -> dict[str, Any]:
    """Retrieve all traces for a session."""
    init_db()
    conn = sqlite3.connect(FEEDBACK_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM llm_traces WHERE session_id = ? ORDER BY timestamp", (session_id,))
    llm_traces = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM tool_call_traces WHERE session_id = ? ORDER BY timestamp", (session_id,))
    tool_traces = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM feedback WHERE session_id = ? ORDER BY created_at", (session_id,))
    feedback = [dict(row) for row in cursor.fetchall()]
    for f in feedback:
        f["tags"] = json.loads(f["tags"] or "[]")
    
    cursor.execute("SELECT * FROM diffs WHERE session_id = ? ORDER BY created_at", (session_id,))
    diffs = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "llm_traces": llm_traces,
        "tool_traces": tool_traces,
        "feedback": feedback,
        "diffs": diffs
    }
