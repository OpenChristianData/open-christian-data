"""Source-bound checks for the complete retained Schaff volume."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.lib.tei_link_check import check_links
from build.tei.lib029_complete_volume import _convert
from build.tei.lib029_complete_volume_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/lib029-complete-volume.source-manifest.json'
NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = reconstruct(source, tmp_path_factory.mktemp("schaff-complete") / "package", _convert)
    report = validate(source, package, _oracle)
    assert report.status == "pass"
    return source, package


def _reseal(path: Path, content: bytes) -> CandidatePackage:
    name = "content.tei.xml"
    (path / name).write_bytes(content)
    record = json.loads((path / "manifest.json").read_bytes())
    row = next(member for member in record["members"] if member["name"] == name)
    row.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    (path / "manifest.json").write_bytes((json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return CandidatePackage.load(path)


def test_complete_volume_covers_paratext_and_source_links(evidence) -> None:
    _, package = evidence
    accounting = json.loads(package.member_bytes("source-accountability.json"))
    tei = etree.fromstring(package.member_bytes("content.tei.xml"))
    text = tei.find(f"{{{NS}}}text")
    assert text is not None
    assert [etree.QName(child).localname for child in text] == ["front", "body", "back"]
    assert [row["source_xml_id"] for row in accounting["crosswalk"] if row["source_tag"] == "div1"] == ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"]
    assert accounting["feature_count"] == 36_679
    assert accounting["attribute_count"] == 56_432
    headings = [row for row in accounting["crosswalk"] if row["source_tag"] in {"h1", "h2", "h3", "h4", "h5", "h6", "title"}]
    assert len(headings) == 52
    assert len([row for row in headings if row["tei_tag"] == "head"]) == 38
    assert {row["source_xml_id"]: row["tei_attributes"]["rend"] for row in headings if row["tei_tag"] == "p"} == {
        "i-p1.2": "source-h1", "i-p1.3": "source-h4", "i-p1.4": "source-h2",
        "i-p2.1": "source-h4", "i-p2.2": "source-h3", "i-p2.3": "source-h5",
        "i-p5.1": "source-h5", "i-p6.1": "source-h3", "i-p6.4": "source-h3",
        "iii-p4.1": "source-h2", "iii-p8.1": "source-h1", "iii-p8.3": "source-h2",
        "iii-p8.4": "source-h3", "xi-p842.1": "source-h3",
    }
    assert len([row for row in accounting["crosswalk"] if row["source_tag"] == "a" and (row["attributes"].get("href") or "").startswith("#")]) == 5_327
    assert check_links(package.member_bytes("content.tei.xml"))["status"] == "pass"


@pytest.mark.parametrize("change", ["front", "back", "link"])
def test_oracle_rejects_semantic_loss(evidence, tmp_path: Path, change: str) -> None:
    source, package = evidence
    clone = tmp_path / "altered"
    shutil.copytree(package.path, clone)
    try:
        tei = etree.fromstring((clone / "content.tei.xml").read_bytes())
        text = tei.find(f"{{{NS}}}text")
        assert text is not None
        if change == "front":
            front = text.find(f"{{{NS}}}front")
            assert front is not None
            front.remove(front[0])
        elif change == "back":
            back = text.find(f"{{{NS}}}back")
            assert back is not None
            back.remove(back[0])
        else:
            ref = next(node for node in tei.iter(f"{{{NS}}}ref") if (node.get("target") or "").startswith("#lib029-f-"))
            ref.set("target", "#lib029-body")
        altered = _reseal(clone, etree.tostring(tei, encoding="UTF-8", xml_declaration=True))
        with pytest.raises(ValueError, match="differs from independent retained-source projection"):
            _oracle(source, altered)
    finally:
        resolved = clone.resolve(strict=True)
        resolved.relative_to(tmp_path.resolve(strict=True))
        if clone.is_symlink():
            raise ValueError("mutation copy became a reparse point")
        shutil.rmtree(clone)
