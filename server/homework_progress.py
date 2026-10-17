"""Compute homework progress from repository evidence without storing state."""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _milestone(
    milestone_id: str,
    title: str,
    complete: bool,
    evidence: str,
    next_step: str,
) -> dict[str, Any]:
    return {
        "id": milestone_id,
        "title": title,
        "status": "complete" if complete else "pending",
        "evidence": evidence,
        "next_step": "Done" if complete else next_step,
    }


def _functions_implemented(path: Path, names: list[str]) -> tuple[bool, str]:
    if not path.exists():
        return False, f"Missing {path.name}"
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError) as exc:
        return False, f"Cannot inspect {path.name}: {exc}"
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = [name for name in names if name not in functions]
    unfinished = []
    for name in names:
        node = functions.get(name)
        if node and any(
            isinstance(child, ast.Raise)
            and isinstance(child.exc, ast.Call)
            and isinstance(child.exc.func, ast.Name)
            and child.exc.func.id == "NotImplementedError"
            for child in ast.walk(node)
        ):
            unfinished.append(name)
    pending = missing + unfinished
    if pending:
        return False, "Pending functions: " + ", ".join(pending)
    return True, f"Implemented: {', '.join(names)}"


def _jsonl_summary(path: Path) -> tuple[int, int, int]:
    if not path.exists():
        return 0, 0, 0
    records: list[dict[str, Any]] = []
    invalid = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            invalid += 1
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            invalid += 1
    met = sum(record.get("met_requirement") is True for record in records)
    return len(records), met, invalid


def _exists(root: Path, relative: str) -> bool:
    return (root / relative).exists()


def _all_exist(root: Path, paths: list[str]) -> tuple[bool, str]:
    missing = [path for path in paths if not _exists(root, path)]
    if missing:
        return False, "Missing: " + ", ".join(missing)
    return True, f"Present: {len(paths)}/{len(paths)} required artifacts"


def _homework(
    homework_id: str,
    title: str,
    module: int,
    milestones: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = sum(item["status"] == "complete" for item in milestones)
    total = len(milestones)
    if completed == total:
        status = "complete"
    elif completed:
        status = "in_progress"
    else:
        status = "pending"
    return {
        "id": homework_id,
        "title": title,
        "module": module,
        "status": status,
        "completed": completed,
        "total": total,
        "milestones": milestones,
    }


def build_homework_progress(root: Path) -> dict[str, Any]:
    """Return HW1-HW6 progress derived from files and implementation markers."""
    hw1_tools, hw1_tools_evidence = _functions_implemented(
        root / "agent/tools.py",
        ["get_policy", "search_products", "list_my_orders", "cancel_order", "find_order"],
    )
    transcript_path = root / "homework/module-1/hw1-session.jsonl"
    transcript_count, transcript_met, transcript_invalid = _jsonl_summary(transcript_path)
    hw1 = _homework(
        "HW1",
        "Implement and examine the support agent",
        1,
        [
            _milestone("hw1-tools", "Implement five support tools", hw1_tools, hw1_tools_evidence, "Complete the remaining tool contracts."),
            _milestone("hw1-records", "Record 10 valid conversations", transcript_count == 10 and transcript_invalid == 0, f"{transcript_count}/10 records; {transcript_invalid} invalid", "Record or repair the required JSONL conversations."),
            _milestone("hw1-quality", "Meet at least 9 conversation requirements", transcript_met >= 9, f"{transcript_met}/10 records meet requirements", "Rerun and replace failed conversations after the prompt revision."),
            _milestone("hw1-analysis", "Document and apply a prompt revision", _exists(root, "homework/module-1/hw1-part-c.md") and "Above-threshold refunds MUST escalate" in (root / "agent/agent.py").read_text(), "Part C document and mandatory escalation instruction checked", "Complete Part C and apply the tested prompt revision."),
            _milestone("hw1-video", "Record the submission video", False, "Manual evidence is not stored in the repository", "Record the <=5 minute HW1 walkthrough."),
        ],
    )

    hw2_functions, hw2_evidence = _functions_implemented(
        root / "observability/instrument.py",
        ["record_tool_result", "_set_permission_denied_attributes"],
    )
    hw2_server, hw2_server_evidence = _functions_implemented(
        root / "server/app.py", ["create_session", "post_message"]
    )
    traces_paths = [root / "hw2-traces.json", root / "homework/module-1/hw2-traces.json"]
    trace_count = 0
    for path in traces_paths:
        if path.exists():
            try:
                value = json.loads(path.read_text())
                trace_count = len(value) if isinstance(value, list) else 0
            except (json.JSONDecodeError, OSError):
                trace_count = 0
            break
    hw2 = _homework(
        "HW2",
        "Build the authenticated traced endpoint",
        1,
        [
            _milestone("hw2-spans", "Add identity and permission span attributes", hw2_functions, hw2_evidence, "Complete the instrumentation functions."),
            _milestone("hw2-endpoint", "Implement authenticated session and message endpoints", hw2_server, hw2_server_evidence, "Complete the endpoint functions."),
            _milestone("hw2-tests", "Add authentication and observability tests", _exists(root, "tests/test_observability.py"), "tests/test_observability.py " + ("exists" if _exists(root, "tests/test_observability.py") else "is missing"), "Create and pass tests/test_observability.py."),
            _milestone("hw2-traces", "Save exactly two inspected trace records", trace_count == 2, f"{trace_count}/2 trace records", "Inspect Langfuse and save hw2-traces.json."),
            _milestone("hw2-video", "Record the submission video", False, "Manual evidence is not stored in the repository", "Record the <=5 minute HW2 walkthrough."),
        ],
    )

    hw3_groups = [
        ("hw3-pilot", "Generate and review the pilot", ["scenarios/pilot_scenarios.jsonl", "scenarios/pilot-results.jsonl", "scenarios/pilot_review.jsonl"]),
        ("hw3-final", "Create and review 250 final scenarios", ["scenarios/support_scenarios.jsonl", "scenarios/support_review.jsonl", "scenarios/monitoring_scenarios.jsonl"]),
        ("hw3-run", "Run scenarios and export traces", ["scenarios/final-results.jsonl", "reports/smoke-output.txt", "traces/support_traces.json"]),
    ]
    hw3_milestones = []
    for milestone_id, title, paths in hw3_groups:
        complete, evidence = _all_exist(root, paths)
        hw3_milestones.append(_milestone(milestone_id, title, complete, evidence, "Create and validate the missing HW3 artifacts."))
    hw3_milestones.append(_milestone("hw3-video", "Record the submission video", False, "Manual evidence is not stored in the repository", "Record the <=5 minute HW3 walkthrough."))
    hw3 = _homework("HW3", "Create the support trace dataset", 1, hw3_milestones)

    hw4_groups = [
        ("hw4-sample", "Save the reviewed sample and annotations", ["analysis/state/sample_manifest.json", "analysis/state/annotations.json"]),
        ("hw4-taxonomy", "Define modes, suggestions, and labels", ["analysis/state/patterns.json", "analysis/state/suggestions.json", "analysis/state/labels"]),
        ("hw4-report", "Write review and interface reports", ["analysis/report/review_summary.md", "analysis/report/interface_comparison.md"]),
    ]
    hw4_milestones = []
    for milestone_id, title, paths in hw4_groups:
        complete, evidence = _all_exist(root, paths)
        hw4_milestones.append(_milestone(milestone_id, title, complete, evidence, "Complete the missing HW4 review artifacts."))
    hw4_milestones.append(_milestone("hw4-video", "Record the submission video", False, "Manual evidence is not stored in the repository", "Record the <=5 minute HW4 walkthrough."))
    hw4 = _homework("HW4", "Review traces and define failure modes", 2, hw4_milestones)

    hw5_groups = [
        ("hw5-labels", "Create balanced labels and evidence", ["analysis/state/hw5_labels"]),
        ("hw5-splits", "Freeze splits and exact judge inputs", ["analysis/state/splits.json", "analysis/state/hw5_trace_inputs.json"]),
        ("hw5-judge", "Save prompts, judge versions, and predictions", ["analysis/prompts", "analysis/state/judges", "analysis/run_judges.py"]),
        ("hw5-metrics", "Save development and test metrics", ["analysis/report"]),
    ]
    hw5_milestones = []
    for milestone_id, title, paths in hw5_groups:
        complete, evidence = _all_exist(root, paths)
        hw5_milestones.append(_milestone(milestone_id, title, complete, evidence, "Complete the missing HW5 judge artifacts."))
    hw5_milestones.append(_milestone("hw5-video", "Record the submission video", False, "Manual evidence is not stored in the repository", "Record the <=5 minute HW5 walkthrough."))
    hw5 = _homework("HW5", "Develop and validate an LLM judge", 2, hw5_milestones)

    hw6_passk, hw6_passk_evidence = _functions_implemented(
        root / "tests/eval/passk.py", ["pass_at_k", "pass_hat_k", "case_passes"]
    )
    hw6 = _homework(
        "HW6",
        "Build continuous integration evaluations",
        3,
        [
            _milestone("hw6-cases", "Create and classify evaluation cases", _exists(root, "eval_cases/cases.jsonl"), "eval_cases/cases.jsonl " + ("exists" if _exists(root, "eval_cases/cases.jsonl") else "is missing"), "Create and classify the evaluation cases."),
            _milestone("hw6-metrics", "Implement reliability metrics", hw6_passk, hw6_passk_evidence, "Implement pass_at_k, pass_hat_k, and case_passes."),
            _milestone("hw6-workflow", "Complete the GitHub Actions evaluation workflow", _exists(root, ".github/workflows/evals.yml"), ".github/workflows/evals.yml " + ("exists" if _exists(root, ".github/workflows/evals.yml") else "is missing"), "Complete the evaluation workflow."),
            _milestone("hw6-runs", "Record intentional regression CI runs", _exists(root, "ci-runs.json"), "ci-runs.json " + ("exists" if _exists(root, "ci-runs.json") else "is missing"), "Run the two CI revisions and save ci-runs.json."),
            _milestone("hw6-video", "Record the submission video", False, "Manual evidence is not stored in the repository", "Record the <=5 minute HW6 walkthrough."),
        ],
    )

    homeworks = [hw1, hw2, hw3, hw4, hw5, hw6]
    completed = sum(hw["status"] == "complete" for hw in homeworks)
    milestone_total = sum(hw["total"] for hw in homeworks)
    milestone_completed = sum(hw["completed"] for hw in homeworks)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "homeworks_complete": completed,
            "homeworks_total": len(homeworks),
            "milestones_complete": milestone_completed,
            "milestones_total": milestone_total,
            "percent": round(100 * milestone_completed / milestone_total),
        },
        "homeworks": homeworks,
    }