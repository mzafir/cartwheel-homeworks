from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from agents.usage import Usage
from fastapi import HTTPException
from langfuse import LangfuseOtelSpanAttributes

from agent.agent import prompt_version
from server import app as server_app


class RecordingSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}

    def is_recording(self) -> bool:
        return True

    def set_attribute(self, name: str, value: Any) -> None:
        self.attributes[name] = value


class RecordingTracer:
    def __init__(self) -> None:
        self.span = RecordingSpan()

    @contextmanager
    def start_as_current_span(self, name: str):
        assert name == "cartwheel.session_message"
        yield self.span


def test_create_session_rejects_claimed_role_mismatch(world: dict) -> None:
    server_app._SESSIONS.clear()

    with pytest.raises(HTTPException) as exc_info:
        server_app.create_session(server_app.SessionCreate(user_id=1, role="merchant"))

    assert exc_info.value.status_code == 403


def test_server_lifespan_flushes_langfuse_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import langfuse

    class RecordingClient:
        flushed = False

        def flush(self) -> None:
            self.flushed = True

    client = RecordingClient()
    monkeypatch.setattr(server_app, "load_env", lambda: None)
    monkeypatch.setattr(server_app, "setup_tracing", lambda: True)
    monkeypatch.setattr(langfuse, "get_client", lambda: client)

    async def exercise_lifespan() -> None:
        async with server_app.lifespan(server_app.app):
            assert not client.flushed

    asyncio.run(exercise_lifespan())
    assert client.flushed


def test_token_cannot_authorize_another_session(world: dict) -> None:
    server_app._SESSIONS.clear()
    first = server_app.create_session(server_app.SessionCreate(user_id=1, role="shopper"))
    second = server_app.create_session(server_app.SessionCreate(user_id=1, role="shopper"))

    with pytest.raises(HTTPException) as exc_info:
        server_app._authorize(second["session_id"], f"Bearer {first['token']}")

    assert exc_info.value.status_code == 403


def test_message_endpoint_records_required_root_span_attributes(
    world: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    server_app._SESSIONS.clear()
    created = server_app.create_session(server_app.SessionCreate(user_id=1, role="shopper"))
    tracer = RecordingTracer()
    selected_model: dict[str, Any] = {}

    def fake_build_agent(ctx: Any, model: str | None = None) -> object:
        selected_model["value"] = model
        return object()

    async def fake_run(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            final_output="A traced reply",
            new_items=[],
            raw_responses=[
                SimpleNamespace(
                    usage=Usage(
                        requests=1,
                        input_tokens=123,
                        output_tokens=45,
                        total_tokens=168,
                    )
                )
            ],
        )

    monkeypatch.setenv("TRACELOOP_TRACE_CONTENT", "true")
    monkeypatch.setattr(server_app, "_tracer", tracer)
    monkeypatch.setattr(server_app, "build_agent", fake_build_agent)
    monkeypatch.setattr(server_app.Runner, "run", fake_run)
    monkeypatch.setattr(server_app.feedback, "log_llm_response", lambda *args: None)

    response = asyncio.run(
        server_app.post_message(
            created["session_id"],
            server_app.MessageIn(
                message="Show my recent orders.",
                model="test-model",
                scenario_id="hw2-test",
            ),
            authorization=f"Bearer {created['token']}",
        )
    )

    assert selected_model["value"] == "test-model"
    assert response["prompt_version"] == prompt_version()
    assert response["usage"] == {
        "requests": 1,
        "input_tokens": 123,
        "output_tokens": 45,
        "total_tokens": 168,
        "available": True,
    }
    assert tracer.span.attributes["cartwheel.session_id"] == created["session_id"]
    assert tracer.span.attributes["cartwheel.user_role"] == "shopper"
    assert tracer.span.attributes["cartwheel.user_id"] == "1"
    assert tracer.span.attributes["cartwheel.scenario_id"] == "hw2-test"
    assert tracer.span.attributes[LangfuseOtelSpanAttributes.TRACE_SESSION_ID] == created["session_id"]
    assert tracer.span.attributes[LangfuseOtelSpanAttributes.TRACE_USER_ID] == "1"
    assert tracer.span.attributes[
        f"{LangfuseOtelSpanAttributes.TRACE_METADATA}.cartwheel.prompt_version"
    ] == prompt_version()
    assert tracer.span.attributes[
        f"{LangfuseOtelSpanAttributes.OBSERVATION_METADATA}.cartwheel.scenario_id"
    ] == "hw2-test"
    assert "Show my recent orders." in tracer.span.attributes["gen_ai.input.messages"]
    assert "A traced reply" in tracer.span.attributes["gen_ai.output.messages"]


def test_litellm_generation_usage_falls_back_to_span_data_usage() -> None:
    from agents.tracing.span_data import GenerationSpanData
    from opentelemetry.instrumentation.openai_agents._hooks import OpenTelemetryTracingProcessor

    from observability import instrument

    instrument._patch_generation_usage(OpenTelemetryTracingProcessor)
    instrument._patch_generation_usage(OpenTelemetryTracingProcessor)  # idempotent
    span_data = GenerationSpanData(
        model="together_ai/zai-org/GLM-5.2",
        usage={
            "requests": 1,
            "input_tokens": 2219,
            "output_tokens": 65,
            "total_tokens": 2284,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    )
    otel_span = RecordingSpan()

    processor = OpenTelemetryTracingProcessor.__new__(OpenTelemetryTracingProcessor)
    processor._end_generation_span(otel_span, span_data, False)

    assert otel_span.attributes["gen_ai.usage.input_tokens"] == 2219
    assert otel_span.attributes["gen_ai.usage.output_tokens"] == 65
    assert otel_span.attributes["gen_ai.usage.total_tokens"] == 2284


def test_generation_usage_fallback_defers_to_response_usage() -> None:
    from observability import instrument

    span_data = SimpleNamespace(
        response=SimpleNamespace(usage=SimpleNamespace(input_tokens=5, output_tokens=1)),
        usage={"input_tokens": 999, "output_tokens": 999, "total_tokens": 1998},
    )
    otel_span = RecordingSpan()

    assert instrument.record_generation_usage_fallback(otel_span, span_data) is False
    assert otel_span.attributes == {}
