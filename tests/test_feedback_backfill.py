from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from scripts.backfill_feedback_to_langfuse import FIDELITY_NOTICE, backfill


class FakeObservation:
    def __init__(self, observation_id: str, data: dict[str, Any]) -> None:
        self.id = observation_id
        self.data = data
        self.children: list[FakeObservation] = []
        self.trace_updates: list[dict[str, Any]] = []
        self.ended = False

    def start_observation(self, **kwargs: Any) -> "FakeObservation":
        child = FakeObservation(f"observation-{len(self.children) + 1}", kwargs)
        self.children.append(child)
        return child

    def update_trace(self, **kwargs: Any) -> None:
        self.trace_updates.append(kwargs)

    def end(self) -> None:
        self.ended = True


class FakeLangfuse:
    def __init__(self) -> None:
        self.roots: list[FakeObservation] = []
        self.flushes = 0

    def create_trace_id(self, *, seed: str) -> str:
        return f"trace:{seed}"

    def start_span(self, **kwargs: Any) -> FakeObservation:
        root = FakeObservation("root-observation", kwargs)
        self.roots.append(root)
        return root

    def flush(self) -> None:
        self.flushes += 1


def _create_feedback_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE llm_traces (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            user_message TEXT NOT NULL,
            assistant_response TEXT NOT NULL,
            tool_calls TEXT NOT NULL,
            timestamp TEXT NOT NULL
        );
        CREATE TABLE tool_call_traces (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            arguments TEXT NOT NULL,
            result TEXT NOT NULL,
            timestamp TEXT NOT NULL
        );
        INSERT INTO tool_call_traces VALUES (
            'tool-1', 'session-1', 'get_order', '{"order_id": 42}',
            '{"status": "delivered"}', '2026-09-01T10:00:01'
        );
        INSERT INTO llm_traces VALUES (
            'llm-1', 'session-1', 'prompt-v1', 'Where is order 42?',
            'It was delivered.', '["tool-1"]', '2026-09-01T10:00:00'
        );
        """
    )
    conn.commit()
    conn.close()


def test_backfill_is_reconstructed_and_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "feedback.db"
    _create_feedback_db(db_path)
    client = FakeLangfuse()

    first = backfill(db_path, apply=True, client=client)

    assert (first.sessions, first.llm_traces, first.tool_traces) == (1, 1, 1)
    assert client.flushes == 1
    root = client.roots[0]
    assert root.data["trace_context"] == {
        "trace_id": "trace:cartwheel-feedback:session-1"
    }
    generation = root.children[0]
    assert generation.data["as_type"] == "generation"
    assert generation.data["metadata"]["cartwheel.backfilled"] is True
    assert generation.data["metadata"]["cartwheel.fidelity_notice"] == FIDELITY_NOTICE
    tool = generation.children[0]
    assert tool.data["as_type"] == "tool"
    assert tool.data["name"] == "get_order"

    conn = sqlite3.connect(db_path)
    mappings = conn.execute(
        "SELECT local_trace_id, status FROM langfuse_backfill ORDER BY local_trace_id"
    ).fetchall()
    conn.close()
    assert mappings == [("llm-1", "completed"), ("tool-1", "completed")]

    second = backfill(db_path, apply=True, client=client)

    assert (second.sessions, second.llm_traces, second.tool_traces) == (0, 0, 0)
    assert second.skipped == 2
    assert len(client.roots) == 1
    assert client.flushes == 1