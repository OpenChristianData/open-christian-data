from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.acceptance import (
    build_acceptance_record,
    make_file_binding,
    promote_accepted_master,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import (
    _files,
    _replacement_changes_are_scoped,
    add_accepted_edition,
    install_accepted_work,
    recover_accepted_work,
)
from tests.test_tei_acceptance import (
    ACQUISITION_ID,
    EDITION_ID,
    FORM_ID,
    WORK_ID,
    _acceptance_path,
    _fixture_root,
    _master_path,
    _write_valid_acceptance,
)


SECOND_EDITION_ID = "alt-edition"
SECOND_ACQUISITION_ID = "alt-acquisition"
SECOND_REVISION_ID = "pipe-004-fixture-v2"


class _AbruptInterruption(BaseException):
    pass


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep copied fixture paths within the Windows path limit."""

    return tmp_path_factory.mktemp("w10")


@pytest.fixture
def installation(tmp_path: Path) -> tuple[Path, object]:
    stage = _fixture_root(tmp_path / "stage")
    acceptance, _record = _write_valid_acceptance(stage, historical=True)
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


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _prepare_second_edition_input(
    live: Path, tmp_path: Path
) -> tuple[Path, Path, list[Path]]:
    """Create a complete promoted future generation with one added edition."""

    root = tmp_path / "second-edition-input"
    shutil.copytree(live, root, ignore=shutil.ignore_patterns(".tmp_audit"))
    work_root = root / "library" / "works" / WORK_ID
    work_path = work_root / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    form = next(
        item
        for item in work["textual_forms"]
        if item["textual_form_id"] == "athanasius-on-the-incarnation-prose"
    )
    form["editions"].append(
        {
            "edition_id": SECOND_EDITION_ID,
            "title": "On the Incarnation of the Word — revised fixture rendering",
            "language": "en",
            "category": "prose",
            "acquisition_ids": [SECOND_ACQUISITION_ID],
        }
    )
    _write_json(work_path, work)

    first_acquisition = (
        work_root
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
        / "acquisitions"
        / f"{ACQUISITION_ID}.json"
    )
    second_edition_root = (
        work_root / "forms" / FORM_ID / "editions" / SECOND_EDITION_ID
    )
    second_acquisition = (
        second_edition_root
        / "acquisitions"
        / f"{SECOND_ACQUISITION_ID}.json"
    )
    acquisition = json.loads(first_acquisition.read_text(encoding="utf-8"))
    acquisition["edition_id"] = SECOND_EDITION_ID
    acquisition["acquisition_id"] = SECOND_ACQUISITION_ID
    _write_json(second_acquisition, acquisition)

    state_path = work_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"].append(
        {
            "target_id": SECOND_EDITION_ID,
            "target_type": "edition",
            "stage": "review",
            "updated_at": "2026-09-17T00:00:00Z",
            "evidence": [
                f"forms/{FORM_ID}/editions/{SECOND_EDITION_ID}/acquisitions/"
                f"{SECOND_ACQUISITION_ID}.json"
            ],
        }
    )
    _write_json(state_path, state)

    acceptance_root = root / "acceptance"
    first_candidate = acceptance_root / "candidate.tei.xml"
    second_candidate = acceptance_root / "candidate-second.tei.xml"
    candidate = first_candidate.read_text(encoding="utf-8")
    candidate = candidate.replace(ACQUISITION_ID, "__SECOND_ACQUISITION__")
    candidate = candidate.replace(EDITION_ID, SECOND_EDITION_ID)
    candidate = candidate.replace("__SECOND_ACQUISITION__", SECOND_ACQUISITION_ID)
    candidate = candidate.replace("pipe-004-fixture-v1", SECOND_REVISION_ID)
    second_candidate.write_text(candidate, encoding="utf-8", newline="\n")

    first_acceptance_path = (
        work_root
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
        / "acceptance.json"
    )
    first_record = json.loads(first_acceptance_path.read_text(encoding="utf-8"))
    identity = {
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": SECOND_EDITION_ID,
        "acquisition_id": SECOND_ACQUISITION_ID,
    }

    source_accounting = acceptance_root / "source-accounting-second.json"
    source_document = json.loads(
        (acceptance_root / "source-accounting.json").read_text(encoding="utf-8")
    )
    source_document["identity"] = identity
    _write_json(source_accounting, source_document)

    candidate_binding = make_file_binding(root, second_candidate)
    technical: dict[str, object] = {
        "producer": copy.deepcopy(first_record["technical"]["producer"]),
        "checker": copy.deepcopy(first_record["technical"]["checker"]),
        "shared_assumptions": copy.deepcopy(
            first_record["technical"]["shared_assumptions"]
        ),
        "independent_corroboration": first_record["technical"][
            "independent_corroboration"
        ],
    }
    for name in (
        "validation",
        "accounting",
        "fidelity",
        "reproducibility",
        "schema",
        "closure",
    ):
        original_path = acceptance_root / f"{name}.json"
        document = json.loads(original_path.read_text(encoding="utf-8"))
        document["identity"] = identity
        document["candidate"] = candidate_binding
        output_path = acceptance_root / f"{name}-second.json"
        _write_json(output_path, document)
        original = first_record["technical"][name]
        technical[name] = {
            "path": output_path,
            "status": original["status"],
            "command": original["command"],
            "exit_code": original["exit_code"],
        }

    review_path = acceptance_root / "review-second.json"
    review_document = json.loads(
        (acceptance_root / "review.json").read_text(encoding="utf-8")
    )
    review_document["identity"] = identity
    review_document["candidate"] = candidate_binding
    _write_json(review_path, review_document)
    original_review = first_record["review"]
    review = {
        "report_path": review_path,
        "reviewer": original_review["reviewer"],
        "reviewed_at": original_review["reviewed_at"],
        "coverage": copy.deepcopy(original_review["coverage"]),
        "source_quality_uncertainty": copy.deepcopy(
            original_review["source_quality_uncertainty"]
        ),
        "discrepancies": copy.deepcopy(original_review["discrepancies"]),
        "unreviewed_residuals": copy.deepcopy(original_review["unreviewed_residuals"]),
    }

    second_acceptance = second_edition_root / "acceptance.json"
    record = build_acceptance_record(
        root,
        identity=identity,
        candidate_path=second_candidate,
        source_accounting_path=source_accounting,
        scope=copy.deepcopy(first_record["scope"]),
        technical=technical,  # type: ignore[arg-type]
        review=review,
        representation_revision={
            "id": SECOND_REVISION_ID,
            "date": "2026-09-06",
            "note": "Bound fixture candidate for PIPE-004.",
        },
        decision=copy.deepcopy(first_record["decision"]),
        promotion_status="pending",
    )
    write_acceptance(second_acceptance, record)
    external_files = [
        second_candidate,
        source_accounting,
        *(acceptance_root / f"{name}-second.json" for name in (
            "validation",
            "accounting",
            "fidelity",
            "reproducibility",
            "schema",
            "closure",
        )),
        review_path,
    ]
    return root, second_acceptance, external_files


def _promoted_second_edition(
    live: Path, tmp_path: Path
) -> tuple[Path, list[Path]]:
    input_root, acceptance_path, external_files = _prepare_second_edition_input(
        live, tmp_path
    )
    promoted = promote_accepted_master(
        input_root,
        acceptance_path=acceptance_path,
        destination=tmp_path / "promoted-v2",
    )
    return promoted.destination_root, external_files


def _copy_external_files_to_live(live: Path, external_files: list[Path]) -> None:
    for path in external_files:
        shutil.copy2(path, live / "acceptance" / path.name)


def test_second_edition_cannot_replace_first_or_drop_historical_bytes(
    installation,
) -> None:
    live, promoted = installation
    install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    target = live / "library" / "works" / WORK_ID
    before = _files(target)
    historical_master = promoted.master_path
    historical_bytes = historical_master.read_bytes()

    with pytest.raises(PipelineError, match="explicit replacement reconciliation"):
        install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)

    assert _files(target) == before
    assert historical_master.read_bytes() == historical_bytes


def test_edition_collision_is_rejected_by_existing_accepted_set_guard() -> None:
    before = {
        "forms/english/editions/first/acceptance.json": "a" * 64,
        "forms/english/editions/first/master.tei.xml": "b" * 64,
        "state.json": "c" * 64,
    }
    after = dict(before)
    after["forms/english/editions/second/acceptance.json"] = "d" * 64
    after["forms/english/editions/second/master.tei.xml"] = "e" * 64

    with pytest.raises(PipelineError, match="replacement changes the accepted-edition set"):
        _replacement_changes_are_scoped(before, after)


def test_concatenated_second_edition_master_is_rejected_and_first_is_untouched(
    installation,
) -> None:
    live, promoted = installation
    target = live / "library" / "works" / WORK_ID
    before = _files(target)
    promoted_master = promoted.master_path
    promoted_master.write_bytes(promoted_master.read_bytes() + promoted_master.read_bytes())

    with pytest.raises(PipelineError, match="promotion.master byte mismatch"):
        install_accepted_work(
            live,
            promoted.destination_root,
            work_id=WORK_ID,
            expected_old=before,
        )

    assert _files(target) == before


def test_add_accepted_edition_preserves_first_edition_and_installs_second(
    installation, tmp_path: Path
) -> None:
    live, promoted = installation
    install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    target = live / "library" / "works" / WORK_ID
    first_master = _master_path(live)
    first_acceptance = _acceptance_path(live)
    before = _files(target)
    (live / ".git").mkdir()
    first_master_bytes = first_master.read_bytes()
    first_acceptance_bytes = first_acceptance.read_bytes()

    promoted_second, external_files = _promoted_second_edition(live, tmp_path)
    _copy_external_files_to_live(live, external_files)
    snapshot = live / "expected-work-files.json"
    snapshot.write_text(json.dumps(before), encoding="utf-8")
    completed = subprocess.run([sys.executable,
        str(Path(__file__).resolve().parents[1] / "build/tools/install_accepted_work.py"),
        "--root", str(live), "--promoted", str(promoted_second), "--work", WORK_ID,
        "--expected-old", str(snapshot), "--add-edition", FORM_ID, SECOND_EDITION_ID],
        check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)

    assert result["status"] == "added-and-validated"
    assert result["accepted_editions"] == 2
    assert _files(target)[_master_path(live).relative_to(target).as_posix()] == before[
        _master_path(live).relative_to(target).as_posix()
    ]
    assert first_master.read_bytes() == first_master_bytes
    assert first_acceptance.read_bytes() == first_acceptance_bytes
    assert (
        target
        / "forms"
        / FORM_ID
        / "editions"
        / SECOND_EDITION_ID
        / "master.tei.xml"
    ).is_file()
    assert (
        Path(result["backup"])
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
        / "master.tei.xml"
    ).read_bytes() == first_master_bytes
    work = json.loads((target / "work.json").read_text(encoding="utf-8"))
    form = next(item for item in work["textual_forms"] if item["textual_form_id"] == FORM_ID)
    assert [item["edition_id"] for item in form["editions"]] == [
        EDITION_ID,
        SECOND_EDITION_ID,
    ]


def test_add_accepted_edition_rejects_stale_snapshot_without_mutating_live(
    installation, tmp_path: Path
) -> None:
    live, promoted = installation
    install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    target = live / "library" / "works" / WORK_ID
    before = _files(target)
    work_path = target / "work.json"
    work_path.write_text(work_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    promoted_second, _external_files = _promoted_second_edition(live, tmp_path)
    with pytest.raises(PipelineError, match="expected-old snapshot"):
        add_accepted_edition(
            live,
            promoted_second,
            work_id=WORK_ID,
            textual_form_id=FORM_ID,
            edition_id=SECOND_EDITION_ID,
            expected_old=before,
        )

    assert not (
        target
        / "forms"
        / FORM_ID
        / "editions"
        / SECOND_EDITION_ID
    ).exists()


def test_add_accepted_edition_rejects_existing_identity_and_unrelated_files(
    installation, tmp_path: Path
) -> None:
    live, promoted = installation
    install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    target = live / "library" / "works" / WORK_ID
    before = _files(target)
    promoted_second, external_files = _promoted_second_edition(live, tmp_path)
    _copy_external_files_to_live(live, external_files)

    with pytest.raises(PipelineError, match="collides with existing edition"):
        add_accepted_edition(
            live,
            promoted_second,
            work_id=WORK_ID,
            textual_form_id=FORM_ID,
            edition_id=EDITION_ID,
            expected_old=before,
        )

    unexpected = (
        promoted_second
        / "library"
        / "works"
        / WORK_ID
        / "forms"
        / FORM_ID
        / "editions"
        / SECOND_EDITION_ID
        / "unexpected.txt"
    )
    unexpected.write_text("not an edition sidecar\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="outside the requested edition"):
        add_accepted_edition(
            live,
            promoted_second,
            work_id=WORK_ID,
            textual_form_id=FORM_ID,
            edition_id=SECOND_EDITION_ID,
            expected_old=before,
        )
    assert _files(target) == before


def test_add_accepted_edition_rejects_concatenated_new_master(
    installation, tmp_path: Path
) -> None:
    live, promoted = installation
    install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    target = live / "library" / "works" / WORK_ID
    before = _files(target)
    promoted_second, _external_files = _promoted_second_edition(live, tmp_path)
    second_master = (
        promoted_second
        / "library"
        / "works"
        / WORK_ID
        / "forms"
        / FORM_ID
        / "editions"
        / SECOND_EDITION_ID
        / "master.tei.xml"
    )
    original = second_master.read_bytes()
    second_master.write_bytes(original + original)

    with pytest.raises(PipelineError, match="promotion.master byte mismatch"):
        add_accepted_edition(
            live,
            promoted_second,
            work_id=WORK_ID,
            textual_form_id=FORM_ID,
            edition_id=SECOND_EDITION_ID,
            expected_old=before,
        )
    assert _files(target) == before


def test_add_accepted_edition_recovers_after_interruption(
    installation, tmp_path: Path
) -> None:
    live, promoted = installation
    install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    target = live / "library" / "works" / WORK_ID
    before = _files(target)
    promoted_second, external_files = _promoted_second_edition(live, tmp_path)
    _copy_external_files_to_live(live, external_files)

    def interrupt(phase: str) -> None:
        if phase == "after-new-live":
            raise _AbruptInterruption()

    with pytest.raises(_AbruptInterruption):
        add_accepted_edition(
            live,
            promoted_second,
            work_id=WORK_ID,
            textual_form_id=FORM_ID,
            edition_id=SECOND_EDITION_ID,
            expected_old=before,
            fail_at=interrupt,
        )

    operations = [
        path
        for path in (live / ".tmp_audit").glob("accepted-install-*/operation.json")
        if json.loads(path.read_text(encoding="utf-8")).get("operation_kind")
        == "addition"
    ]
    assert operations
    recovered = recover_accepted_work(
        live,
        work_id=WORK_ID,
        operation=operations[-1].parent,
    )
    assert recovered["status"] == "recovered-new"
    assert len(list(target.rglob("acceptance.json"))) == 2
    assert _files(Path(recovered["operation"]) / "previous") == before
