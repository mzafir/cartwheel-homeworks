from server.homework_progress import build_homework_progress

from agent.config import REPO_ROOT


def test_homework_progress_reports_released_assignments() -> None:
    progress = build_homework_progress(REPO_ROOT)

    assert [homework["id"] for homework in progress["homeworks"]] == [
        "HW1",
        "HW2",
        "HW3",
        "HW4",
        "HW5",
        "HW6",
    ]
    assert progress["summary"]["milestones_total"] == sum(
        homework["total"] for homework in progress["homeworks"]
    )


def test_homework_progress_matches_current_evidence() -> None:
    progress = build_homework_progress(REPO_ROOT)
    by_id = {homework["id"]: homework for homework in progress["homeworks"]}
    hw1 = {item["id"]: item for item in by_id["HW1"]["milestones"]}
    hw6 = {item["id"]: item for item in by_id["HW6"]["milestones"]}

    assert hw1["hw1-tools"]["status"] == "complete"
    assert hw1["hw1-quality"]["status"] == "pending"
    assert "7/10" in hw1["hw1-quality"]["evidence"]
    assert hw6["hw6-metrics"]["status"] == "pending"