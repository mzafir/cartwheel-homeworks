from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from scenarios import batch_runner
from scenarios.batch_runner import (
    build_plan,
    case_manifest_hash,
    evaluate_case,
    validate_cases,
)


def make_cases(count: int = 100) -> list[dict]:
    roles = ("shopper", "merchant", "support")
    users = {"shopper": 1, "merchant": 9001, "support": 9501}
    def make_case(index: int) -> dict:
        role = roles[index % len(roles)]
        return {
            "id": f"case-{index:03d}",
            "role": role,
            "user_id": users[role],
            "query": f"Question {index}",
            "tags": ["smoke"],
            "checks": [],
            "review": "Review this case manually.",
        }

    return [make_case(index) for index in range(count)]


def test_plan_builds_ten_case_batches_and_request_interval() -> None:
    plan = build_plan(
        make_cases(),
        case_ids=None,
        model="gpt-4o-mini",
        max_spend_usd=Decimal("2"),
    )

    assert plan["case_count"] == 100
    assert [len(batch) for batch in plan["batches"]] == [10] * 10
    assert plan["wait_count"] == 99
    assert plan["estimated_wait_seconds"] == 495
    assert plan["runnable_case_count"] == 100


def test_plan_rejects_unknown_case_ids() -> None:
    with pytest.raises(ValueError, match="unknown case ids"):
        build_plan(
            make_cases(),
            case_ids=["missing-case"],
            model="gpt-4o-mini",
            max_spend_usd=Decimal("2"),
        )


def test_plan_caps_case_count_by_reserved_spend() -> None:
    plan = build_plan(
        make_cases(10),
        case_ids=None,
        model="gpt-4o-mini",
        max_spend_usd=Decimal("0.01"),
    )

    assert plan["runnable_case_count"] == 2
    assert plan["budget_limited"] is True


def test_unchecked_case_is_inconclusive_and_tool_checks_are_deterministic() -> None:
    unchecked = evaluate_case(make_cases(1)[0], {"reply": "hello", "tool_calls": []})
    assert unchecked["status"] == "inconclusive"

    case = {
        "checks": [
            {"type": "tool_called", "name": "get_order"},
            {"type": "tool_error", "name": "get_order", "error": "permission_denied"},
        ]
    }
    result = evaluate_case(
        case,
        {
            "reply": "I cannot access that order.",
            "tool_calls": [
                {"name": "get_order", "result": {"error": "permission_denied"}}
            ],
        },
    )
    assert result["status"] == "passed"


def test_model_pricing_estimate_is_calculated_in_usd() -> None:
    cost = batch_runner.cost_for_usage(100_000, 10_000, "gpt-4o-mini")
    assert cost == Decimal("0.021")

    with pytest.raises(ValueError, match="unsupported model"):
        batch_runner.cost_for_usage(100, 100, "unknown-model")


def test_model_options_report_provider_availability_without_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TOGETHER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("TOGETHER_API_KEY", "test-only-placeholder")

    options = {item["id"]: item for item in batch_runner.model_options()}

    assert options["gpt-4o-mini"]["credential_env"] == "OPENAI_API_KEY"
    assert options["gpt-4o-mini"]["available"] is False
    assert options["claude-haiku-4-5"]["available"] is True
    assert options["claude-opus-4-6"]["available"] is True
    assert options["glm-5.2"]["available"] is True
    assert "test-only-placeholder" not in repr(options)


def test_case_validation_rejects_duplicate_ids_and_role_mismatch() -> None:
    cases = make_cases(2)
    cases[1]["id"] = cases[0]["id"]
    cases[1]["user_id"] = 1
    errors = validate_cases(cases)

    assert any("duplicate case id" in error for error in errors)
    assert any("user_id does not match its role" in error for error in errors)


def test_manifest_changes_when_input_or_model_changes() -> None:
    case = make_cases(1)[0]

    original = case_manifest_hash(case, "gpt-4o-mini")
    changed_input = case_manifest_hash({**case, "query": "Different question"}, "gpt-4o-mini")
    changed_model = case_manifest_hash(case, "claude-haiku-4-5")

    assert original != changed_input
    assert original != changed_model


def test_isolated_case_uses_private_world_session_and_feedback_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_db = tmp_path / "seed.db"
    seed_db.write_text("seed")
    seed_policies = tmp_path / "seed-policies"
    seed_policies.mkdir()
    (seed_policies / "policy.md").write_text("policy")
    attempt_dir = tmp_path / "run" / "cases" / "case-001" / "attempt-1"
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

    def fake_popen(command, *, cwd, env, stdout, stderr):
        captured.update(command=command, cwd=cwd, env=env)
        return FakeProcess()

    def fake_request(url, payload=None, token=None):
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/sessions"):
            return {"session_id": "session-1", "token": "test-token"}
        return {"reply": "A reply", "tool_calls": [], "usage": {"available": True}}

    monkeypatch.setattr(batch_runner, "_allocate_port", lambda: 59087)
    monkeypatch.setattr(batch_runner.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(batch_runner, "_json_request", fake_request)

    response = batch_runner._run_isolated_case(
        make_cases(1)[0],
        model="gpt-4o-mini",
        seed_db=seed_db,
        seed_policies=seed_policies,
        attempt_dir=attempt_dir,
    )

    env = captured["env"]
    assert response["reply"] == "A reply"
    assert Path(env["CARTWHEEL_DB"]) == attempt_dir / "cartwheel.db"
    assert Path(env["CARTWHEEL_SESSIONS_DB"]) == attempt_dir / ".sessions.db"
    assert Path(env["CARTWHEEL_FEEDBACK_DB"]) == attempt_dir / ".feedback.db"
    assert Path(env["CARTWHEEL_POLICIES_DIR"]) == attempt_dir / "policies"