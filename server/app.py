"""The Cartwheel endpoint, with the session routes completed in Homework 2.

A thin FastAPI wrapper with three routes (Lecture 2.3):

  - POST /sessions            binds a user + role, returns a signed dev token
  - POST /sessions/{id}/messages   one conversation turn
  - GET  /health              liveness

Why an endpoint at all: one choke point to authenticate, log, sample,
rate-limit, and replay. Modules 3 and 4 need a surface to monitor and attack.

The token is dev-only auth: a base64 JSON payload signed with an HMAC over a
shared secret (CARTWHEEL_DEV_SECRET). It is not real auth; the *shape* (a
server-issued credential carrying user id + role that tools trust) is what
Module 4 attacks. In production you would stream responses and assemble the
final message in middleware; this server does not stream.

Run with:
    uv run uvicorn server.app:app --port 8010
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from agents import Runner, SQLiteSession
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from langfuse import LangfuseOtelSpanAttributes
from opentelemetry import trace
from pydantic import BaseModel

from agent import db, feedback
from agent.agent import build_agent, prompt_version
from agent.auth import ROLES, AuthContext
from agent.config import REPO_ROOT, db_path
from observability.instrument import load_env, setup_tracing
from server.homework_progress import build_homework_progress
from server.batch_runs import router as batch_runs_router

MAX_TURNS = 12  # cap runaway loops; keeps conversations bounded
SESSIONS_DB = Path(os.environ.get("CARTWHEEL_SESSIONS_DB", REPO_ROOT / ".sessions.db"))

_tracer = trace.get_tracer("cartwheel.server")
_logger = logging.getLogger("cartwheel.server")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    load_env()
    tracing_enabled = setup_tracing()
    try:
        yield
    finally:
        if tracing_enabled:
            try:
                from langfuse import get_client

                get_client().flush()
            except Exception as exc:
                _logger.warning("Langfuse flush failed during shutdown (%s)", type(exc).__name__)


app = FastAPI(title="Cartwheel support agent", lifespan=lifespan)
app.include_router(batch_runs_router)

# Add CORS middleware for the UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static UI files
ui_path = REPO_ROOT / "ui"
if ui_path.exists():
    app.mount("/ui", StaticFiles(directory=ui_path, html=True), name="ui")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    tb = traceback.format_exc()
    (REPO_ROOT / "server-error.log").write_text(tb)
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})

# session_id -> (AuthContext, SQLiteSession). In-memory on purpose: the trace
# store is the durable record, not this dict.
_SESSIONS: dict[str, tuple[AuthContext, SQLiteSession]] = {}


# ---------------------------------------------------------------------------
# Signed dev token: base64url(JSON payload) + "." + HMAC-SHA256 signature.
# ---------------------------------------------------------------------------


def _secret() -> bytes:
    return os.environ.get("CARTWHEEL_DEV_SECRET", "cartwheel-dev-secret").encode()


def create_token(payload: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True).encode()
    ).decode()
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str) -> dict[str, Any] | None:
    """Return the payload if the signature checks out, else None."""
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(body.encode()))
    except (binascii.Error, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


class SessionCreate(BaseModel):
    user_id: int
    role: str


class MessageIn(BaseModel):
    message: str
    model: str | None = None
    # Set by the scenario runner (Lecture 3) so a trace links back to its
    # ground truth. Manual sessions leave it null.
    scenario_id: str | None = None


@app.post("/sessions")
def create_session(body: SessionCreate) -> dict[str, Any]:
    """Bind a verified database user to a new server-side session.

    Validate the requested role, load the user from the database, and reject
    a request whose claimed role differs from the stored role. Create an
    AuthContext and SQLiteSession, save them in _SESSIONS, then return the
    session id and a signed token. The token payload must contain session_id,
    user_id, role, store_id, and issued_at.
    """
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"unknown role: {body.role!r}")
    
    conn = db.connect()
    try:
        user = db.get_user(conn, body.user_id)
    finally:
        conn.close()
    
    if user is None:
        raise HTTPException(status_code=404, detail=f"unknown user: {body.user_id}")
    
    if user.role != body.role:
        raise HTTPException(
            status_code=403,
            detail=f"user {body.user_id} has role {user.role!r}, not {body.role!r}",
        )
    
    ctx = AuthContext(user_id=user.id, role=user.role, store_id=user.store_id)
    session_id = str(uuid.uuid4())
    session = SQLiteSession(session_id, str(SESSIONS_DB))

    token_payload = {
        "session_id": session_id,
        "user_id": user.id,
        "role": user.role,
        "store_id": user.store_id,
        "issued_at": time.time(),
    }
    token = create_token(token_payload)
    _SESSIONS[session_id] = (ctx, session)
    
    return {"session_id": session_id, "token": token}


def _authorize(session_id: str, authorization: str | None) -> AuthContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    payload = verify_token(authorization.removeprefix("Bearer "))
    if payload is None:
        raise HTTPException(status_code=401, detail="bad token signature")
    if payload.get("session_id") != session_id:
        raise HTTPException(status_code=403, detail="token is for another session")
    if session_id not in _SESSIONS:
        raise HTTPException(status_code=404, detail="unknown session (server restarted?)")
    return _SESSIONS[session_id][0]


@app.post("/sessions/{session_id}/messages")
async def post_message(
    session_id: str,
    body: MessageIn,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Run one authenticated conversation turn inside a root trace span.

    Authorize the token, recover the server-side session, and build the agent
    for the authenticated context. Hash only the system prompt template.
    The cartwheel.session_message span must record the session id, user role,
    user id, prompt version, and a nonempty scenario id when one is supplied. Run the
    agent inside that span, then return the session id, final reply, and
    prompt version.
    When TRACELOOP_TRACE_CONTENT is true, record gen_ai.input.messages and
    gen_ai.output.messages on the root span as JSON arrays of OTel GenAI
    messages with role and parts fields.
    """
    ctx = _authorize(session_id, authorization)
    _, session = _SESSIONS[session_id]

    agent = build_agent(ctx, model=body.model)
    version = prompt_version()
    capture = os.environ.get("TRACELOOP_TRACE_CONTENT", "false").lower() == "true"

    with _tracer.start_as_current_span("cartwheel.session_message") as span:
        if span.is_recording():
            attributes = {
                "cartwheel.session_id": session_id,
                "cartwheel.user_role": ctx.role,
                "cartwheel.user_id": str(ctx.user_id),
                "cartwheel.prompt_version": version,
            }
            if body.scenario_id:
                attributes["cartwheel.scenario_id"] = body.scenario_id
            for name, value in attributes.items():
                span.set_attribute(name, value)
                span.set_attribute(
                    f"{LangfuseOtelSpanAttributes.TRACE_METADATA}.{name}", value
                )
                span.set_attribute(
                    f"{LangfuseOtelSpanAttributes.OBSERVATION_METADATA}.{name}", value
                )
            span.set_attribute(LangfuseOtelSpanAttributes.TRACE_NAME, "cartwheel.session_message")
            span.set_attribute(LangfuseOtelSpanAttributes.TRACE_SESSION_ID, session_id)
            span.set_attribute(LangfuseOtelSpanAttributes.TRACE_USER_ID, str(ctx.user_id))
            if capture:
                span.set_attribute(
                    "gen_ai.input.messages",
                    json.dumps(
                        [
                            {
                                "role": "user",
                                "parts": [{"type": "text", "content": body.message}],
                            }
                        ]
                    ),
                )

        result = await Runner.run(
            agent, body.message, session=session, context=ctx, max_turns=MAX_TURNS
        )
        reply = str(result.final_output)
        if span.is_recording() and capture:
            span.set_attribute(
                "gen_ai.output.messages",
                json.dumps(
                    [
                        {
                            "role": "assistant",
                            "parts": [{"type": "text", "content": reply}],
                        }
                    ]
                ),
            )

    tool_calls = _extract_tool_calls(result)
    tool_trace_ids = [
        feedback.log_tool_call(session_id, tc["name"], tc["arguments"], tc["result"])
        for tc in tool_calls
    ]
    feedback.log_llm_response(session_id, version, body.message, reply, tool_trace_ids)
    usage = _extract_usage(result)

    return {
        "session_id": session_id,
        "reply": reply,
        "tool_calls": tool_calls,
        "prompt_version": version,
        "usage": usage,
    }


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _extract_tool_calls(result: Any) -> list[dict[str, Any]]:
    """Pair each tool_call_item with its tool_call_output_item by call_id."""
    calls: dict[str, dict[str, Any]] = {}
    for item in getattr(result, "new_items", []):
        raw = getattr(item, "raw_item", None)
        if item.type == "tool_call_item":
            call_id = getattr(raw, "call_id", None) or getattr(raw, "id", "")
            calls[call_id] = {
                "name": getattr(raw, "name", "unknown"),
                "arguments": _parse_json(getattr(raw, "arguments", "{}")),
                "result": None,
            }
        elif item.type == "tool_call_output_item":
            call_id = raw.get("call_id", "") if isinstance(raw, dict) else getattr(raw, "call_id", "")
            output = getattr(item, "output", None)
            if call_id in calls:
                calls[call_id]["result"] = _parse_json(output)
    return list(calls.values())


def _extract_usage(result: Any) -> dict[str, int | bool]:
    totals = {
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    available = False
    for response in getattr(result, "raw_responses", []):
        usage = getattr(response, "usage", None)
        if usage is None:
            continue
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        request_count = int(getattr(usage, "requests", 0) or 0)
        available = available or input_tokens > 0 or output_tokens > 0
        totals["requests"] += request_count
        totals["input_tokens"] += input_tokens
        totals["output_tokens"] += output_tokens
        totals["total_tokens"] += int(
            getattr(usage, "total_tokens", 0) or input_tokens + output_tokens
        )
    return {**totals, "available": available}


class FeedbackSubmit(BaseModel):
    trace_id: str
    trace_type: str  # "tool_call" or "llm_response"
    rating: int | None = None  # 1 or -1
    annotation: str | None = None
    tags: list[str] | None = None


@app.post("/sessions/{session_id}/feedback")
async def submit_feedback_endpoint(
    session_id: str,
    body: FeedbackSubmit,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Submit feedback on a trace (tool call or LLM response)."""
    _authorize(session_id, authorization)

    feedback_id = feedback.submit_feedback(
        trace_id=body.trace_id,
        trace_type=body.trace_type,
        session_id=session_id,
        rating=body.rating,
        annotation=body.annotation,
        tags=body.tags
    )
    
    return {
        "feedback_id": feedback_id,
        "session_id": session_id,
        "trace_id": body.trace_id,
        "received": True
    }


@app.get("/sessions/{session_id}/traces")
def get_traces_endpoint(
    session_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Retrieve all traces and feedback for a session."""
    _authorize(session_id, authorization)

    traces = feedback.get_session_traces(session_id)
    
    return {
        "session_id": session_id,
        "traces": traces
    }


@app.get("/prompts")
def list_prompts(limit: int = 50) -> dict[str, Any]:
    """List all cached prompts from Redis."""
    try:
        from prompt_cache import PromptCache
        cache = PromptCache(backend="auto")
        prompts = cache.list_all(limit=limit)
        return {
            "prompts": prompts,
            "count": len(prompts),
            "backend": cache.backend_type
        }
    except Exception as e:
        return {
            "error": str(e),
            "prompts": [],
            "count": 0
        }


@app.get("/prompts/search")
def search_prompts(q: str, threshold: int = 60) -> dict[str, Any]:
    """Fuzzy search prompts by text, name, or tags."""
    try:
        from prompt_cache import PromptCache
        cache = PromptCache(backend="auto")
        results = cache.search(q, threshold=threshold)
        return {
            "query": q,
            "results": results,
            "count": len(results),
            "threshold": threshold
        }
    except Exception as e:
        return {
            "error": str(e),
            "query": q,
            "results": [],
            "count": 0
        }


@app.get("/prompts/{prompt_id}")
def get_prompt(prompt_id: str) -> dict[str, Any]:
    """Get a single prompt by ID."""
    try:
        from prompt_cache import PromptCache
        cache = PromptCache(backend="auto")
        prompt = cache.get_by_id(prompt_id)
        if prompt:
            return {"prompt": prompt}
        else:
            return {"error": f"Prompt {prompt_id} not found"}
    except Exception as e:
        return {"error": str(e)}


@app.post("/prompts/use/{prompt_id}")
def use_prompt(prompt_id: str) -> dict[str, Any]:
    """Mark a prompt as used and return it."""
    try:
        from prompt_cache import PromptCache
        cache = PromptCache(backend="auto")
        cache.mark_used(prompt_id)
        prompt = cache.get_by_id(prompt_id)
        return {
            "prompt": prompt,
            "marked_used": True
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "code_rev": 3,
        "db_exists": db_path().exists(),
        "active_sessions": len(_SESSIONS),
    }


@app.get("/api/homework-progress")
def homework_progress() -> dict[str, Any]:
    """Return live homework milestones derived from repository evidence."""
    return build_homework_progress(REPO_ROOT)
