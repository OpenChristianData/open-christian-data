"""Focused NPNF206 work-local source-bound reconstruction proof."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tei.npnf206_work_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage, validate
from tests.npnf_work_runtime_baselines import current_work_baseline


ROOT = Path(__file__).resolve().parents[1]
WORK = "jerome-life-of-paulus"
MANIFEST = ROOT / "sources/structured-text/jerome-npnf206-works" / WORK / "source-manifest.json"
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def test_work_candidate_passes_and_resealed_text_change_fails(tmp_path: Path) -> None:
    cases = json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-npnf-work-late.json").read_bytes())
    case = next(row for row in cases if row["work_id"] == WORK)
    manifest, candidate = current_work_baseline(ROOT, case, tmp_path / "current")
    from build.tools.reconstruct_candidate import _bound_callable
    bound_oracle = _bound_callable(manifest.repository_root, manifest.record["validator"], role="validator")
    report = validate(manifest, candidate, bound_oracle)
    assert report.status == "pass"
    assert not report.findings

    content_path = candidate.path / "content.tei.xml"
    tree = etree.parse(str(content_path))
    paragraph = tree.xpath("/tei:TEI/tei:text/tei:body//tei:p", namespaces=TEI_NS)[0]
    paragraph.text = (paragraph.text or "") + " [invented]"
    changed = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    content_path.write_bytes(changed)
    record_path = candidate.path / "manifest.json"
    record = json.loads(record_path.read_bytes())
    member = next(item for item in record["members"] if item["name"] == "content.tei.xml")
    member["bytes"] = len(changed)
    member["sha256"] = sha256(changed).hexdigest()
    record_path.write_bytes(_canonical(record))
    with pytest.raises(ValueError, match="TEI direct text or tail drift"):
        _oracle(manifest, CandidatePackage.load(candidate.path))


def test_held_letters_collection_cannot_be_staged(tmp_path: Path) -> None:
    from build.tools.stage_npnf206_work_acceptance import prepare

    with pytest.raises(ValueError, match="outside exact NPNF206 set"):
        prepare("jerome-letters", tmp_path / "letters-stage", tmp_path / "letters-receipt.json")
