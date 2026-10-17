import asyncio
from decimal import Decimal

import httpx
import pytest

from server import app as server_app
from server import batch_runs
from scenarios.batch_runner import load_cases, model_options
from server.batch_runs import BatchRunSettings, _plan


def test_batch_routes_and_fixed_bank_are_registered() -> None:
    routes = set(server_app.app.openapi()["paths"])
    cases = load_cases()

    assert "/api/batch-tests/cases" in routes
    assert "/api/batch-tests/models" in routes
    assert "/api/batch-tests/preview" in routes
    assert "/api/batch-runs" in routes
    assert len(cases) == 100
    assert {item["id"] for item in model_options()} == {
        "gpt-4o-mini",
        "claude-haiku-4-5",
        "claude-opus-4-6",
        "glm-5.2",
    }


def test_preview_is_a_plan_only_operation() -> None:
    plan = _plan(
        BatchRunSettings(
            case_ids=["c001-shopper-order-status", "c002-shopper-list-orders"],
            model="gpt-4o-mini",
            max_spend_usd=Decimal("1"),
        )
    )

    assert plan["case_count"] == 2
    assert plan["wait_count"] == 1
    assert plan["estimated_wait_seconds"] == 5
    assert plan["runnable_case_count"] == 2
    assert plan["case_ids"] == ["c001-shopper-order-status", "c002-shopper-list-orders"]


def test_http_case_load_and_preview_do_not_start_a_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_worker(*args, **kwargs):
        pytest.fail("preview must not start a worker")

    monkeypatch.setattr(batch_runs.subprocess, "Popen", unexpected_worker)

    async def exercise_routes() -> None:
        transport = httpx.ASGITransport(
            app=server_app.app, client=("127.0.0.1", 41000)
        )
        async with httpx.AsyncClient(
            transport=transport, base_url="http://cartwheel"
        ) as client:
            cases_response = await client.get("/api/batch-tests/cases")
            assert cases_response.status_code == 200
            assert cases_response.json()["count"] == 100

            preview_response = await client.post(
                "/api/batch-tests/preview",
                json={
                    "case_ids": ["c001-shopper-order-status"],
                    "model": "gpt-4o-mini",
                    "max_spend_usd": "1.00",
                },
            )
            assert preview_response.status_code == 200
            preview = preview_response.json()
            assert preview["case_count"] == 1
            assert preview["estimated_total_usd"] == pytest.approx(0.0036)

    asyncio.run(exercise_routes())