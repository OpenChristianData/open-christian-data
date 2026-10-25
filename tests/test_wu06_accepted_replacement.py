from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Event, Thread
import time

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    promote_accepted_master,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import (
    _files,
    install_accepted_work,
    read_accepted_work,
    recover_accepted_work,
)
from tests.test_tei_acceptance import (
    WORK_ID,
    _acceptance_path,
    _candidate,
    _decision,
    _fixture_root,
    _identity,
    _master_path,
    _prepare_evidence,
    _scope,
    _write_valid_acceptance,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep copied fixture paths short on Windows."""

    return tmp_path_factory.mktemp("w6")


@pytest.fixture
def installation(tmp_path: Path) -> tuple[Path, object]:
    stage = _fixture_root(tmp_path / "stage")
    acceptance, _record = _write_valid_acceptance(stage)
    promoted = promote_accepted_master(
        stage,
        acceptance_path=acceptance,
        destination=tmp_path / "promoted-v1",
    )
    live = tmp_path / "live"
    shutil.copytree(stage, live)
    _master_path(live).unlink()
    _acceptance_path(live).unlink()
    state_path = live / "library" / "works" / WORK_ID / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"] = [
        item for item in state["targets"] if item["target_type"] != "edition"
    ]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return live, promoted


def _promoted_revision(tmp_path: Path, revision_id: str = "pipe-004-fixture-v2"):
    stage = _fixture_root(tmp_path / "revision-stage")
    work_evidence = stage / "library" / "works" / WORK_ID / "acceptance"
    work_evidence.mkdir(parents=True, exist_ok=True)
    candidate = _candidate(stage, revision_id=revision_id)
    candidate = candidate.rename(work_evidence / "candidate.tei.xml")
    source_accounting, technical, review = _prepare_evidence(stage, candidate)
    source_accounting = source_accounting.rename(work_evidence / source_accounting.name)
    for name, evidence in list(technical.items()):
        if isinstance(evidence, dict) and isinstance(evidence.get("path"), Path):
            evidence["path"] = evidence["path"].rename(work_evidence / evidence["path"].name)
    review["report_path"] = review["report_path"].rename(
        work_evidence / review["report_path"].name
    )
    record = build_acceptance_record(
        stage,
        identity=_identity(),
        candidate_path=candidate,
        source_accounting_path=source_accounting,
        scope=_scope(),
        technical=technical,  # type: ignore[arg-type]
        review=review,
        representation_revision={
            "id": revision_id,
            "date": "2026-09-06",
            "note": "Bound fixture candidate for PIPE-004.",
        },
        decision=_decision(),
    )
    acceptance = _acceptance_path(stage)
    write_acceptance(acceptance, record)
    return promote_accepted_master(
        stage,
        acceptance_path=acceptance,
        destination=tmp_path / "promoted-v2",
    )


def _install_initial(live: Path, promoted) -> dict:
    return install_accepted_work(
        live,
        promoted.destination_root,
        work_id=WORK_ID,
    )


def test_expected_old_snapshot_rejects_stale_replacement(installation) -> None:
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library" / "works" / WORK_ID
    expected_old = _files(target)
    operations_before = set((live / ".tmp_audit").glob("accepted-install-*"))
    work_path = target / "work.json"
    work_path.write_bytes(work_path.read_bytes() + b"\nchanged")
    changed = _files(target)

    with pytest.raises(PipelineError, match="expected-old"):
        install_accepted_work(
            live,
            promoted.destination_root,
            work_id=WORK_ID,
            expected_old=expected_old,
            lock_acquire_timeout=0.0,
        )

    assert _files(target) == changed
    assert set((live / ".tmp_audit").glob("accepted-install-*")) == operations_before


def test_existing_replacement_guard_remains_without_expected_old(installation) -> None:
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library" / "works" / WORK_ID
    before = _files(target)

    with pytest.raises(PipelineError, match="explicit replacement reconciliation"):
        install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)

    assert _files(target) == before


def test_reviewed_generation_binds_publication_changes_and_preserves_backup(installation):
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library/works" / WORK_ID
    source = promoted.destination_root / "library/works" / WORK_ID
    before = _files(target)
    (source / "PUBLICATION_DISPOSITION.md").write_text("Reviewed disposition.\n", encoding="utf-8")
    after = _files(source)
    old_snapshot, new_snapshot = live / "before.json", live / "reviewed.json"
    old_snapshot.write_text(json.dumps(before), encoding="utf-8")
    new_snapshot.write_text(json.dumps(after), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(REPO_ROOT / "build/tools/install_accepted_work.py"),
        "--root", str(live), "--promoted", str(promoted.destination_root), "--work", WORK_ID,
        "--expected-old", str(old_snapshot), "--reviewed-new", str(new_snapshot)],
        check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)
    assert _files(target) == after
    assert _files(Path(result["backup"])) == before
    journal = json.loads((Path(result["operation"]) / "operation.json").read_bytes())
    assert journal["operation_kind"] == "reviewed-generation"


def test_reviewed_generation_admits_catalog_only_declarations(installation):
    live, promoted = installation
    target = live / "library/works" / WORK_ID
    source = promoted.destination_root / "library/works" / WORK_ID
    work_path = target / "work.json"
    work = json.loads(work_path.read_bytes())
    work["textual_forms"] = []
    work_path.write_text(json.dumps(work), encoding="utf-8")
    state_path = target / "state.json"
    state = json.loads(state_path.read_bytes())
    state["targets"] = []
    state_path.write_text(json.dumps(state), encoding="utf-8")
    before = _files(target)
    result = install_accepted_work(live, promoted.destination_root, work_id=WORK_ID,
        expected_old=before, reviewed_new=_files(source))
    assert result["status"] == "installed-and-validated"
    assert _files(Path(result["backup"])) == before


def test_reviewed_generation_archives_superseded_rights_without_losing_bytes(installation):
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library/works" / WORK_ID
    source = promoted.destination_root / "library/works" / WORK_ID
    relative = Path("forms/athanasius-on-the-incarnation-prose/editions/ccel-npnf204/rights/old-assessment.json")
    old = target / relative
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text('{"historical": true}\n', encoding="utf-8")
    archive = source / "publication/history/superseded/old-assessment.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(old, archive)
    before = _files(target)
    result = install_accepted_work(live, promoted.destination_root, work_id=WORK_ID,
        expected_old=before, reviewed_new=_files(source))
    assert _files(Path(result["backup"])) == before
    assert (target / archive.relative_to(source)).read_bytes() == (Path(result["backup"]) / relative).read_bytes()


@pytest.mark.parametrize("mutation", ["stale-stage", "removed-file", "archived-other-file", "changed-acquisition", "changed-state"])
def test_reviewed_generation_rejects_unreviewed_or_destructive_changes(installation, mutation):
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library/works" / WORK_ID
    source = promoted.destination_root / "library/works" / WORK_ID
    if mutation == "removed-file":
        (target / "prior-evidence.md").write_text("Preserve me", encoding="utf-8")
    if mutation == "archived-other-file":
        old = target / "PUBLICATION_DISPOSITION.md"
        old.write_text("Current authority", encoding="utf-8")
        archive = source / "publication/history/superseded" / old.name
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old, archive)
    before = _files(target)
    reviewed = _files(source)
    if mutation == "stale-stage":
        (source / "unreviewed.md").write_text("Not reviewed", encoding="utf-8")
    elif mutation == "changed-acquisition":
        acquisition = next(source.rglob("acquisitions/*.json"))
        acquisition.write_bytes(acquisition.read_bytes() + b"\n")
        reviewed = _files(source)
    elif mutation == "changed-state":
        path = source / "state.json"
        state = json.loads(path.read_bytes())
        state["targets"][0]["evidence"].append("state.json")
        path.write_text(json.dumps(state), encoding="utf-8")
        reviewed = _files(source)
    with pytest.raises(PipelineError):
        install_accepted_work(live, promoted.destination_root, work_id=WORK_ID,
            expected_old=before, reviewed_new=reviewed)
    assert _files(target) == before


def test_exact_snapshot_supports_replacement_in_an_ordinary_checkout(installation) -> None:
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library" / "works" / WORK_ID
    expected_old = _files(target)
    (live / ".git").mkdir()

    snapshot = live / "expected-work-files.json"
    snapshot.write_text(json.dumps(expected_old), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(REPO_ROOT / "build/tools/install_accepted_work.py"),
        "--root", str(live), "--promoted", str(promoted.destination_root), "--work", WORK_ID,
        "--expected-old", str(snapshot)], check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)
    assert result["status"] == "replaced-and-validated"
    assert _files(Path(result["backup"])) == expected_old


def test_ordinary_checkout_still_rejects_stale_snapshot(installation) -> None:
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library" / "works" / WORK_ID
    expected_old = _files(target)
    (live / ".git").mkdir()
    (target / "peer-evidence.md").write_text("Concurrent evidence", encoding="utf-8")
    actual = _files(target)

    with pytest.raises(PipelineError, match="expected-old"):
        install_accepted_work(
            live,
            promoted.destination_root,
            work_id=WORK_ID,
            expected_old=expected_old,
        )

    assert _files(target) == actual


def test_replacement_preserves_exact_previous_generation(installation, tmp_path: Path) -> None:
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library" / "works" / WORK_ID
    expected_old = _files(target)
    promoted_v2 = _promoted_revision(tmp_path)
    expected_new = _files(promoted_v2.destination_root / "library" / "works" / WORK_ID)

    result = install_accepted_work(
        live,
        promoted_v2.destination_root,
        work_id=WORK_ID,
        expected_old=expected_old,
    )

    assert result["status"] == "replaced-and-validated"
    assert result["previous_files"] == expected_old
    assert result["installed_files"] == expected_new
    assert _files(target) == expected_new
    assert _files(Path(result["backup"])) == expected_old
    acceptance = target / "forms" / "athanasius-on-the-incarnation-prose" / "editions" / "ccel-npnf204" / "acceptance.json"
    assert validate_acceptance(acceptance, root=live)["identity"]["work_id"] == WORK_ID


def test_replacement_excludes_a_second_process_while_lock_is_held(installation) -> None:
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library" / "works" / WORK_ID
    expected_old = _files(target)
    script = """
import json
import sys
from pathlib import Path
from ocd_kernel.tei.install_accepted import install_accepted_work

try:
    install_accepted_work(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        work_id=sys.argv[3],
        expected_old=json.loads(sys.argv[4]),
        lock_acquire_timeout=0.0,
    )
except Exception as exc:
    print(type(exc).__name__ + ":" + str(exc))
    raise SystemExit(3)
raise SystemExit(0)
"""

    with acquire_jsonl_lock(target, acquire_timeout=0.0):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(live),
                str(promoted.destination_root),
                WORK_ID,
                json.dumps(expected_old, sort_keys=True),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    assert completed.returncode == 3
    assert completed.stdout.startswith("LockAcquireTimeout:")
    assert _files(target) == expected_old


def test_reader_retries_the_unavailable_swap_window(installation, tmp_path: Path) -> None:
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library" / "works" / WORK_ID
    expected_old = _files(target)
    promoted_v2 = _promoted_revision(tmp_path)
    expected_new = _files(promoted_v2.destination_root / "library" / "works" / WORK_ID)
    started = Event()
    reader_result: dict[str, object] = {}

    def reader() -> None:
        started.set()
        try:
            reader_result["path"] = read_accepted_work(
                live,
                work_id=WORK_ID,
                attempts=200,
                retry_delay=0.005,
            )
            reader_result["files"] = _files(reader_result["path"])
        except Exception as exc:  # pragma: no cover - assertion reports the error
            reader_result["error"] = exc

    reader_thread = Thread(target=reader)

    def checkpoint(name: str) -> None:
        if name == "after-previous-moved":
            reader_thread.start()
            assert started.wait(timeout=1.0)
            time.sleep(0.05)

    install_accepted_work(
        live,
        promoted_v2.destination_root,
        work_id=WORK_ID,
        expected_old=expected_old,
        fail_at=checkpoint,
    )
    reader_thread.join(timeout=3.0)

    assert not reader_thread.is_alive()
    assert "error" not in reader_result
    assert reader_result["path"] == target
    assert reader_result["files"] in (expected_old, expected_new)
    assert _files(target) == expected_new


class _AbruptInterruption(BaseException):
    pass


@pytest.mark.parametrize(
    "checkpoint_name",
    [
        "after-incoming",
        "after-previous-moved",
        "after-new-live",
        "after-validated",
    ],
)
def test_recovery_returns_to_a_complete_generation(
    installation,
    tmp_path: Path,
    checkpoint_name: str,
) -> None:
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library" / "works" / WORK_ID
    expected_old = _files(target)
    promoted_v2 = _promoted_revision(tmp_path)
    expected_new = _files(promoted_v2.destination_root / "library" / "works" / WORK_ID)
    unrelated = live / "unrelated-dirty-marker.txt"
    unrelated.write_bytes(b"preserve this unrelated dirty state\n")

    def interrupt(name: str) -> None:
        if name == checkpoint_name:
            raise _AbruptInterruption(checkpoint_name)

    with pytest.raises(_AbruptInterruption):
        install_accepted_work(
            live,
            promoted_v2.destination_root,
            work_id=WORK_ID,
            expected_old=expected_old,
            fail_at=interrupt,
        )

    operations = []
    for journal_path in sorted((live / ".tmp_audit").glob("accepted-install-*/operation.json")):
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("phase") not in {"complete", "recovered-old", "recovered-new", "rolled-back"}:
            operations.append(journal_path)
    assert len(operations) == 1
    operation = operations[0].parent
    recovery = recover_accepted_work(live, work_id=WORK_ID, operation=operation)
    assert recovery["status"] in {"recovered-old", "recovered-new"}

    live_files = _files(target)
    assert live_files in (expected_old, expected_new)
    acceptance = target / "forms" / "athanasius-on-the-incarnation-prose" / "editions" / "ccel-npnf204" / "acceptance.json"
    validate_acceptance(acceptance, root=live)
    again = recover_accepted_work(live, work_id=WORK_ID, operation=operation)
    assert again["status"] == recovery["status"]
    assert _files(target) == live_files
    assert unrelated.read_bytes() == b"preserve this unrelated dirty state\n"
    assert (operation / "operation.json").is_file()


@pytest.mark.parametrize(
    "checkpoint_name",
    ["after-incoming", "after-previous-moved", "after-new-live", "after-validated"],
)
def test_fresh_process_termination_leaves_recoverable_journal(
    installation, tmp_path: Path, checkpoint_name: str
) -> None:
    live, promoted = installation
    _install_initial(live, promoted)
    target = live / "library" / "works" / WORK_ID
    expected_old = _files(target)
    promoted_v2 = _promoted_revision(tmp_path)
    expected_new = _files(promoted_v2.destination_root / "library" / "works" / WORK_ID)
    unrelated = live / "unrelated-dirty-marker.txt"
    unrelated.write_bytes(b"preserve this unrelated dirty state\n")
    script = """
import os
import sys
from pathlib import Path
from ocd_kernel.tei.install_accepted import install_accepted_work

def checkpoint(name):
    if name == sys.argv[5]:
        os._exit(17)

install_accepted_work(
    Path(sys.argv[1]),
    Path(sys.argv[2]),
    work_id=sys.argv[3],
    expected_old=__import__("json").loads(sys.argv[4]),
    fail_at=checkpoint,
)
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(live),
            str(promoted_v2.destination_root),
            WORK_ID,
            json.dumps(expected_old, sort_keys=True),
            checkpoint_name,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 17
    operations = []
    for journal_path in sorted((live / ".tmp_audit").glob("accepted-install-*/operation.json")):
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("phase") == checkpoint_name:
            operations.append(journal_path.parent)
    assert len(operations) == 1
    recovered = recover_accepted_work(live, work_id=WORK_ID, operation=operations[0])
    assert recovered["status"] in {"recovered-old", "recovered-new"}
    assert _files(target) == expected_old or _files(target) == expected_new
    assert unrelated.read_bytes() == b"preserve this unrelated dirty state\n"
