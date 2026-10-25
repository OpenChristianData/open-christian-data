from pathlib import Path

from ocd_kernel.library.record_connections import _ticket_tasks
from ocd_kernel.library.record_read import RecordRead


SELECTOR = {"kind": "work", "namespace": "ocd", "id": "alpha"}


def write_task(path: Path, ticket_id: str, *, lifecycle: str = "in-progress", status: str = "Work is underway") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"**Ticket ID:** {ticket_id}\n"
        "**Work ID:** `alpha`\n"
        "**Triage label:** ready-for-agent\n"
        f"**Lifecycle:** {lifecycle}\n"
        f"**Status:** {status}\n"
        "**Task applicability:** current\n",
        encoding="utf-8",
    )


def test_discovers_canonical_issue_and_nested_ticket_but_not_plan_artifacts(tmp_path):
    packet = tmp_path / "plans/2026-10-02-current/issues/05-metadata.md"
    packet.parent.mkdir(parents=True)
    packet.write_text("**Ticket ID:** META-STRUCT-005\n**Lifecycle:** in-progress\n", encoding="utf-8")
    write_task(tmp_path / "plans/2026-10-02-current/issues/06-alpha.md", "META-STRUCT-006")
    write_task(tmp_path / "plans/2026-10-02-current/tickets/library/LIBRARY-901.md", "LIBRARY-901")
    write_task(tmp_path / "plans/2026-10-02-current/artifacts/review.md", "REVIEW-001")
    write_task(tmp_path / "plans/2026-10-02-current/general-plan.md", "PLAN-001")

    read = RecordRead(tmp_path)
    tasks = _ticket_tasks(read, SELECTOR, [])

    assert "plans/2026-10-02-current/issues/05-metadata.md" in read.inputs
    assert {task["task"] for task in tasks} == {"META-STRUCT-006", "LIBRARY-901"}


def test_archived_and_retired_task_homes_are_historical(tmp_path):
    write_task(tmp_path / "plans/2026-10-02-current/issues/_archive/04-old.md", "META-STRUCT-004")
    retired = tmp_path / "plans/2026-08-31-retired"
    (retired / "RETIREMENT.md").parent.mkdir(parents=True, exist_ok=True)
    (retired / "RETIREMENT.md").write_text("# Retired\n", encoding="utf-8")
    write_task(retired / "issues/37c-001-alpha.md", "37c-001")

    tasks = _ticket_tasks(RecordRead(tmp_path), SELECTOR, [])

    assert {task["task"]: task["applicability"] for task in tasks} == {
        "META-STRUCT-004": "historical",
        "37c-001": "historical",
    }


def test_typed_lifecycle_alone_controls_current_terminal_state(tmp_path):
    path = tmp_path / "plans/2026-10-02-current/issues/05-metadata.md"
    write_task(path, "META-STRUCT-005", lifecycle="in-progress", status="Resolved wording in a narrative")
    assert _ticket_tasks(RecordRead(tmp_path), SELECTOR, [])[0]["applicability"] == "current"

    write_task(path, "META-STRUCT-005", lifecycle="complete", status="Follow-up prose remains open")
    assert _ticket_tasks(RecordRead(tmp_path), SELECTOR, [])[0]["applicability"] == "historical"
