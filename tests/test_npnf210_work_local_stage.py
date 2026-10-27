"""Focused source conservation and reproduction for the LIB-044 work-local stage."""

from __future__ import annotations

import hashlib
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.npnf_ambrose_work_local_oracle import _oracle
from build.tools.stage_npnf210_work_local import ASSIGNED, EVIDENCE, ROOT, SOURCE_SHA256
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from tests.runtime_candidate_baselines import current_runtime_baseline, historical_bound_bytes


TEI_NS = "http://www.tei-c.org/ns/1.0"


ORIGINAL_EVIDENCE = EVIDENCE
ORIGINAL_EVIDENCE_SHA256 = "0c3a469215209eee9893f1a4d0c1e54590a0515524b0ff89bbb76c4ef73dd364"


@pytest.fixture(scope="module", autouse=True)
def current_nine_work_baselines(tmp_path_factory):
    observed_original = ORIGINAL_EVIDENCE.read_bytes()
    raw = historical_bound_bytes(ORIGINAL_EVIDENCE, ORIGINAL_EVIDENCE_SHA256)
    assert _sha(raw) == ORIGINAL_EVIDENCE_SHA256
    original = json.loads(raw)
    current = deepcopy(original)
    cases = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-npnf210-work.json").read_bytes())
    for case in cases:
        _, candidate = current_runtime_baseline(
            root=ROOT, original_manifest=case["original"], runtime_manifest=case["manifest"],
            retained_package=Path(case["retained_package"]), retained_sha256=case["retained_package_sha256"],
            destination=tmp_path_factory.mktemp("ambrose-work-current") / "candidate")
        row = next(row for row in current["works"] if row["work_id"] == case["work_id"])
        row.update(manifest_path=case["manifest"], manifest_sha256=_sha((ROOT / case["manifest"]).read_bytes()),
                   candidate_path=candidate.path.parent.as_posix(), candidate_sha256=candidate.sha256,
                   files=_files(candidate.path), validation_sha256=_sha((candidate.path.parent / "validation.json").read_bytes()))
    restored = deepcopy(current)
    for row, retained in zip(restored["works"], original["works"], strict=True):
        for field in ("manifest_path", "manifest_sha256", "candidate_path", "candidate_sha256", "files", "validation_sha256"):
            row[field] = retained[field]
    assert restored == original
    receipt = tmp_path_factory.mktemp("ambrose-current-receipt") / "receipt.json"
    receipt.write_bytes((json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(globals(), "EVIDENCE", receipt)
        yield
    assert ORIGINAL_EVIDENCE.read_bytes() == observed_original


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _files(path: Path) -> dict[str, str]:
    return {member.name: _sha(member.read_bytes()) for member in sorted(path.iterdir()) if member.is_file()}


def test_nine_work_boundaries_and_exact_stage_receipt() -> None:
    receipt = json.loads(EVIDENCE.read_bytes())
    assert receipt["status"] == "pass" and receipt["work_count"] == 9
    assert receipt["source_sha256"] == SOURCE_SHA256
    assert [(row["source_root_id"], row["work_id"]) for row in receipt["works"]] == list(ASSIGNED)
    source = (ROOT / "raw/ccel/npnf2/npnf210.xml").read_bytes()
    assert _sha(source) == SOURCE_SHA256
    tree = etree.fromstring(source, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    roots = [tree.xpath("//ThML.body//*[@id=$scope]", scope=scope)[0] for scope, _ in ASSIGNED]
    assert len({id(node) for node in roots}) == 9
    assert all(ancestor not in roots for node in roots for ancestor in node.iterancestors())
    assert sum(sum(isinstance(node.tag, str) for node in selected.iter()) for selected in roots) == 17_122
    for row in receipt["works"]:
        manifest_path = ROOT / row["manifest_path"]
        assert _sha(manifest_path.read_bytes()) == row["manifest_sha256"]
        destination = Path(row["candidate_path"])
        assert _files(destination / "package") == row["files"]
        assert _sha((destination / "validation.json").read_bytes()) == row["validation_sha256"]
        manifest = SourceManifest.load(manifest_path, repository_root=ROOT)
        candidate = CandidatePackage.load(destination / "package")
        assert _oracle(manifest, candidate)["status"] == "pass"


def test_all_nine_packages_reproduce_in_clean_process(tmp_path: Path) -> None:
    receipt = json.loads(EVIDENCE.read_bytes())
    for row in receipt["works"]:
        destination = tmp_path / row["work_id"]
        process = subprocess.run(
            [sys.executable, "-m", "build.tools.reconstruct_candidate", "--repository-root", str(ROOT), "--manifest", row["manifest_path"], "--destination", str(destination)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(process.stdout)["status"] == "pass"
        assert _files(destination / "package") == row["files"]
        assert _sha((destination / "validation.json").read_bytes()) == row["validation_sha256"]


def test_oracle_rejects_source_note_text_mutation(tmp_path: Path) -> None:
    row = next(item for item in json.loads(EVIDENCE.read_bytes())["works"] if item["work_id"] == "ambrose-of-milan-on-mysteries")
    source_package = Path(row["candidate_path"]) / "package"
    target = tmp_path / "candidate"
    target.mkdir()
    for member in source_package.iterdir():
        (target / member.name).write_bytes(member.read_bytes())
    xml_path = target / "content.tei.xml"
    tree = etree.parse(str(xml_path))
    note = tree.xpath("//tei:note", namespaces={"tei": TEI_NS})[0]
    note.text = (note.text or "") + " invented"
    xml_path.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False) + b"\n")
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == "content.tei.xml")
    payload = xml_path.read_bytes()
    member["bytes"] = len(payload)
    member["sha256"] = _sha(payload)
    manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    source = SourceManifest.load(ROOT / row["manifest_path"], repository_root=ROOT)
    candidate = CandidatePackage.load(target)
    with pytest.raises(ValueError, match="source-kind|direct text|crosswalk"):
        _oracle(source, candidate)
