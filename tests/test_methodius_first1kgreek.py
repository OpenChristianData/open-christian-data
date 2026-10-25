"""Source-bound tests for the complete Methodius First1KGreek TEI member."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

from lxml import etree
from tests.historical_authority_mirrors import prepare_historical_mirror
import pytest

from build.tei.methodius_first1kgreek_oracle import _oracle, source_inventory
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state


ROOT = Path(__file__).resolve().parents[1]
_BOUND_ROOT = ROOT
MANIFEST = ROOT / "sources/manifest-acquisitions/methodius-symposium-first1kgreek/source-manifest.json"
CANDIDATE = Path(
    os.environ.get(
        "OCD_METHODIUS_CANDIDATE",
        r"D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260925\methodius-symposium-first1kgreek-v3\package",
    )
)
TEI = "{http://www.tei-c.org/ns/1.0}"


@pytest.fixture(scope="module", autouse=True)
def historical_authorities(tmp_path_factory):
    mirror, path = prepare_historical_mirror(ROOT, tmp_path_factory.mktemp("methodius-authorities") / "root", "methodius")
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(globals(), "MANIFEST", path)
        patch.setitem(globals(), "_BOUND_ROOT", mirror)
        yield


def _bound():
    return SourceManifest.load(MANIFEST, repository_root=_BOUND_ROOT), CandidatePackage.load(CANDIDATE)


def _changed_package(tmp_path: Path, changed: bytes) -> CandidatePackage:
    output = tmp_path / "package"
    shutil.copytree(CANDIDATE, output)
    (output / "content.tei.xml").write_bytes(changed)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    record = next(item for item in manifest["members"] if item["name"] == "content.tei.xml")
    record["bytes"] = len(changed)
    record["sha256"] = hashlib.sha256(changed).hexdigest()
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return CandidatePackage.load(output)


def test_source_inventory_and_baseline_oracle():
    source_manifest, candidate = _bound()
    source = source_manifest.authority_path("retained-tei").read_bytes()
    inventory = source_inventory(source)
    assert inventory["title"] == "Symposium Sive Convivium Decem Virginum"
    assert inventory["cts_edition"] == "urn:cts:greekLit:tlg2959.tlg001.opp-grc1"
    assert [book["book"] for book in inventory["book_chapter_counts"]] == [
        "praef", *map(str, range(1, 12))
    ]
    assert inventory["element_counts"]["note"] == 329
    candidate_content = candidate.member_bytes("content.tei.xml")
    assert candidate_content == source
    source_root = etree.fromstring(source)
    candidate_root = etree.fromstring(candidate_content)
    closing_xpath = "/t:TEI/t:text/t:body/t:div[@type='edition']/t:div[@subtype='book' and @n='11']/t:div[@subtype='chapter' and @n='1']"
    source_chapters = source_root.xpath(closing_xpath, namespaces={"t": TEI[1:-1]})
    candidate_chapters = candidate_root.xpath(closing_xpath, namespaces={"t": TEI[1:-1]})
    for root, chapters in ((source_root, source_chapters), (candidate_root, candidate_chapters)):
        assert len(root.xpath("/t:TEI", namespaces={"t": TEI[1:-1]})) == 1
        assert len(root.xpath("/t:TEI/t:text/t:body/*", namespaces={"t": TEI[1:-1]})) == 1
        assert len(chapters) == 1
        chapter = chapters[0]
        book = chapter.getparent()
        assert book.get("n") == "11" and len(list(book.itersiblings())) == 0
        assert chapter.get("n") == "1" and len(list(chapter.itersiblings())) == 0
        assert len(chapter.xpath("./t:pb[@n='141']", namespaces={"t": TEI[1:-1]})) == 1
        children = list(chapter)
        marker = next(i for i, node in enumerate(children) if etree.QName(node).localname == "pb" and node.get("n") == "141")
        assert [etree.QName(node).localname for node in children[marker + 1:]] == ["p", "note", "note"]
    assert etree.tostring(source_chapters[0], method="c14n") == etree.tostring(candidate_chapters[0], method="c14n")
    result = _oracle(source_manifest, candidate)
    assert result["status"] == "pass", result["findings"]


@pytest.mark.parametrize("mutation", ["title", "note-type", "book-order", "closing-anchor"])
def test_oracle_rejects_source_feature_mutations(tmp_path: Path, mutation: str):
    source_manifest, candidate = _bound()
    content = candidate.member_bytes("content.tei.xml")
    if mutation == "title":
        before = b"Symposium Sive Convivium Decem Virginum"
        assert content.count(before) == 1
        changed = content.replace(before, b"Symposium Sive Convivium Novum", 1)
        assert source_inventory(changed)["title"] != source_inventory(content)["title"]
    elif mutation == "note-type":
        before = b'type="footnote"'
        assert content.count(before) == 329
        changed = content.replace(before, b'type="endnote"', 1)
        assert changed.count(b'type="footnote"') == 328
    elif mutation == "closing-anchor":
        tree = etree.fromstring(content)
        chapter = tree.xpath(
            "/t:TEI/t:text/t:body/t:div[@type='edition']/t:div[@subtype='book' and @n='11']/t:div[@subtype='chapter' and @n='1']",
            namespaces={"t": TEI[1:-1]},
        )[0]
        marker = chapter.xpath("./t:pb[@n='141']", namespaces={"t": TEI[1:-1]})[0]
        following = marker.getnext()
        assert following is not None and etree.QName(following).localname == "p"
        chapter.remove(following)
        changed = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
        assert len(etree.fromstring(changed).xpath(
            "/t:TEI/t:text/t:body/t:div[@type='edition']/t:div[@subtype='book' and @n='11']/t:div[@subtype='chapter' and @n='1']/t:pb[@n='141']/following-sibling::t:p[1]",
            namespaces={"t": TEI[1:-1]},
        )) == 0
    else:
        tree = etree.fromstring(content)
        edition = tree.find(f"{TEI}text/{TEI}body/{TEI}div")
        assert edition is not None
        books = [node for node in edition if node.tag == f"{TEI}div" and node.get("subtype") == "book"]
        assert len(books) == 12
        first, second = books[1:3]
        edition.remove(second)
        edition.insert(edition.index(first), second)
        changed = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
        assert [book["book"] for book in source_inventory(changed)["book_chapter_counts"][:3]] == ["praef", "2", "1"]
    result = _oracle(source_manifest, _changed_package(tmp_path, changed))
    assert result["status"] == "fail"
    assert any("byte conservation failed" in finding for finding in result["findings"])


def test_exact_v2_catalog_linkage_and_reproduction() -> None:
    source_manifest, candidate = _bound()
    base = ROOT / "library/works/methodius-symposium"
    work = load_work(base / "work.json")
    acquisition = base / "forms/ancient-greek/editions/bonwetsch-1917-first1k-opp-grc1/acquisitions/first1kgreek-8ee111e.json"
    validate_acquisition(acquisition, root=ROOT)
    validate_state(base / "state.json", root=ROOT)
    source_record = source_manifest.record
    assert source_record["work_id"] == "methodius-symposium"
    assert source_record["edition_id"] == "bonwetsch-1917-first1k-opp-grc1"
    assert source_record["acquisition_id"] == "first1kgreek-8ee111e"
    assert source_record["repository_revision"] == "8ee111eb44ecef4120c844e10749178d95d1f30c"
    receipt = json.loads(source_manifest.authority_path("acquisition-receipt").read_bytes())
    assert receipt["source_path"] == "raw/first1kgreek/methodius-symposium-1917/tlg2959.tlg001.opp-grc1.xml"
    assert receipt["sha256"] == hashlib.sha256(candidate.member_bytes("content.tei.xml")).hexdigest()
    package_manifest = json.loads((CANDIDATE / "manifest.json").read_bytes())
    assert package_manifest["source_manifest"]["sha256"] == source_manifest.sha256
    state = json.loads((base / "state.json").read_bytes())
    edition = next(target for target in state["targets"] if target["target_type"] == "edition")
    assert edition["stage"] == "accepted"
    acceptance_path = acquisition.parent.parent / "acceptance.json"
    assert acceptance_path.relative_to(ROOT).as_posix() in edition["evidence"]
    acceptance = json.loads(acceptance_path.read_bytes())
    assert acceptance["identity"]["work_id"] == work["work_id"]
    assert acceptance["identity"]["edition_id"] == source_record["edition_id"]
    assert acceptance["promotion"]["status"] == "promoted"
    master = acceptance["promotion"]["master"]
    master_bytes = (ROOT / master["path"]).read_bytes()
    assert len(master_bytes) == master["bytes"]
    assert hashlib.sha256(master_bytes).hexdigest() == master["sha256"]
    closeout_path = ROOT / "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/L813_METHODIUS_CURRENT_TECHNICAL_CLOSEOUT_20260930.json"
    closeout = json.loads(closeout_path.read_bytes())
    closeout_ref = closeout_path.relative_to(ROOT).as_posix()
    assert closeout_ref in edition["evidence"]
    assert closeout["identity"]["work_id"] == work["work_id"] == "methodius-symposium"
    assert closeout["identity"]["edition_id"] == source_record["edition_id"]
    assert closeout["identity"]["acquisition_id"] == source_record["acquisition_id"]
    assert closeout["source"]["source_manifest"]["sha256"] == source_manifest.sha256
    assert closeout["candidate"]["package_manifest_sha256"] == candidate.sha256
    assert closeout["candidate"]["tei_sha256"] == hashlib.sha256(candidate.member_bytes("content.tei.xml")).hexdigest()
    assert closeout["candidate"]["validation"]["status"] == "pass"
    assert closeout["candidate"]["validation"]["findings"] == []
    validation_bytes = (CANDIDATE.parent / "validation.json").read_bytes()
    assert closeout["candidate"]["validation"]["sidecar_sha256"] == hashlib.sha256(validation_bytes).hexdigest()
    assert closeout["candidate"]["package_status"] == "nonaccepted"
    assert closeout["workcatalog"]["acquisition_stage"] == "acquired"
    assert closeout["workcatalog"]["edition_stage"] == "review"
    assert closeout["workcatalog"]["candidate_acceptance"] == "not recorded; unchanged"
    assert closeout["workcatalog"]["rights"] == "not cleared; unchanged"
    assert closeout["workcatalog"]["publication"] == "not authorized; unchanged"
    assert "source segment remains outside governed segment range" in closeout["closing_anchor"]["visual_limit"]
    assert any("print-edition visual collation are not established" in item for item in closeout["candidate"]["unresolved"])
