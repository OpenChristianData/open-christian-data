"""Focused source boundaries and independent mutation checks for LIB-042."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.npnf109_work_oracle import _oracle
from build.tei.npnf109_work_reconstruction import _convert
from build.tools.prepare_npnf109_next_work_candidates import BATCH, HOME
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = Path(r"D:\Library\Open Christian Data\candidate-reviews\npnf109-next-four-work-candidates-20260927-v1\receipt.json")
TEI = "{http://www.tei-c.org/ns/1.0}"


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _reseal(path: Path) -> CandidatePackage:
    manifest = json.loads((path / "manifest.json").read_bytes())
    for member in manifest["members"]:
        content = (path / member["name"]).read_bytes()
        member["bytes"] = len(content)
        member["sha256"] = sha256(content).hexdigest()
    (path / "manifest.json").write_bytes(_json(manifest))
    return CandidatePackage.load(path)


def test_four_work_boundaries_and_candidate_receipts_match_current_source(tmp_path: Path) -> None:
    raw = RECEIPT.read_bytes()
    assert sha256(raw).hexdigest() == "e456b2e0f22b84620157c57c4a5493727f6d4d3648dbf9c43a4ebaadffdb2511"
    receipt = json.loads(raw)
    assert receipt["status"] == "validated-nonaccepted"
    assert [(item["source_root_id"], item["work_id"]) for item in receipt["works"]] == list(BATCH)
    for item in receipt["works"]:
        manifest = SourceManifest.load(ROOT / item["manifest_path"], repository_root=ROOT)
        candidate = CandidatePackage.load(Path(item["candidate_root"]) / "package")
        assert candidate.manifest["source_manifest"]["sha256"] == item["manifest_sha256"]
        assert manifest.record["source_id"] == f"{item['work_id']}-npnf109-native-root-v1"
        assert next(a["sha256"] for a in manifest.record["authorities"] if a["name"] == "retained-thml") == receipt["source_sha256"]
        assert candidate.sha256 == item["candidate_sha256"]
        current = reconstruct(manifest, tmp_path / item["work_id"], _convert)
        assert current.member_names == candidate.member_names
        for name in current.member_names:
            if name != "manifest.json":
                assert current.member_bytes(name) == candidate.member_bytes(name), name
        assert current.manifest["source_manifest"]["sha256"] == manifest.sha256
        report = validate(manifest, current, _oracle)
        assert report.status == "pass" and not report.findings


def test_work_source_oracle_rejects_missing_note_and_changed_title(tmp_path: Path) -> None:
    receipt = json.loads(RECEIPT.read_bytes())
    item = receipt["works"][0]
    manifest = SourceManifest.load(ROOT / HOME / item["work_id"] / "source-manifest.json", repository_root=ROOT)
    original = Path(item["candidate_root"]) / "package"
    for mutation in ("missing-note", "changed-title"):
        altered = tmp_path / mutation
        shutil.copytree(original, altered)
        tei_path = altered / "content.tei.xml"
        tree = etree.parse(str(tei_path))
        if mutation == "missing-note":
            notes = tree.findall(f".//{TEI}note")
            assert notes
            notes[0].getparent().remove(notes[0])
        else:
            title = tree.find(f".//{TEI}titleStmt/{TEI}title")
            assert title is not None
            title.text = "Changed title"
        tei_path.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True))
        candidate = _reseal(altered)
        with pytest.raises(ValueError):
            _oracle(manifest, candidate)
