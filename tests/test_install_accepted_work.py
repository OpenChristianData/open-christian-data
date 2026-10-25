import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import discover_library
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, promote_accepted_master, validate_acceptance
from ocd_kernel.tei.install_accepted import _acceptance_paths, _files, _io_path, _load_recovery_operation, _validate_promoted_tree, install_accepted_work
from tests.test_tei_acceptance import _fixture_root, _write_valid_acceptance, _master_path, WORK_ID


@pytest.fixture
def installation(tmp_path_factory):
    temp = tmp_path_factory.mktemp("iw")
    stage = _fixture_root(temp)
    acceptance, _ = _write_valid_acceptance(stage)
    promoted = promote_accepted_master(stage, acceptance_path=acceptance, destination=temp / "p")
    live = temp / "l"
    shutil.copytree(stage, live)
    _master_path(live).unlink()
    (live / acceptance.relative_to(stage)).unlink()
    state = live / "library/works" / WORK_ID / "state.json"
    record = json.loads(state.read_text(encoding="utf-8"))
    record["targets"] = [item for item in record["targets"] if item["target_type"] != "edition"]
    state.write_text(json.dumps(record), encoding="utf-8")
    return live, promoted


@pytest.fixture
def review_installation(tmp_path_factory):
    temp = tmp_path_factory.mktemp("ri")
    stage = _fixture_root(temp)
    state_path = stage / "library/works" / WORK_ID / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"][0]["stage"] = "review"
    state["targets"][0]["reason"] = "No accepted master is installed."
    state["targets"][0]["evidence"] = ["work.json"]
    acquisition = {
        "target_id": "ccel-npnf204-retained-xml",
        "target_type": "acquisition",
        "stage": "acquired",
        "evidence": [
            "forms/athanasius-on-the-incarnation-prose/editions/ccel-npnf204/"
            "acquisitions/ccel-npnf204-retained-xml.json"
        ],
        "updated_at": "2026-09-06T08:57:28.078565Z",
    }
    state["targets"].append(acquisition)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    acceptance, _ = _write_valid_acceptance(stage)
    promoted = promote_accepted_master(stage, acceptance_path=acceptance, destination=temp / "p")
    live = temp / "l"
    shutil.copytree(stage, live)
    _master_path(live).unlink()
    (live / acceptance.relative_to(stage)).unlink()
    return live, promoted


@pytest.fixture
def acquired_installation(review_installation):
    live, promoted = review_installation
    state_path = live / "library/works" / WORK_ID / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"][0]["stage"] = "acquired"
    state["targets"][0].pop("reason", None)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return live, promoted


def test_install_advances_matching_acquired_edition_only(acquired_installation):
    live, promoted = acquired_installation
    state_path = live / "library/works" / WORK_ID / "state.json"
    before = json.loads(state_path.read_text(encoding="utf-8"))

    result = install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)

    after = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["status"] == "installed-and-validated"
    assert after == json.loads(promoted.state_path.read_text(encoding="utf-8"))
    assert after["targets"][0]["stage"] == "accepted"
    assert after["targets"][0]["reason"] == PROMOTED_MASTER_REASON
    assert after["targets"][1] == before["targets"][1]


def test_install_rejects_extra_evidence_on_acquired_edition(acquired_installation):
    live, promoted = acquired_installation
    state_path = promoted.state_path
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"][0]["evidence"].append("state.json")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    validate_acceptance(promoted.acceptance_path, root=promoted.destination_root)
    live_state = live / "library/works" / WORK_ID / "state.json"
    before = live_state.read_bytes()

    with pytest.raises(PipelineError, match="existing state target"):
        install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)

    assert live_state.read_bytes() == before
    assert not _master_path(live).exists()


def test_install_advances_matching_review_edition_only(review_installation):
    live, promoted = review_installation
    state_path = live / "library/works" / WORK_ID / "state.json"
    before = json.loads(state_path.read_text(encoding="utf-8"))
    promoted_state = json.loads(promoted.state_path.read_text(encoding="utf-8"))

    result = install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)

    assert result["status"] == "installed-and-validated"
    operation_name = Path(result["operation"]).name
    assert operation_name.startswith("accepted-install-")
    strong_acquisition = (
        PureWindowsPath("C:/Users/Reader/Workspace/Open Christian Data")
        / ".tmp_audit" / operation_name / "incoming"
        / "forms/strong-systematic-theology-vol-3-english/editions/project-gutenberg-45283"
        / "acquisitions/strong-systematic-theology-vol-3-pg45283-retained.json"
    )
    assert len(strong_acquisition.as_posix()) < 260
    after = json.loads(state_path.read_text(encoding="utf-8"))
    assert after == promoted_state
    assert after["work_id"] == before["work_id"]
    assert after["targets"][0]["stage"] == "accepted"
    assert before["targets"][0]["reason"] == "No accepted master is installed."
    assert after["targets"][0]["reason"] == PROMOTED_MASTER_REASON
    assert after["targets"][0]["target_id"] == before["targets"][0]["target_id"]
    assert after["targets"][0]["target_type"] == before["targets"][0]["target_type"]
    assert after["targets"][0]["evidence"][:1] == before["targets"][0]["evidence"]
    assert after["targets"][1] == before["targets"][1]
    assert json.loads((Path(result["backup"]) / "state.json").read_text(encoding="utf-8")) == before


def test_install_rejects_changes_to_unrelated_acquisition_target(review_installation):
    live, promoted = review_installation
    state_path = promoted.state_path
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"][1]["stage"] = "planned"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    old_state_path = live / "library/works" / WORK_ID / "state.json"
    before = old_state_path.read_bytes()

    with pytest.raises(PipelineError, match="existing state target"):
        install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)

    assert old_state_path.read_bytes() == before
    assert not _master_path(live).exists()


def test_install_rejects_extra_promoted_edition_evidence(review_installation):
    live, promoted = review_installation
    state_path = promoted.state_path
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"][0]["evidence"].append("state.json")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    validate_acceptance(promoted.acceptance_path, root=promoted.destination_root)
    old_state_path = live / "library/works" / WORK_ID / "state.json"
    before = old_state_path.read_bytes()

    with pytest.raises(PipelineError, match="existing state target"):
        install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)

    assert old_state_path.read_bytes() == before
    assert not _master_path(live).exists()


def test_install_rejects_arbitrary_promoted_reason(review_installation):
    live, promoted = review_installation
    state_path = promoted.state_path
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"][0]["reason"] = "Rights and publication are cleared."
    state_path.write_text(json.dumps(state), encoding="utf-8")
    validate_acceptance(promoted.acceptance_path, root=promoted.destination_root)
    old_state_path = live / "library/works" / WORK_ID / "state.json"
    before = old_state_path.read_bytes()

    with pytest.raises(PipelineError, match="existing state target"):
        install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)

    assert old_state_path.read_bytes() == before
    assert not _master_path(live).exists()


def test_install_checks_only_target_work_when_sibling_acquisition_is_invalid(
    review_installation,
):
    live, promoted = review_installation
    source_work_root = live / "library/works" / WORK_ID
    unrelated_work_id = "unrelated-invalid-acquisition"
    work = json.loads((source_work_root / "work.json").read_text(encoding="utf-8"))
    work["work_id"] = unrelated_work_id
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    edition.pop("acquisition_ids", None)
    unrelated_root = live / "library/works" / unrelated_work_id
    acquisition_path = (
        unrelated_root / "forms" / form["textual_form_id"] / "editions"
        / edition["edition_id"] / "acquisitions" / "unrelated-invalid-acquisition.json"
    )
    acquisition_path.parent.mkdir(parents=True)
    (unrelated_root / "work.json").write_text(json.dumps(work), encoding="utf-8")
    acquisition = json.loads(
        next(source_work_root.glob("forms/*/editions/*/acquisitions/*.json"))
        .read_text(encoding="utf-8")
    )
    acquisition["acquisition_id"] = "unrelated-invalid-acquisition"
    acquisition["source_path"] = "raw/unrelated-package.zip"
    acquisition_path.write_text(json.dumps(acquisition), encoding="utf-8")

    with pytest.raises(PipelineError, match="source_path cannot identify a ZIP package"):
        discover_library(live)

    result = install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)

    assert result["status"] == "installed-and-validated"
    assert _master_path(live).is_file()


def test_install_cli_installs_promoted_work(installation):
    live, promoted = installation
    script = Path(__file__).resolve().parents[1] / "build/tools/install_accepted_work.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--root", str(live),
         "--promoted", str(promoted.destination_root), "--work", WORK_ID],
        cwd=live,
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result["status"] == "installed-and-validated"
    assert result["work_id"] == WORK_ID
    assert result["accepted_editions"] == 1
    assert _master_path(live).is_file()
    path = live / promoted.acceptance_path.relative_to(promoted.destination_root)
    assert validate_acceptance(path, root=live)["promotion"]["status"] == "promoted"
    assert (Path(result["backup"]) / "work.json").is_file()


def test_install_cli_reports_invalid_work_id(installation):
    live, promoted = installation
    script = Path(__file__).resolve().parents[1] / "build/tools/install_accepted_work.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--root", str(live),
         "--promoted", str(promoted.destination_root), "--work", "../invalid"],
        cwd=live,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr.startswith("Installation failed: ")
    assert "work_id" in completed.stderr
    assert "Traceback" not in completed.stderr
    assert not _master_path(live).exists()


def test_install_validates_and_keeps_previous_tree(installation):
    live, promoted = installation
    result = install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    assert result["status"] == "installed-and-validated"
    path = live / promoted.acceptance_path.relative_to(promoted.destination_root)
    assert validate_acceptance(path, root=live)["promotion"]["status"] == "promoted"
    from pathlib import Path
    assert (Path(result["backup"]) / "work.json").is_file()


def test_install_rejects_changed_existing_authority(installation):
    live, promoted = installation
    path = live / "library/works" / WORK_ID / "work.json"
    original = path.read_bytes()
    path.write_bytes(original + b"\n")
    with pytest.raises(PipelineError, match="existing work authority"):
        install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    assert path.read_bytes() == original + b"\n"


def test_live_validation_failure_restores_original(installation, monkeypatch):
    live, promoted = installation
    import ocd_kernel.tei.install_accepted as module
    original = module._validate_acceptance_for_work
    state = live / "library/works" / WORK_ID / "state.json"
    before = state.read_bytes()
    def reject_live(path, *, root, work_id):
        if root == live:
            raise PipelineError("live authority mismatch")
        return original(path, root=root, work_id=work_id)
    monkeypatch.setattr(module, "_validate_acceptance_for_work", reject_live)
    with pytest.raises(PipelineError, match="live authority mismatch"):
        install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    assert state.read_bytes() == before
    assert not _master_path(live).exists()


def test_install_new_work_without_existing_identity(installation):
    live, promoted = installation
    work = live / 'library/works' / WORK_ID
    work.rename(live / 'prior-fixture-work')
    result = install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    assert result['backup'] is None
    assert result['previous_files'] == {}
    assert _master_path(live).exists()


def test_new_work_failure_leaves_no_live_work(installation, monkeypatch):
    live, promoted = installation
    work = live / 'library/works' / WORK_ID
    work.rename(live / 'prior-fixture-work')
    import ocd_kernel.tei.install_accepted as module
    original = module._validate_acceptance_for_work
    def reject_live(path, *, root, work_id):
        if root == live:
            raise PipelineError('live mismatch')
        return original(path, root=root, work_id=work_id)
    monkeypatch.setattr(module, '_validate_acceptance_for_work', reject_live)
    with pytest.raises(PipelineError, match='live mismatch'):
        install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    assert not work.exists()


def test_missing_original_language_evidence_rolls_back_install(installation):
    from build.lib.source_metadata import MetadataError
    live, promoted = installation
    for root in (live, promoted.destination_root):
        path = root / 'library/works' / WORK_ID / 'work.json'
        work = json.loads(path.read_text(encoding='utf-8'))
        work['original_language'] = {'value':'grc','source_metadata_subject':{'kind':'catalog','id':'missing-evidence'}}
        path.write_text(json.dumps(work), encoding='utf-8')
    state = live / 'library/works' / WORK_ID / 'state.json'
    before = state.read_bytes()
    with pytest.raises(MetadataError, match='index is missing'):
        install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    assert state.read_bytes() == before
    assert not _master_path(live).exists()


def test_install_with_adopted_original_language_evidence(installation):
    import hashlib
    from build.lib import source_metadata
    from tests.test_source_metadata_semantics import _fixture
    live, promoted = installation
    descriptor = {'kind':'original_language','predicate':'original_language','role':'original_composition','scope':'work'}
    _, decision, claim, worklist_path, decisions_path = _fixture(live, descriptor=descriptor, packet_value='grc')
    relative = f'library/works/{WORK_ID}/work.json'
    work = json.loads((live / relative).read_text(encoding='utf-8'))
    work['original_language'] = {'value':'grc','source_metadata_subject':{'kind':'catalog','id':'synthetic-work'}}
    content = source_metadata.canonical_bytes(work)
    for root in (live, promoted.destination_root):
        (root / relative).write_bytes(content)
    claim['adoption'] = {'classification':'adopted','destination':'v2','target':{'path':relative,'selector':'/original_language/value','expected_value':'grc','value_check':True,'current_raw_sha256':hashlib.sha256(content).hexdigest()}}
    decisions_path.write_bytes(source_metadata.canonical_bytes(decision))
    source_metadata.write_outputs(live, worklist_path=worklist_path, decisions_path=decisions_path)
    evidence_before = (live / 'evidence.json').read_bytes()
    index_before = (live / 'metadata/source-evidence/index.json').read_bytes()
    result = install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    assert result['status'] == 'installed-and-validated'
    assert source_metadata.lookup_work_original_language(live, live / relative)['evidence']['value'] == 'grc'
    assert (live / 'evidence.json').read_bytes() == evidence_before
    assert (live / 'metadata/source-evidence/index.json').read_bytes() == index_before


def test_install_with_adopted_work_kind_evidence(installation):
    import hashlib
    from build.lib import source_metadata
    from tests.test_source_metadata_semantics import _fixture
    live, promoted = installation
    descriptor = {'kind':'work_kind','predicate':'work_kind','role':'work_classification','scope':'work'}
    _, decision, claim, worklist_path, decisions_path = _fixture(live, descriptor=descriptor, packet_value='treatise')
    relative = f'library/works/{WORK_ID}/work.json'
    work = json.loads((live / relative).read_text(encoding='utf-8'))
    work['work_kind'] = {'value':'treatise','source_metadata_subject':{'kind':'catalog','id':'synthetic-work'}}
    content = source_metadata.canonical_bytes(work)
    for root in (live, promoted.destination_root):
        (root / relative).write_bytes(content)
    claim['adoption'] = {'classification':'adopted','destination':'v2','target':{'path':relative,'selector':'/work_kind/value','expected_value':'treatise','value_check':True,'current_raw_sha256':hashlib.sha256(content).hexdigest()}}
    decisions_path.write_bytes(source_metadata.canonical_bytes(decision))
    source_metadata.write_outputs(live, worklist_path=worklist_path, decisions_path=decisions_path)
    evidence_before = (live / 'evidence.json').read_bytes()
    index_before = (live / 'metadata/source-evidence/index.json').read_bytes()
    result = install_accepted_work(live, promoted.destination_root, work_id=WORK_ID)
    assert result['status'] == 'installed-and-validated'
    assert source_metadata.lookup_work_kind(live, live / relative)['evidence']['value'] == 'treatise'
    assert (live / 'evidence.json').read_bytes() == evidence_before
    assert (live / 'metadata/source-evidence/index.json').read_bytes() == index_before


def test_legacy_full_uuid_install_journal_remains_discoverable(tmp_path):
    legacy = tmp_path / ".tmp_audit" / ("accepted-install-" + "a" * 32)
    legacy.mkdir(parents=True)
    journal = {"work_id": "strong-systematic-theology-vol-3", "phase": "prepared"}
    (legacy / "operation.json").write_text(json.dumps(journal), encoding="utf-8")

    operation, loaded = _load_recovery_operation(
        tmp_path, "strong-systematic-theology-vol-3", None
    )
    assert operation == legacy.resolve()
    assert loaded == journal


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path seam")
def test_installer_copies_and_hashes_deep_windows_member(tmp_path):
    source = tmp_path / "promoted"
    incoming = tmp_path / "operation" / "incoming"
    member = (Path("forms") / ("f" * 74) / "editions" / ("e" * 74)
              / "acquisitions" / (("a" * 74) + ".json"))
    assert len(str(incoming / member)) > 260
    original = _io_path(source / member)
    original.parent.mkdir(parents=True)
    original.write_bytes(b"pinned acquisition")

    shutil.copytree(_io_path(source), _io_path(incoming))
    assert _files(source) == _files(incoming) == {member.as_posix(): _files(source)[member.as_posix()]}
    _io_path(incoming / member).write_bytes(b"changed acquisition")
    assert _files(source) != _files(incoming)


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path seam")
def test_installer_discovers_and_validates_long_promoted_acceptance(installation, tmp_path):
    _, promoted = installation
    deep_root = tmp_path / ("p" * 100)
    target = deep_root / "library" / "works" / WORK_ID
    acceptance = target / promoted.acceptance_path.relative_to(
        promoted.destination_root / "library" / "works" / WORK_ID
    )
    assert len(str(target)) < 260 < len(str(acceptance))

    try:
        shutil.copytree(_io_path(promoted.destination_root), _io_path(deep_root))
        assert _acceptance_paths(target) == [acceptance]
        records = _validate_promoted_tree(deep_root, target, work_id=WORK_ID)
        assert len(records) == 1
        assert records[0]["promotion"]["status"] == "promoted"
    finally:
        if _io_path(deep_root).exists():
            shutil.rmtree(_io_path(deep_root))
