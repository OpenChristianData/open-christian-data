"""Focused source boundaries and independent mutation checks for LIB-042."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.npnf109_work_oracle import _oracle
from build.tools.prepare_npnf109_final_work_candidates import BATCH, HOME
from build.tools.stage_npnf109_final_work_acceptance import prepare as stage_prepare
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = Path(r"D:\Library\Open Christian Data\candidate-reviews\npnf109-final-four-work-candidates-20260927-v1\receipt.json")
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


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
    raw_receipt = RECEIPT.read_bytes()
    assert sha256(raw_receipt).hexdigest() == "04026a8b3aba74339e93e21cf652d9c58466929fd55542be93f5b12ca14756c1"
    receipt = json.loads(raw_receipt)
    assert receipt["status"] == "validated-nonaccepted"
    assert [(item["source_root_id"], item["work_id"]) for item in receipt["works"]] == list(BATCH)
    for item in receipt["works"]:
        manifest = SourceManifest.load(ROOT / item["manifest_path"], repository_root=ROOT)
        candidate = CandidatePackage.load(Path(item["candidate_root"]) / "package")
        # The retained package keeps the exact historical receipt identity;
        # the current independently verified manifest may bind later metadata.
        assert candidate.manifest["source_manifest"]["sha256"] == item["manifest_sha256"]
        assert manifest.record["source_id"] == f"{item['work_id']}-npnf109-native-root-v1"
        assert next(a["sha256"] for a in manifest.record["authorities"] if a["name"] == "retained-thml") == receipt["source_sha256"]
        assert candidate.sha256 == item["candidate_sha256"]
        if item["work_id"] in {"chrysostom-letters-to-olympias", "chrysostom-correspondence-with-rome"}:
            from tests.npnf_four_install_fixture import historical_child_manifest
            manifest = historical_child_manifest(ROOT, manifest, tmp_path / item["work_id"])
        result = _oracle(manifest, candidate)
        assert result["status"] == "pass" and result["findings"] == []


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


def test_series_homilies_remain_navigable_and_letter_roots_are_held(tmp_path: Path) -> None:
    receipt = json.loads(RECEIPT.read_bytes())
    item = next(row for row in receipt["works"] if row["source_root_id"] == "xix")
    manifest = SourceManifest.load(ROOT / item["manifest_path"], repository_root=ROOT)
    source = etree.fromstring(manifest.authority_path("retained-thml").read_bytes())
    body = source.find("ThML.body")
    assert body is not None
    series = next(node for node in body if node.get("id") == "xix")
    source_homilies = [node for node in series if node.tag == "div2"][2:]
    assert len(source_homilies) == 21
    assert [node.get("title") for node in source_homilies] == [
        "Homily I", "Homily II", "Homily III", "Homily IV", "Homily V", "Homily VI",
        "Homily VII", "Homily VIII", "Homily IX", "Homily X", "Homily XI", "Homily XII",
        "Homily XIII", "Homily XIV", "Homily XV", "Homily XVI", "Homily XVII",
        "Homily XVIII", "Homily XIX", "Homily XX", "Homily XXI",
    ]
    package = CandidatePackage.load(Path(item["candidate_root"]) / "package")
    tei = etree.fromstring(package.member_bytes("content.tei.xml"))
    work = tei.find(f"./{TEI}text/{TEI}body/{TEI}div")
    assert work is not None
    tei_homilies = work.findall(f"{TEI}div")[2:]
    assert len(tei_homilies) == 21
    assert [node.get(XML_ID) for node in tei_homilies] == [
        f"npnf109-{node.get('id')}" for node in source_homilies
    ]
    assert [node.find(f"{TEI}head").text for node in tei_homilies] == [
        node.get("title") for node in source_homilies
    ]
    held = {"xvii": "chrysostom-letters-to-olympias",
            "xviii": "chrysostom-correspondence-with-rome"}
    for root_id, work_id in held.items():
        selected = next(node for node in body if node.get("id") == root_id)
        assert len([node for node in selected if node.tag == "div2"]) >= 6
        with pytest.raises(ValueError, match="constituent representation review"):
            stage_prepare(work_id, tmp_path / work_id, tmp_path / f"{work_id}.json")
