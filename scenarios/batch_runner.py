"""Offline planning and deterministic checks for the Cartwheel batch runner."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = REPO_ROOT / "scenarios" / "bulk_queries.jsonl"
BATCH_SIZE = 10
REQUEST_INTERVAL_S = 5
DEFAULT_USERS = {"shopper": 1, "merchant": 9001, "support": 9501}
CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
CHECK_TYPES = {"tool_called", "tool_error", "reply_contains", "reply_not_contains"}
RATE_CARD_AS_OF = "2026-10-17"
RESERVE_INPUT_TOKENS_PER_CASE = 12_000
RESERVE_OUTPUT_TOKENS_PER_CASE = 3_000
MODEL_PRICING_USD_PER_MILLION = {
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    "claude-opus-4-6": (Decimal("5.00"), Decimal("25.00")),
    "glm-5.2": (Decimal("1.40"), Decimal("4.40")),
}
MODEL_LABELS = {
    "gpt-4o-mini": "GPT-4o mini",
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "claude-opus-4-6": "Claude Opus 4.6",
    "glm-5.2": "GLM-5.2",
}
MODEL_CREDENTIALS = {
    "gpt-4o-mini": "OPENAI_API_KEY",
    "claude-haiku-4-5": "ANTHROPIC_API_KEY",
    "claude-opus-4-6": "ANTHROPIC_API_KEY",
    "glm-5.2": "TOGETHER_API_KEY",
}


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    errors = validate_cases(cases)
    if errors:
        raise ValueError("invalid Cartwheel query bank: " + "; ".join(errors))
    return cases


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    role_counts = {role: 0 for role in DEFAULT_USERS}
    if len(cases) != 100:
        errors.append(f"expected exactly 100 cases, found {len(cases)}")
    seen: set[str] = set()
    for index, case in enumerate(cases):
        prefix = f"case[{index}]"
        case_id = case.get("id")
        role = case.get("role")
        if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
            errors.append(f"{prefix} has an invalid id")
        elif case_id in seen:
            errors.append(f"duplicate case id {case_id}")
        else:
            seen.add(case_id)
        if role not in DEFAULT_USERS:
            errors.append(f"{prefix} has an unsupported role")
        else:
            role_counts[role] += 1
        if not isinstance(case.get("user_id"), int) or case.get("user_id", 0) <= 0:
            errors.append(f"{prefix} has an invalid user_id")
        if role in DEFAULT_USERS and case.get("user_id") != DEFAULT_USERS[role]:
            errors.append(f"{prefix} user_id does not match its role")
        if not isinstance(case.get("query"), str) or not case.get("query", "").strip():
            errors.append(f"{prefix} has an empty query")
        if not isinstance(case.get("tags"), list) or not case["tags"]:
            errors.append(f"{prefix} needs at least one coverage tag")
        checks = case.get("checks")
        if not isinstance(checks, list):
            errors.append(f"{prefix} checks must be a list")
            continue
        if not checks and not (isinstance(case.get("review"), str) and case["review"].strip()):
            errors.append(f"{prefix} needs deterministic checks or a review note")
        for check in checks:
            if not isinstance(check, dict) or check.get("type") not in CHECK_TYPES:
                errors.append(f"{prefix} contains an unsupported check")
            elif check["type"] in {"tool_called", "tool_error"} and not check.get("name"):
                errors.append(f"{prefix} tool checks need a name")
            elif check["type"] == "tool_error" and not check.get("error"):
                errors.append(f"{prefix} error checks need an error code")
            elif check["type"].startswith("reply_") and not check.get("text"):
                errors.append(f"{prefix} reply checks need text")
    for role, count in role_counts.items():
        if count < 20:
            errors.append(f"role {role} needs at least 20 cases, found {count}")
    return errors


def select_cases(
    cases: list[dict[str, Any]], case_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    if case_ids is None:
        return cases
    requested = set(case_ids)
    known = {case["id"] for case in cases}
    unknown = sorted(requested - known)
    if unknown:
        raise ValueError("unknown case ids: " + ", ".join(unknown))
    if len(requested) != len(case_ids):
        raise ValueError("case ids must be unique")
    return [case for case in cases if case["id"] in requested]


def case_manifest_hash(case: dict[str, Any], model: str) -> str:
    payload = json.dumps(
        {"case": case, "model": model}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def model_options() -> list[dict[str, str | bool]]:
    return [
        {
            "id": key,
            "label": MODEL_LABELS[key],
            "credential_env": MODEL_CREDENTIALS[key],
            "available": bool(os.environ.get(MODEL_CREDENTIALS[key])),
        }
        for key in MODEL_PRICING_USD_PER_MILLION
    ]


def cost_for_usage(input_tokens: int, output_tokens: int, model: str) -> Decimal:
    try:
        input_rate, output_rate = MODEL_PRICING_USD_PER_MILLION[model]
    except KeyError as exc:
        raise ValueError(f"unsupported model for spend estimation: {model}") from exc
    return (
        Decimal(input_tokens) * input_rate
        + Decimal(output_tokens) * output_rate
    ) / Decimal(1_000_000)


def build_plan(
    cases: list[dict[str, Any]],
    *,
    case_ids: list[str] | None,
    model: str,
    max_spend_usd: Decimal,
) -> dict[str, Any]:
    if not model.strip():
        raise ValueError("an explicit model is required")
    if model not in MODEL_PRICING_USD_PER_MILLION:
        raise ValueError(f"unsupported model for spend estimation: {model}")
    if max_spend_usd <= 0:
        raise ValueError("max_spend_usd must be positive")

    selected = select_cases(cases, case_ids)
    reserve = cost_for_usage(
        RESERVE_INPUT_TOKENS_PER_CASE,
        RESERVE_OUTPUT_TOKENS_PER_CASE,
        model,
    )
    runnable_count = min(
        len(selected),
        math.floor(max_spend_usd / reserve) if reserve else 0,
    )
    batches = [
        [case["id"] for case in selected[offset : offset + BATCH_SIZE]]
        for offset in range(0, len(selected), BATCH_SIZE)
    ]
    waits = max(0, len(selected) - 1)
    return {
        "model": model,
        "case_count": len(selected),
        "case_ids": [case["id"] for case in selected],
        "batch_size": BATCH_SIZE,
        "batches": batches,
        "interval_seconds": REQUEST_INTERVAL_S,
        "wait_count": waits,
        "estimated_wait_seconds": waits * REQUEST_INTERVAL_S,
        "reserve_usd_per_case": float(reserve),
        "estimated_total_usd": float(reserve * len(selected)),
        "max_spend_usd": float(max_spend_usd),
        "rate_card_as_of": RATE_CARD_AS_OF,
        "runnable_case_count": runnable_count,
        "budget_limited": runnable_count < len(selected),
    }


def evaluate_case(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    calls = response.get("tool_calls") or []
    reply = response.get("reply") or ""
    for expected in case["checks"]:
        kind = expected["type"]
        if kind == "tool_called":
            passed = any(call.get("name") == expected["name"] for call in calls)
        elif kind == "tool_error":
            passed = any(
                call.get("name") == expected["name"]
                and (call.get("result") or {}).get("error") == expected["error"]
                for call in calls
            )
        elif kind == "reply_contains":
            passed = expected["text"].casefold() in reply.casefold()
        else:
            passed = expected["text"].casefold() not in reply.casefold()
        checks.append({"check": expected, "passed": passed})
    if not checks:
        status = "inconclusive"
    else:
        status = "passed" if all(item["passed"] for item in checks) else "failed"
    return {"status": status, "checks": checks}


def _json_request(
    url: str, payload: dict[str, Any] | None = None, token: str | None = None
) -> dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Cartwheel API returned HTTP {exc.code}: {detail}") from exc


def _allocate_port() -> int:
    for port in range(59000, 60000):
        with socket.socket() as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no available loopback port in 59000-59999")


def _wait_for_api(process: subprocess.Popen[Any], base_url: str) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"isolated Cartwheel API exited with {process.returncode}")
        try:
            _json_request(f"{base_url}/health")
            return
        except (OSError, RuntimeError, urllib.error.URLError):
            time.sleep(0.2)
    raise TimeoutError("isolated Cartwheel API did not become healthy within 30 seconds")


def _run_isolated_case(
    case: dict[str, Any],
    *,
    model: str,
    seed_db: Path,
    seed_policies: Path,
    attempt_dir: Path,
) -> dict[str, Any]:
    attempt_dir.mkdir(parents=True, exist_ok=True)
    world_db = attempt_dir / "cartwheel.db"
    policies_dir = attempt_dir / "policies"
    sessions_db = attempt_dir / ".sessions.db"
    feedback_db = attempt_dir / ".feedback.db"
    shutil.copy2(seed_db, world_db)
    shutil.copytree(seed_policies, policies_dir)

    port = _allocate_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "CARTWHEEL_DB": str(world_db),
            "CARTWHEEL_POLICIES_DIR": str(policies_dir),
            "CARTWHEEL_SESSIONS_DB": str(sessions_db),
            "CARTWHEEL_FEEDBACK_DB": str(feedback_db),
        }
    )
    with (attempt_dir / "server.log").open("wb") as server_log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "server.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_api(process, base_url)
            session = _json_request(
                f"{base_url}/sessions",
                {"user_id": case["user_id"], "role": case["role"]},
            )
            return _json_request(
                f"{base_url}/sessions/{session['session_id']}/messages",
                {
                    "message": case["query"],
                    "model": model,
                    "scenario_id": case["id"],
                },
                token=session["token"],
            )
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _read_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_status(path: Path, status: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(status, indent=2) + "\n")
    temporary.replace(path)


def _is_cancelled(run_dir: Path) -> bool:
    return (run_dir / "cancel.requested").exists()


def run_worker(run_id: str) -> None:
    run_id = str(UUID(run_id))
    run_dir = (REPO_ROOT / "scenarios" / "results" / "bulk-runs" / run_id).resolve()
    if run_dir.parent != (REPO_ROOT / "scenarios" / "results" / "bulk-runs").resolve():
        raise ValueError("invalid run directory")
    config = json.loads((run_dir / "config.json").read_text())
    cases = load_cases()
    selected = select_cases(cases, config.get("case_ids"))
    plan = build_plan(
        cases,
        case_ids=config.get("case_ids"),
        model=config["model"],
        max_spend_usd=Decimal(str(config["max_spend_usd"])),
    )
    results_path = run_dir / "results.jsonl"
    status_path = run_dir / "status.json"
    old_results = _read_results(results_path)
    latest = {row["case_id"]: row for row in old_results}
    selected_by_id = {case["id"]: case for case in selected}
    skipped = set()
    for case_id, row in latest.items():
        case = selected_by_id.get(case_id)
        if (
            case is not None
            and row.get("status") == "completed"
            and (row.get("usage") or {}).get("available") is True
            and row.get("manifest_hash") == case_manifest_hash(case, config["model"])
        ):
            skipped.add(case_id)
    completed_cost = sum(
        Decimal(str(row.get("cost_usd", 0)))
        for case_id, row in latest.items()
        if case_id in skipped
    )
    max_spend = Decimal(str(config["max_spend_usd"]))
    reserve = Decimal(str(plan["reserve_usd_per_case"]))
    status: dict[str, Any] = {
        "run_id": run_id,
        "state": "running",
        "model": config["model"],
        "total": len(selected),
        "completed": len(skipped),
        "skipped": len(skipped),
        "spent_usd": float(completed_cost),
        "max_spend_usd": float(max_spend),
        "current_case_id": None,
        "stop_reason": None,
    }
    _write_status(status_path, status)

    seed_dir = run_dir / "seed"
    seed_db = seed_dir / "cartwheel.db"
    seed_policies = seed_dir / "policies"
    if not seed_db.exists():
        seed_dir.mkdir(parents=True, exist_ok=True)
        from seed.generate import generate_world

        generate_world(scale="dev", db_path=seed_db, policies_dir=seed_policies)

    try:
        for case in selected:
            manifest = case_manifest_hash(case, config["model"])
            if case["id"] in skipped:
                continue
            if _is_cancelled(run_dir):
                status.update(state="stopped", stop_reason="cancelled by operator")
                break
            if completed_cost + reserve > max_spend:
                status.update(
                    state="stopped_budget",
                    stop_reason="remaining budget is below the per-case reserve",
                )
                break

            status["current_case_id"] = case["id"]
            _write_status(status_path, status)
            attempt = sum(row["case_id"] == case["id"] for row in old_results) + 1
            attempt_dir = run_dir / "cases" / case["id"] / f"attempt-{attempt}"
            attempt_dir.mkdir(parents=True, exist_ok=False)
            started = time.time()
            try:
                response = _run_isolated_case(
                    case,
                    model=config["model"],
                    seed_db=seed_db,
                    seed_policies=seed_policies,
                    attempt_dir=attempt_dir,
                )
                usage = response.get("usage") or {}
                if not usage.get("available"):
                    outcome = {"status": "inconclusive", "checks": []}
                    cost = Decimal("0")
                    usage_reason = "provider usage was unavailable; stopped to preserve the spend cap"
                else:
                    cost = cost_for_usage(
                        int(usage["input_tokens"]),
                        int(usage["output_tokens"]),
                        config["model"],
                    )
                    outcome = evaluate_case(case, response)
                    usage_reason = None
                result = {
                    "case_id": case["id"],
                    "role": case["role"],
                    "tags": case["tags"],
                    "model": config["model"],
                    "manifest_hash": manifest,
                    "status": "completed",
                    "outcome": outcome["status"],
                    "checks": outcome["checks"],
                    "review": case.get("review"),
                    "query": case["query"],
                    "reply": response.get("reply", ""),
                    "tool_calls": response.get("tool_calls", []),
                    "usage": usage,
                    "cost_usd": float(cost),
                    "usage_note": usage_reason,
                    "duration_s": round(time.time() - started, 2),
                }
            except Exception as exc:
                result = {
                    "case_id": case["id"],
                    "role": case["role"],
                    "tags": case["tags"],
                    "model": config["model"],
                    "manifest_hash": manifest,
                    "status": "error",
                    "outcome": "inconclusive",
                    "review": case.get("review"),
                    "error": f"{type(exc).__name__}: {exc}",
                    "cost_usd": 0,
                    "duration_s": round(time.time() - started, 2),
                }
                usage_reason = "API error; stopped because model usage could not be confirmed"

            with results_path.open("a") as output:
                output.write(json.dumps(result, sort_keys=True) + "\n")
                output.flush()
                os.fsync(output.fileno())
            old_results.append(result)
            if result.get("status") == "completed":
                completed_cost += Decimal(str(result.get("cost_usd", 0)))
                status["completed"] += 1
                status["spent_usd"] = float(completed_cost)
            status["current_case_id"] = None
            if usage_reason:
                status.update(state="stopped_usage_unavailable", stop_reason=usage_reason)
                break
            if completed_cost >= max_spend:
                status.update(
                    state="stopped_budget",
                    stop_reason="measured usage reached the configured spend ceiling",
                )
                break
            _write_status(status_path, status)
            if case is not selected[-1]:
                time.sleep(REQUEST_INTERVAL_S)
        else:
            status.update(state="completed", stop_reason=None)
    except Exception as exc:
        status.update(state="failed", stop_reason=f"{type(exc).__name__}: {exc}")
    finally:
        status["finished_at"] = time.time()
        status["current_case_id"] = None
        _write_status(status_path, status)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run isolated Cartwheel API test cases.")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    run_worker(args.run_id)


if __name__ == "__main__":
    main()