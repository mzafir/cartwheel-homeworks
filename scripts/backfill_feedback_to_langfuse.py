"""Backfill local feedback traces into Langfuse as reconstructed observations."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.feedback import FEEDBACK_DB
from analysis.helpers.langfuse_io import _client


BACKFILL_SOURCE = ".feedback.db"
FIDELITY_NOTICE = (
    "Reconstructed from Cartwheel local feedback records; original OTel span "
    "IDs, timing, model, and token usage are unavailable."
)


@dataclass(frozen=True)
class BackfillSummary:
    sessions: int
    llm_traces: int
    tool_traces: int
    skipped: int
    applied: bool


def _loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _existing_mappings(conn: sqlite3.Connection) -> set[str]:
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'langfuse_backfill'"
    ).fetchone()
    if table is None:
        return set()
    return {
        row[0]
        for row in conn.execute("SELECT local_trace_id FROM langfuse_backfill")
    }


def _ensure_mapping_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS langfuse_backfill (
            local_trace_id TEXT PRIMARY KEY,
            trace_type TEXT NOT NULL,
            langfuse_trace_id TEXT NOT NULL,
            observation_id TEXT,
            status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'error')),
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _load_pending(
    conn: sqlite3.Connection,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], int]:
    conn.row_factory = sqlite3.Row
    mapped = _existing_mappings(conn)
    llm_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tools: dict[str, dict[str, Any]] = {}
    skipped = 0

    for row in conn.execute("SELECT * FROM llm_traces ORDER BY timestamp, id"):
        record = dict(row)
        if record["id"] in mapped:
            skipped += 1
            continue
        record["tool_calls"] = _loads(record["tool_calls"], [])
        llm_by_session[record["session_id"]].append(record)

    for row in conn.execute("SELECT * FROM tool_call_traces ORDER BY timestamp, id"):
        record = dict(row)
        if record["id"] in mapped:
            skipped += 1
            continue
        record["arguments"] = _loads(record["arguments"], {})
        record["result"] = _loads(record["result"], {})
        tools[record["id"]] = record

    return dict(llm_by_session), tools, skipped


def _metadata(local_trace_id: str, timestamp: str) -> dict[str, Any]:
    return {
        "cartwheel.backfilled": True,
        "cartwheel.backfill_source": BACKFILL_SOURCE,
        "cartwheel.local_trace_id": local_trace_id,
        "cartwheel.original_timestamp": timestamp,
        "cartwheel.fidelity_notice": FIDELITY_NOTICE,
    }


def _reserve(
    conn: sqlite3.Connection,
    records: list[tuple[str, str, str]],
) -> None:
    now = datetime.now(UTC).isoformat()
    conn.executemany(
        """
        INSERT INTO langfuse_backfill
        (local_trace_id, trace_type, langfuse_trace_id, status, created_at, updated_at)
        VALUES (?, ?, ?, 'pending', ?, ?)
        """,
        [(local_id, trace_type, trace_id, now, now) for local_id, trace_type, trace_id in records],
    )
    conn.commit()


def _finish(
    conn: sqlite3.Connection,
    observation_ids: dict[str, str | None],
    *,
    error: str | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    status = "error" if error else "completed"
    conn.executemany(
        """
        UPDATE langfuse_backfill
        SET observation_id = ?, status = ?, error = ?, updated_at = ?
        WHERE local_trace_id = ?
        """,
        [
            (observation_id, status, error, now, local_id)
            for local_id, observation_id in observation_ids.items()
        ],
    )
    conn.commit()


def backfill(
    db_path: Path = FEEDBACK_DB,
    *,
    apply: bool = False,
    client: Any | None = None,
) -> BackfillSummary:
    """Plan or apply an idempotent reconstruction of local feedback traces."""
    conn = sqlite3.connect(db_path)
    try:
        llm_by_session, tools, skipped = _load_pending(conn)
        session_ids = set(llm_by_session) | {tool["session_id"] for tool in tools.values()}
        summary = BackfillSummary(
            sessions=len(session_ids),
            llm_traces=sum(len(rows) for rows in llm_by_session.values()),
            tool_traces=len(tools),
            skipped=skipped,
            applied=apply,
        )
        if not apply or not session_ids:
            return summary

        _ensure_mapping_table(conn)
        lf = client or _client()
        for session_id in sorted(session_ids):
            llm_rows = llm_by_session.get(session_id, [])
            session_tools = {
                local_id: row
                for local_id, row in tools.items()
                if row["session_id"] == session_id
            }
            trace_id = lf.create_trace_id(seed=f"cartwheel-feedback:{session_id}")
            reservations = [
                (row["id"], "llm_response", trace_id) for row in llm_rows
            ] + [
                (row["id"], "tool_call", trace_id) for row in session_tools.values()
            ]
            _reserve(conn, reservations)
            observation_ids = {local_id: None for local_id, _, _ in reservations}

            try:
                root = lf.start_span(
                    trace_context={"trace_id": trace_id},
                    name="cartwheel.feedback_backfill",
                    metadata={
                        "cartwheel.backfilled": True,
                        "cartwheel.backfill_source": BACKFILL_SOURCE,
                        "cartwheel.session_id": session_id,
                        "cartwheel.fidelity_notice": FIDELITY_NOTICE,
                    },
                )
                root.update_trace(
                    name="Cartwheel historical session",
                    session_id=session_id,
                    input=llm_rows[0]["user_message"] if llm_rows else None,
                    output=llm_rows[-1]["assistant_response"] if llm_rows else None,
                    metadata={
                        "cartwheel.backfilled": True,
                        "cartwheel.backfill_source": BACKFILL_SOURCE,
                        "cartwheel.fidelity_notice": FIDELITY_NOTICE,
                    },
                    tags=["cartwheel-backfill"],
                )

                attached_tools: set[str] = set()
                for row in llm_rows:
                    generation = root.start_observation(
                        name="cartwheel.local_llm_response",
                        as_type="generation",
                        input=row["user_message"],
                        output=row["assistant_response"],
                        version=row["prompt_version"],
                        metadata=_metadata(row["id"], row["timestamp"]),
                    )
                    observation_ids[row["id"]] = generation.id
                    for tool_id in row["tool_calls"]:
                        tool_row = session_tools.get(tool_id)
                        if tool_row is None or tool_id in attached_tools:
                            continue
                        tool = generation.start_observation(
                            name=tool_row["tool_name"],
                            as_type="tool",
                            input=tool_row["arguments"],
                            output=tool_row["result"],
                            metadata=_metadata(tool_id, tool_row["timestamp"]),
                        )
                        observation_ids[tool_id] = tool.id
                        tool.end()
                        attached_tools.add(tool_id)
                    generation.end()

                for tool_id, tool_row in session_tools.items():
                    if tool_id in attached_tools:
                        continue
                    tool = root.start_observation(
                        name=tool_row["tool_name"],
                        as_type="tool",
                        input=tool_row["arguments"],
                        output=tool_row["result"],
                        metadata={
                            **_metadata(tool_id, tool_row["timestamp"]),
                            "cartwheel.orphaned_tool_trace": True,
                        },
                    )
                    observation_ids[tool_id] = tool.id
                    tool.end()

                root.end()
                lf.flush()
            except Exception as exc:
                _finish(conn, observation_ids, error=f"{type(exc).__name__}: {exc}")
                raise
            else:
                _finish(conn, observation_ids)

        return summary
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconstruct .feedback.db traces in Langfuse (dry-run by default)."
    )
    parser.add_argument("--db", type=Path, default=FEEDBACK_DB)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Send pending records to Langfuse and record their mappings.",
    )
    args = parser.parse_args()
    result = backfill(args.db, apply=args.apply)
    mode = "applied" if result.applied else "dry-run"
    print(
        f"{mode}: {result.sessions} sessions, {result.llm_traces} LLM traces, "
        f"{result.tool_traces} tool traces, {result.skipped} already mapped"
    )


if __name__ == "__main__":
    main()