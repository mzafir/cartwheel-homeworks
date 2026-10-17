"""Tracing setup and the hand-written instrumentation for Homework 2.

`setup_tracing()` is the whole course stack: the Langfuse client reads
LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_HOST from the
environment and registers an OpenTelemetry tracer provider.
OpenLLMetry's OpenAI Agents integration records agent, model, and tool spans
using OTel GenAI attributes. Students add request spans,
auth context and permission-denied results as span
attributes (the `cartwheel.*` namespace from the Module 1 outline,
Artifact G).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.tracing import set_trace_processors
from agents.tracing.processors import default_processor
from opentelemetry import trace

if TYPE_CHECKING:
    from agent.auth import AuthContext

REPO_ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("cartwheel.instrument")

_genai_instrumented = False
_openai_tracing_enabled = False


def configure_model_tracing(*, openai_model: bool) -> None:
    """Remove implicit hosted export for non-OpenAI models.

    SDK processors are process-wide. Preserve either explicitly selected course
    destination; do not globally disable spans, which would also break Langfuse.
    """
    if not openai_model and not _genai_instrumented and not _openai_tracing_enabled:
        set_trace_processors([])


def setup_openai_tracing() -> bool:
    """Explicitly select hosted tracing, including for non-OpenAI inference."""
    global _openai_tracing_enabled
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ValueError("--trace-openai requires OPENAI_API_KEY; omit the flag for local chat")
    set_trace_processors([default_processor()])
    _openai_tracing_enabled = True
    return True



_USAGE_ATTRIBUTE_KEYS = (
    ("input_tokens", "gen_ai.usage.input_tokens"),
    ("output_tokens", "gen_ai.usage.output_tokens"),
    ("total_tokens", "gen_ai.usage.total_tokens"),
)


def record_generation_usage_fallback(otel_span: Any, span_data: Any) -> bool:
    """Copy LiteLLM token usage onto a generation span the hook left at zero.

    OpenLLMetry's OpenAI Agents hook reads usage only from
    `span_data.response.usage`, which the SDK fills for the OpenAI Responses
    API. `LitellmModel` (Anthropic, Together, ...) stores the same counts in the
    `span_data.usage` dict and leaves `response` unset, so Langfuse showed
    0 tokens for every non-OpenAI generation. Returns True when attributes
    were written.
    """
    if getattr(span_data, "response", None) is not None:
        return False
    usage = getattr(span_data, "usage", None)
    if not isinstance(usage, dict):
        return False
    wrote = False
    for usage_key, attribute in _USAGE_ATTRIBUTE_KEYS:
        value = usage.get(usage_key)
        if isinstance(value, int) and not isinstance(value, bool):
            otel_span.set_attribute(attribute, value)
            wrote = True
    return wrote


def _patch_generation_usage(processor_cls: Any) -> None:
    """Wrap the hook's generation finaliser with the LiteLLM usage fallback."""
    original = processor_cls._end_generation_span
    if getattr(original, "_cartwheel_usage_fallback", False):
        return

    def _end_generation_span(self: Any, otel_span: Any, span_data: Any, trace_content: bool) -> None:
        original(self, otel_span, span_data, trace_content)
        record_generation_usage_fallback(otel_span, span_data)

    _end_generation_span._cartwheel_usage_fallback = True  # type: ignore[attr-defined]
    processor_cls._end_generation_span = _end_generation_span


def instrument_genai(tracer_provider: Any) -> None:
    """Install GenAI recording once, using the supplied OTel provider."""
    global _genai_instrumented
    if _genai_instrumented:
        return
    from opentelemetry.instrumentation.openai_agents import OpenAIAgentsInstrumentor
    from opentelemetry.instrumentation.openai_agents._hooks import OpenTelemetryTracingProcessor

    _patch_generation_usage(OpenTelemetryTracingProcessor)
    os.environ.setdefault("TRACELOOP_TRACE_CONTENT", "false")
    # Export only through Langfuse, not the SDK's separate hosted tracing path.
    instrumentor = OpenAIAgentsInstrumentor(replace_existing_processors=True)
    instrumentor.instrument(tracer_provider=tracer_provider)
    if not instrumentor.is_instrumented_by_opentelemetry:
        raise RuntimeError("OpenAI Agents tracing instrumentation failed to install")
    _genai_instrumented = True


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ (existing vars win).

    A tiny loader so the repo does not need python-dotenv. Lines starting
    with '#' and blank lines are ignored. Values are never logged.
    """
    path = path or REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            os.environ.setdefault(key, value)


def setup_tracing() -> bool:
    """Install Langfuse tracing; return False when credentials are missing."""
    load_env()
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        log.warning(
            "LANGFUSE_PUBLIC_KEY is not set; tracing is off. Start the stack "
            "(docker compose -f observability/docker-compose.yml up -d) and "
            "copy .env.example to .env."
        )
        return False
    from langfuse import get_client

    get_client()  # registers the OTel tracer provider from LANGFUSE_* env vars
    instrument_genai(trace.get_tracer_provider())
    # Preserve processor replacement for callers such as the server, which
    # ignore our return value. A missing secret makes Langfuse a no-op client;
    # returning before replacement would leave hosted OpenAI export active.
    if not os.environ.get("LANGFUSE_SECRET_KEY"):
        return False
    log.info("tracing enabled; spans go to %s", os.environ.get("LANGFUSE_HOST"))
    return True


def record_tool_result(ctx: "AuthContext", result: dict[str, Any]) -> None:
    """Add authenticated identity and permission attributes to the active tool span.

    OpenLLMetry creates the tool span and records its name, arguments, and
    result. The tool wrappers call this helper before that span ends.
    Add the caller's user_role and string user_id, plus the string store_id
    for merchants, then record the permission decision with the helper below.
    When tracing is off, the active span is non-recording and this is a no-op.
    """
    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.set_attribute("cartwheel.user_role", ctx.role)
    span.set_attribute("cartwheel.user_id", str(ctx.user_id))
    if ctx.store_id is not None:
        span.set_attribute("cartwheel.store_id", str(ctx.store_id))
    _set_permission_denied_attributes(span, result)


def _set_permission_denied_attributes(
    span: trace.Span, result: dict[str, Any]
) -> None:
    """Set the permission-denied attributes on a tool span.

    Contract (Module 1 outline, Artifact G):
      - `result` is the structured dict a tool returned (see agent/auth.py
        for the convention).
      - Always set the span attribute "cartwheel.permission_denied" to a
        bool: True when result["error"] == "permission_denied", else False.
        Use result.get, since success dicts have no "error" key.
      - When it is True, also set "cartwheel.permission_denied.reason" to
        result["reason"] (default to "" if the reason is missing).
      - Set attributes with span.set_attribute(name, value). Do not raise on
        odd input; any dict without the permission_denied error code is
        simply False.

    Why this exists: permission-denied events are gold for Module 4, and
    the smoke report counts them and Module 3 asserts on them. This is the one place in the
    course where you touch instrumentation by hand.
    """
    is_denied = result.get("error") == "permission_denied"
    span.set_attribute("cartwheel.permission_denied", is_denied)
    if is_denied:
        span.set_attribute("cartwheel.permission_denied.reason", result.get("reason", ""))
