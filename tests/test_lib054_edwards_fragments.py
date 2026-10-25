"""Exact enclosing-volume candidates and isolated acceptance swaps for Edwards."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.lib054_edwards_fragments_oracle import _verify
from build.tools.generate_lib054_edwards_fragment_manifests import VOLUMES, manifest_bytes
from build.tools.install_lib054_edwards_fragments import FIXTURE_MARKER, install, preflight
from build.tools.stage_lib054_edwards_fragments import _work_row
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _files, _io_path

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = Path(r"D:\Library\Open Christian Data")
FAMILY = Path("sources/structured-text/lib054-ccel-puritan/work-bindings")
STAGES = {
    "edwards-distinguishing-marks": "l54-edwards-m",
    "edwards-history-of-redemption": "l54-edwards-h",
}
EXPECTED_BOUNDARIES = {
    "edwards-distinguishing-marks": ("vii", 7, 16, 172, 464),
    "edwards-history-of-redemption": ("xii", 12, 15, 957, 3121),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


RUNTIME_CASES = {
    "edwards-distinguishing-marks": {
        "original": "sources/structured-text/lib054-ccel-puritan/work-bindings/edwards-distinguishing-marks/lib054-edwards-fragment.source-manifest.json",
        "original_sha256": "6ff4502d3efecbef3081ad7d42854506e5247ddca1ddb31308b35098fe0cf150",
        "manifest": "tests/fixtures/reconstruction-runtime/edwards-distinguishing-marks-fragment.source-manifest.json",
        "retained_candidate_sha256": "ae721946d9c2e3cdd6dfd17c659b626c97fa034ab95b54fcbef0807e6213c365"
    },
    "edwards-history-of-redemption": {
        "original": "sources/structured-text/lib054-ccel-puritan/work-bindings/edwards-history-of-redemption/lib054-edwards-fragment.source-manifest.json",
        "original_sha256": "5d31a9cad607b8902abf73de96ab028dff12206e55b26a1610bc1ae534e461f0",
        "manifest": "tests/fixtures/reconstruction-runtime/edwards-history-of-redemption-fragment.source-manifest.json",
        "retained_candidate_sha256": "c434faf86057b24202198859e0694934133084b8fd406960de96e7aec2ae8dcb"
    }
}
CURRENT_CLOSURE = '7992f1e8b05321e6253a3f8ba3eadb293a514c3152b4aefd33017f5a3a22a9d7'


def _manifest(work_id: str) -> SourceManifest:
    case = RUNTIME_CASES[work_id]
    original = (ROOT / case["original"]).read_bytes()
    assert _sha(original) == case["original_sha256"]
    expected = json.loads(original)
    expected["validator"]["import_closure_sha256"] = CURRENT_CLOSURE
    fixture = ROOT / case["manifest"]
    assert json.loads(fixture.read_bytes()) == expected
    assert fixture.read_bytes() == manifest_bytes(ROOT, work_id)
    return SourceManifest.load(fixture, repository_root=ROOT)


@pytest.mark.parametrize("work_id", STAGES)
def test_runtime_manifest_preserves_complete_original_record(work_id: str) -> None:
    from ocd_kernel.reconstruction.closure_verification import check_validator_manifest_closure

    manifest = _manifest(work_id)
    original = check_validator_manifest_closure(ROOT, RUNTIME_CASES[work_id]["original"])
    assert not original.matches
    assert original.live_sha256 == CURRENT_CLOSURE
    assert check_validator_manifest_closure(ROOT, manifest.path.relative_to(ROOT)).matches


@pytest.fixture(scope="module")
def current_candidates(tmp_path_factory):
    from tests.runtime_candidate_baselines import current_runtime_baseline

    result = {}
    for work_id, case in RUNTIME_CASES.items():
        destination = tmp_path_factory.mktemp("edwards-current") / "handoff"
        manifest, candidate = current_runtime_baseline(
            root=ROOT, original_manifest=case["original"], runtime_manifest=case["manifest"],
            retained_package=_candidate(work_id).path,
            retained_sha256=case["retained_candidate_sha256"], destination=destination,
        )
        assert manifest.sha256 == _manifest(work_id).sha256
        result[work_id] = (manifest, candidate, destination)
    return result


def _candidate(work_id: str) -> CandidatePackage:
    return CandidatePackage.load(LIBRARY / "candidate-reviews" / f"lib054-work-{work_id}-20260926-v3" / "package")


def _stage(work_id: str) -> tuple[Path, str]:
    stage = LIBRARY / STAGES[work_id]
    return stage, _sha((stage / "stage-receipt.json").read_bytes())


@pytest.mark.parametrize("work_id", STAGES)
def test_exact_volume_division_and_candidate(work_id: str, current_candidates) -> None:
    manifest, candidate, handoff = current_candidates[work_id]
    validation = json.loads((handoff / "validation.json").read_bytes())
    facts = _verify(manifest, candidate)
    division_id, position, total, backlinks, nodes = EXPECTED_BOUNDARIES[work_id]
    assert validation["status"] == "pass"
    assert validation["source_manifest_sha256"] == manifest.sha256
    assert validation["candidate_sha256"] == candidate.sha256
    assert facts["body_nodes"] == nodes
    assert facts["body_child_position"] == position
    assert facts["index_backlinks_to_work"] == backlinks
    assert candidate.manifest["status"] == "nonaccepted"
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))["enclosing_volume"]
    assert (accounting["source_division_id"], accounting["body_child_count"]) == (division_id, total)
    assert accounting["path"] == VOLUMES[work_id].as_posix()


@pytest.mark.parametrize("work_id", STAGES)
def test_clean_process_reproduces_every_candidate_member(work_id: str, tmp_path: Path, current_candidates) -> None:
    relative = Path(RUNTIME_CASES[work_id]["manifest"])
    destination = tmp_path / "candidate"
    subprocess.run([sys.executable, "-m", "build.tools.reconstruct_candidate",
                    "--manifest", relative.as_posix(), "--destination", str(destination),
                    "--repository-root", str(ROOT)], cwd=ROOT, check=True,
                   capture_output=True, text=True)
    expected = current_candidates[work_id][2]
    for relative_member in (
        "package/README.source.md", "package/content.tei.xml", "package/manifest.json",
        "package/provenance.json", "package/source-accountability.json",
        "package/unresolved.jsonl", "validation.json", "text-quality.json",
    ):
        assert (destination / relative_member).read_bytes() == (expected / relative_member).read_bytes()


def test_oracle_rejects_fabricated_enclosing_volume_provenance(tmp_path: Path, current_candidates) -> None:
    work_id = "edwards-distinguishing-marks"
    candidate = current_candidates[work_id][1]
    members = {name: candidate.member_bytes(name) for name in candidate.member_names}
    tei = etree.fromstring(members["content.tei.xml"])
    notes = tei.xpath(".//*[local-name()='note' and @type='extracted-fragment']")
    assert len(notes) == 1
    notes[0].text = "This work includes the volume index."
    members["content.tei.xml"] = etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False) + b"\n"
    record = json.loads(members["manifest.json"])
    for item in record["members"]:
        if item["name"] == "content.tei.xml":
            item["bytes"] = len(members["content.tei.xml"])
            item["sha256"] = _sha(members["content.tei.xml"])
    members["manifest.json"] = _json(record)
    for name, content in members.items():
        (tmp_path / name).write_bytes(content)
    with pytest.raises(ValueError, match="TEI extraction provenance differs"):
        _verify(_manifest(work_id), CandidatePackage.load(tmp_path))


@pytest.mark.parametrize("work_id", STAGES)
def test_read_only_preflight_checks_staged_actual_master(work_id: str, tmp_path: Path) -> None:
    root, stage, work, pin = _fixture_root(tmp_path, work_id)
    before = _files(root / work)
    with pytest.raises(PipelineError, match="three-file acquired baseline"):
        preflight(work_id, stage, pin)
    report = preflight(work_id, stage, pin, root_override=root)
    assert _files(root / work) == before
    assert not (root / "library/.sidecar-operations").exists()
    assert report["status"] == "pass-read-only"
    assert report["current_work_files"] == 3
    assert report["staged_work_files"] > 3
    assert report["projection_rows"] == 1
    assert report["projection_independent_verifier_errors"] == []


def _fixture_root(tmp_path: Path, work_id: str) -> tuple[Path, Path, Path, str]:
    root = tmp_path / "fixture"
    root.mkdir()
    (root / FIXTURE_MARKER).write_text("isolated Edwards fragment fixture\n", encoding="utf-8")
    stage, pin = _stage(work_id)
    work = Path("library/works") / work_id
    prefix = work.as_posix() + "/"
    for relative in _files(stage):
        if relative == "stage-receipt.json" or relative.startswith(prefix):
            continue
        target = _io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(stage / relative), target)
    row = _work_row(work_id)
    edition = work / "forms" / row["form_id"] / "editions" / row["edition_id"]
    acquisition = edition / "acquisitions" / (row["acquisition_id"] + ".json")
    target = _io_path(root / acquisition)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(stage / acquisition), target)
    work_record = json.loads((stage / work / "work.json").read_bytes())
    work_record.pop("creators")
    work_record["textual_forms"][0]["editions"][0].pop("category")
    state = json.loads((stage / work / "state.json").read_bytes())
    target_state = next(item for item in state["targets"] if item["target_id"] == row["edition_id"])
    target_state["stage"] = "acquired"
    target_state.pop("reason")
    target_state["evidence"] = target_state["evidence"][:-2]
    for name, value in (("work.json", work_record), ("state.json", state)):
        (root / work / name).write_bytes(_json(value))
    return root, stage, work, pin


@pytest.mark.parametrize("work_id", STAGES)
def test_guarded_fixture_install_and_actual_master(work_id: str, tmp_path: Path) -> None:
    root, stage, work, pin = _fixture_root(tmp_path, work_id)
    before = _files(root / work)
    report = install(work_id, stage, pin, root_override=root)
    assert report["status"] == "installed-and-validated"
    assert report["projection_rows"] == 1
    assert _files(root / work) == _files(stage / work)
    operations = list((root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    journal = json.loads((operations[0] / "operation.json").read_bytes())
    assert journal["phase"] == "complete"
    assert _files(operations[0] / "previous") == before


@pytest.mark.parametrize("phase", ["after-old-rename", "after-new-rename"])
def test_injected_failure_restores_prior_generation(phase: str, tmp_path: Path) -> None:
    work_id = "edwards-distinguishing-marks"
    root, stage, work, pin = _fixture_root(tmp_path, work_id)
    before = _files(root / work)

    def fail_at(reached: str) -> None:
        if reached == phase:
            raise RuntimeError("injected " + phase)

    with pytest.raises(RuntimeError, match="injected " + phase):
        install(work_id, stage, pin, root_override=root, fail_at=fail_at)
    assert _files(root / work) == before
    operations = list((root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    assert json.loads((operations[0] / "operation.json").read_bytes())["phase"] == "rolled-back"
    assert preflight(work_id, stage, pin, root_override=root)["status"] == "pass-read-only"


def test_stale_receipt_pin_rejected_before_fixture_swap(tmp_path: Path) -> None:
    work_id = "edwards-history-of-redemption"
    root, stage, _, _ = _fixture_root(tmp_path, work_id)
    with pytest.raises(PipelineError, match="receipt differs"):
        preflight(work_id, stage, "0" * 64, root_override=root)
    assert not (root / "library/.sidecar-operations").exists()
