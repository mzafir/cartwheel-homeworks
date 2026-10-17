"""Loopback-only control API for offline preview and isolated batch runs."""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from agent.config import REPO_ROOT
from scenarios.batch_runner import (
    MODEL_CREDENTIALS,
    build_plan,
    load_cases,
    model_options,
)

router = APIRouter(prefix="/api")
RUNS_DIR = REPO_ROOT / "scenarios" / "results" / "bulk-runs"
_RUNS: dict[str, subprocess.Popen[Any]] = {}


class BatchRunSettings(BaseModel):
    case_ids: list[str] | None = None
    model: str = Field(min_length=1, max_length=200)
    max_spend_usd: Decimal = Field(gt=0, max_digits=10, decimal_places=4)


def _loopback_only(request: Request) -> None:
    host = request.client.host if request.client else ""
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(status_code=403, detail="batch runs are loopback-only")


def _plan(settings: BatchRunSettings) -> dict[str, Any]:
    return build_plan(
        load_cases(),
        case_ids=settings.case_ids,
        model=settings.model,
        max_spend_usd=settings.max_spend_usd,
    )


def _run_dir(run_id: str) -> Path:
    try:
        safe_id = str(UUID(run_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="unknown batch run") from exc
    return RUNS_DIR / safe_id


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="unknown batch run") from exc


def _launch_worker(run_id: str, run_dir: Path) -> None:
    existing = _RUNS.get(run_id)
    if existing is not None and existing.poll() is None:
        raise HTTPException(status_code=409, detail="batch run is already active")
    log = (run_dir / "worker.log").open("ab")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "scenarios.batch_runner", "--run-id", run_id],
            cwd=REPO_ROOT,
            env=os.environ.copy(),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        log.close()
        raise HTTPException(status_code=503, detail="could not start batch worker") from exc
    log.close()
    _RUNS[run_id] = process


@router.get("/batch-tests/cases")
def get_batch_cases(request: Request) -> dict[str, Any]:
    _loopback_only(request)
    cases = load_cases()
    return {
        "count": len(cases),
        "cases": [
            {
                "id": case["id"],
                "role": case["role"],
                "query": case["query"],
                "tags": case["tags"],
                "checks": case["checks"],
                "review": case.get("review"),
            }
            for case in cases
        ],
    }


@router.get("/batch-tests/models")
def get_batch_models(request: Request) -> dict[str, Any]:
    _loopback_only(request)
    options = model_options()
    available = [item["id"] for item in options if item["available"]]
    preferred = os.environ.get("CARTWHEEL_MODEL", "gpt-4o-mini")
    default_model = preferred if preferred in available else (available[0] if available else "")
    return {"models": options, "default_model": default_model}


@router.post("/batch-tests/preview")
def preview_batch(settings: BatchRunSettings, request: Request) -> dict[str, Any]:
    _loopback_only(request)
    try:
        return _plan(settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/batch-runs", status_code=status.HTTP_202_ACCEPTED)
def start_batch(settings: BatchRunSettings, request: Request) -> dict[str, Any]:
    _loopback_only(request)
    try:
        plan = _plan(settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if plan["case_count"] == 0:
        raise HTTPException(status_code=422, detail="select at least one case")
    if plan["runnable_case_count"] == 0:
        raise HTTPException(
            status_code=422,
            detail="the spend ceiling does not cover the per-case reserve",
        )
    credential_env = MODEL_CREDENTIALS[settings.model]
    if not os.environ.get(credential_env):
        raise HTTPException(
            status_code=422,
            detail=f"model unavailable; configure {credential_env} in the local .env",
        )
    if any(process.poll() is None for process in _RUNS.values()):
        raise HTTPException(status_code=409, detail="a batch run is already active")

    run_id = str(uuid4())
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    config = settings.model_dump(mode="json")
    (run_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "state": "queued",
                "model": settings.model,
                "total": plan["case_count"],
                "completed": 0,
                "spent_usd": 0,
                "max_spend_usd": float(settings.max_spend_usd),
                "current_case_id": None,
                "stop_reason": None,
                "created_at": time.time(),
            },
            indent=2,
        )
        + "\n"
    )
    _launch_worker(run_id, run_dir)
    return {"run_id": run_id, "state": "queued", "plan": plan}


@router.get("/batch-runs/{run_id}")
def get_batch_status(run_id: str, request: Request) -> dict[str, Any]:
    _loopback_only(request)
    run_dir = _run_dir(run_id)
    status_data = _read_json(run_dir / "status.json")
    results_path = run_dir / "results.jsonl"
    latest: dict[str, dict[str, Any]] = {}
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                latest[row["case_id"]] = row
    status_data["results"] = list(latest.values())
    process = _RUNS.get(str(UUID(run_id)))
    if process is not None and process.poll() is not None and status_data["state"] in {
        "queued",
        "running",
    }:
        status_data["state"] = "failed"
        status_data["stop_reason"] = f"worker exited with code {process.returncode}"
    return status_data


@router.post("/batch-runs/{run_id}/stop")
def stop_batch(run_id: str, request: Request) -> dict[str, str]:
    _loopback_only(request)
    run_dir = _run_dir(run_id)
    _read_json(run_dir / "status.json")
    (run_dir / "cancel.requested").write_text("stop after the current case\n")
    return {"run_id": str(UUID(run_id)), "state": "stop_requested"}


@router.post("/batch-runs/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
def resume_batch(run_id: str, request: Request) -> dict[str, str]:
    _loopback_only(request)
    run_id = str(UUID(run_id))
    run_dir = _run_dir(run_id)
    current = _read_json(run_dir / "status.json")
    if current.get("state") in {
        "completed",
        "queued",
        "running",
        "stopped_budget",
    }:
        raise HTTPException(status_code=409, detail="batch run is not resumable")
    (run_dir / "cancel.requested").unlink(missing_ok=True)
    current.update(state="queued", stop_reason=None, resumed_at=time.time())
    (run_dir / "status.json").write_text(json.dumps(current, indent=2) + "\n")
    _launch_worker(run_id, run_dir)
    return {"run_id": run_id, "state": "queued"}