"""Exact retained-source and guarded-stage regressions for LIB-054 children."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from lxml import etree
import pytest

from build.tei.lib054_work_local_oracle import _verify
from build.tools.install_lib054_full_witness_acceptance import preflight
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files
from tests.runtime_candidate_baselines import current_runtime_baseline
from tests.test_install_lib054_full_witness_acceptance import _fixture_root

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = Path(r"D:\Library\Open Christian Data")
FAMILY = ROOT / "sources/structured-text/lib054-ccel-puritan"
WORKS = (
    "baxter-call-to-unconverted", "baxter-reformed-pastor", "baxter-saints-rest",
    "boston-crook-in-the-lot", "bunyan-grace-abounding", "bunyan-holy-war",
    "butler-analogy-of-religion", "edwards-distinguishing-marks",
    "edwards-freedom-of-the-will", "edwards-history-of-redemption",
)
STAGES = {
    "baxter-call-to-unconverted": "l54-baxter-call-v2",
    "baxter-reformed-pastor": "l54-baxter-pastor-v2",
    "baxter-saints-rest": "l54-baxter-saints-v2",
    "boston-crook-in-the-lot": "l54-boston-crook-v2",
    "bunyan-grace-abounding": "l54-bunyan-grace-v2",
    "bunyan-holy-war": "l54-bunyan-war-v2",
    "butler-analogy-of-religion": "l54-butler-analogy-v2",
    "edwards-freedom-of-the-will": "l54-edwards-will-v2",
}
STAGE_RECEIPT_SHA256 = {'baxter-call-to-unconverted': 'a872fed49fe370ed8b1ff54c5614056f8ac4d847a69b927e21c33576aa236f70', 'baxter-reformed-pastor': '5b017bd398911541c911a970f91f8c3db6a7b0b29ec041104254b07d0b0f3238', 'baxter-saints-rest': '9f088f47b7fd119baddb5d9561df528d6abcb277e9c2c428d1b107f356a0b01a', 'boston-crook-in-the-lot': 'eeaa9e0d9dec683a1ccadf3d482b9f60c80f2d6479f6dcaeb5d28418a98523ff', 'bunyan-grace-abounding': '868730dd94fcd1a70e0964be0f6596d0d347dcd064ef387712dd0c0fa6d4d64c', 'bunyan-holy-war': 'a0d94a7aad643c24df0950c356de53e0fd150b6e680ac36ff082956e9aa20903', 'butler-analogy-of-religion': 'a7ad6ccf715ce5b0f5ddb7d8366eb7238aa3b49e0dbb793ee5cd8dca07671b19', 'edwards-freedom-of-the-will': 'a9b9c92f412cfc4b74c034b24a4623c1321ebc55bd2af77a26ce8b5e98eed65a'}
TEI_NS = "http://www.tei-c.org/ns/1.0"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _runtime_case(work_id: str):
    cases = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-lib054-work-local.json").read_bytes())
    matches = [case for case in cases if case["work_id"] == work_id]
    assert len(matches) == 1
    return matches[0]


def _manifest(work_id: str) -> SourceManifest:
    return SourceManifest.load(ROOT / _runtime_case(work_id)["manifest"], repository_root=ROOT)


@pytest.fixture(scope="module")
def runtime_baselines(tmp_path_factory):
    result = {}
    for work_id in WORKS:
        case = _runtime_case(work_id)
        result[work_id] = current_runtime_baseline(
            root=ROOT, original_manifest=case["original"], runtime_manifest=case["manifest"],
            retained_package=_candidate(work_id).path,
            retained_sha256=case["retained_package_sha256"],
            destination=tmp_path_factory.mktemp("lib054-runtime") / "candidate",
        )
    return result


def _candidate(work_id: str) -> CandidatePackage:
    return CandidatePackage.load(LIBRARY / "candidate-reviews" / f"lib054-work-{work_id}-20260926-v2" / "package")


def _mutated(candidate: CandidatePackage, destination: Path, change) -> CandidatePackage:
    destination.mkdir()
    members = {name: candidate.member_bytes(name) for name in candidate.member_names}
    tree = etree.fromstring(members["content.tei.xml"])
    change(tree, json.loads(members["source-accountability.json"]))
    members["content.tei.xml"] = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False) + b"\n"
    record = json.loads(members["manifest.json"])
    for item in record["members"]:
        if item["name"] == "content.tei.xml":
            item["bytes"] = len(members["content.tei.xml"])
            item["sha256"] = _sha(members["content.tei.xml"])
    members["manifest.json"] = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    for name, content in members.items():
        (destination / name).write_bytes(content)
    return CandidatePackage.load(destination)


def _mapped(tree: etree._Element, row: dict[str, object]) -> etree._Element:
    target_id = str(row["tei_selector"])[1:]
    result = tree.xpath("//*[@xml:id=$target_id]", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"}, target_id=target_id)
    assert len(result) == 1
    return result[0]


def test_all_ten_readable_work_local_candidates_are_source_checked(runtime_baselines) -> None:
    total = 0
    for work_id in WORKS:
        manifest, candidate = runtime_baselines[work_id]
        validation = json.loads((candidate.path.parent / "validation.json").read_bytes())
        facts = _verify(manifest, candidate)
        assert validation["status"] == "pass"
        assert validation["candidate_sha256"] == candidate.sha256
        assert validation["source_manifest_sha256"] == manifest.sha256
        assert candidate.manifest["status"] == "nonaccepted"
        assert facts["work_id"] == work_id and facts["paragraphs"] > 0
        total += facts["body_nodes"]
    assert total > 10_000


def test_source_division_heading_demotion_is_rejected(tmp_path: Path, runtime_baselines) -> None:
    manifest, candidate = runtime_baselines["baxter-call-to-unconverted"]

    def demote(tree: etree._Element, accounting: dict[str, object]) -> None:
        row = next(row for row in accounting["body_crosswalk"] if row["source_tag"] == "h2" and row["tei_tag"] == "head")
        _mapped(tree, row).tag = f"{{{TEI_NS}}}p"

    with pytest.raises(ValueError, match="source division heading lost"):
        _verify(manifest, _mutated(candidate, tmp_path / "heading", demote))


def test_work_local_link_retarget_is_rejected(tmp_path: Path, runtime_baselines) -> None:
    manifest, candidate = runtime_baselines["butler-analogy-of-religion"]

    def retarget(tree: etree._Element, accounting: dict[str, object]) -> None:
        row = next(row for row in accounting["body_crosswalk"] if row["source_tag"] == "a" and str(row["attributes"].get("href", "")).startswith("#"))
        _mapped(tree, row).set("target", "#butler-analogy-of-religion")

    with pytest.raises(ValueError, match="source link target changed"):
        _verify(manifest, _mutated(candidate, tmp_path / "link", retarget))


def test_eight_full_witness_stages_pass_exact_read_only_preflight(tmp_path: Path) -> None:
    for work_id, name in STAGES.items():
        # Reuse the existing synthetic acquired baseline; no historical before-hash claim.
        parent = tmp_path / work_id
        parent.mkdir()
        root, stage, work, receipt_sha = _fixture_root(parent, work_id)
        assert stage == LIBRARY / name
        assert receipt_sha == STAGE_RECEIPT_SHA256[work_id]
        before, staged = _files(root / work), _files(stage / work)
        report = preflight(work_id, stage, receipt_sha, root_override=root)
        assert _files(root / work) == before and _files(stage / work) == staged
        assert not (root / "library/.sidecar-operations").exists()
        assert report["status"] == "pass-read-only"
        assert report["current_work_files"] == 3
        assert report["staged_work_files"] > 3
        assert report["projection_rows"] == 1
        assert report["projection_independent_verifier_errors"] == []


def test_guard_rejects_stale_receipt_pin() -> None:
    with pytest.raises(ValueError, match="receipt differs"):
        preflight("baxter-call-to-unconverted", LIBRARY / STAGES["baxter-call-to-unconverted"], "0" * 64)


@pytest.mark.parametrize("work_id", ["butler-analogy-of-religion", "edwards-distinguishing-marks"])
def test_clean_process_reproduces_source_checked_candidate(work_id: str, tmp_path: Path, runtime_baselines) -> None:
    manifest_path = ROOT / _runtime_case(work_id)["manifest"]
    destination = tmp_path / work_id
    subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--manifest", str(manifest_path.relative_to(ROOT)), "--destination", str(destination), "--repository-root", str(ROOT)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    expected = runtime_baselines[work_id][1].path.parent
    for relative in ("package/README.source.md", "package/content.tei.xml", "package/manifest.json", "package/provenance.json", "package/source-accountability.json", "package/unresolved.jsonl", "validation.json"):
        assert (destination / relative).read_bytes() == (expected / relative).read_bytes()


@pytest.mark.parametrize("work_id", STAGES)
def test_current_accepted_generation_is_not_the_acquired_fixture(work_id: str) -> None:
    with pytest.raises(PipelineError, match="canonical work is not the declared three-file acquired baseline"):
        preflight(work_id, LIBRARY / STAGES[work_id], STAGE_RECEIPT_SHA256[work_id])
