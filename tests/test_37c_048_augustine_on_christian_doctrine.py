"""Exact-source contract for Ticket 37c-048 / LIB-008."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from lxml import etree

import pytest

from build.tei.augustine_on_christian_doctrine_oracle import _oracle
from build.tei.augustine_on_christian_doctrine_reconstruction import _convert
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]
if os.name == "nt":
    ROOT = Path("\\\\?\\" + str(ROOT))
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/augustine-on-christian-doctrine.source-manifest.json'
SOURCE = ROOT / "raw/ccel/npnf1/npnf102.xml"
NS = {"t": "http://www.tei-c.org/ns/1.0"}


def test_37c048_exact_source_and_complete_carrier_envelope() -> None:
    raw = SOURCE.read_bytes()
    assert len(raw) == 4_137_798
    assert hashlib.sha256(raw).hexdigest() == "b8ca21dfa7d553681651f85197064b0fe52ae6c17e5e17252df9301536a4ae2a"
    source = etree.parse(str(SOURCE), etree.XMLParser(resolve_entities=False, no_network=True))
    root = source.getroot()
    body = root.find("ThML.body")
    assert root.tag == "ThML"
    assert [child.get("id") for child in body] == ["i", "ii", "iii", "iv", "v", "vi", "vii"]
    selected = body.find("div1[@id='v']")
    assert selected.get("title") == "On Christian Doctrine"
    assert [child.get("id") for child in selected.findall("div2")] == [
        "v.i", "v.ii", "v.iii", "v.iv", "v.v", "v.vi", "IV_1"
    ]
    assert len([node for node in selected.iter() if isinstance(node.tag, str)]) == 1_974
    assert len(list(root.itersiblings(preceding=True))) == 2
    assert source.docinfo.public_id == "-//CCEL/DTD Theological Markup Language//EN"
    assert source.docinfo.system_url == "http://www.ccel.org/dtd/ThML10.dtd"
    assert [child.tag for child in root.find("ThML.head")] == [
        "generalInfo", "printSourceInfo", "electronicEdInfo", "style", "style"
    ]


def test_37c048_candidate_is_valid_and_package_reproduces(tmp_path: Path) -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    first = reconstruct(manifest, tmp_path / "first", _convert)
    first_validation = validate(manifest, first, _oracle)
    second = reconstruct(manifest, tmp_path / "second", _convert)
    second_validation = validate(manifest, second, _oracle)

    assert first.manifest["status"] == "nonaccepted"
    assert first_validation.status == second_validation.status == "pass"
    assert first.manifest == second.manifest
    assert first.member_names == second.member_names
    assert {name: first.member_bytes(name) for name in first.member_names} == {
        name: second.member_bytes(name) for name in second.member_names
    }
    tei = etree.fromstring(first.member_bytes("content.tei.xml"))
    assert tei.xpath("string(/t:TEI/t:teiHeader//t:titleStmt/t:title[1])", namespaces=NS) == "On Christian Doctrine"
    assert len(tei.xpath("/t:TEI/t:text/t:body/t:div/t:div", namespaces=NS)) == 7
    assert not tei.xpath("//t:head | //t:label", namespaces=NS)
    source = etree.fromstring(SOURCE.read_bytes(), etree.XMLParser(resolve_entities=False, no_network=True))
    selected = source.find("ThML.body/div1[@id='v']")
    originals = [node for node in selected.iter() if isinstance(node.tag, str)]
    positions = {node: index for index, node in enumerate(originals, 1)}
    divisions = [node for node in originals if node.tag.startswith("div")]
    assert len(divisions) == 158
    assert len(tei.xpath("/t:TEI/t:text/t:body//*", namespaces=NS)) == 1974
    for division in divisions:
        output = tei.xpath("//*[@xml:id=$identity]", identity=f"src-{positions[division]}")[0]
        assert [child.get("{http://www.w3.org/XML/1998/namespace}id") for child in output if isinstance(child.tag, str)] == [f"src-{positions[child]}" for child in division if isinstance(child.tag, str)]
        assert "".join(output.itertext()) == "".join(division.itertext())
    book = selected.find("div2[@id='v.iv']")
    assert len(book.findall("p")) >= 2
    assert "Book I." in "".join(book.findall("p")[0].itertext())
    ending = selected.xpath(".//*[@id='v.IV_1.31']")[0]
    assert "Chapter 31" in "".join(ending[0].itertext())
    assert "Apology" in "".join(ending[0].itertext())
    assert tei.xpath("boolean(//t:div[@type='Book'])", namespaces=NS)
    assert b"New York: The Christian Literature Publishing Co., 1890" in first.member_bytes("README.source.md")
    assert b"rights clearance, human acceptance, release, and publication authorization are not established" in first.member_bytes("README.source.md")


def test_37c048_independent_oracle_rejects_changed_candidate_text(tmp_path: Path) -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(manifest, tmp_path / "baseline", _convert)
    mutated_path = tmp_path / "mutated"
    shutil.copytree(candidate.path, mutated_path)
    tei_path = mutated_path / "content.tei.xml"
    tree = etree.parse(str(tei_path), etree.XMLParser(resolve_entities=False, no_network=True))
    paragraph = tree.find("./{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body//{http://www.tei-c.org/ns/1.0}p")
    assert paragraph is not None and paragraph.text
    paragraph.text = "Ticket 37c-048 mutation probe"
    mutated_bytes = etree.tostring(tree, encoding="utf-8", xml_declaration=True)
    tei_path.write_bytes(mutated_bytes)
    package_manifest_path = mutated_path / "manifest.json"
    package_manifest = json.loads(package_manifest_path.read_bytes())
    member = next(item for item in package_manifest["members"] if item["name"] == "content.tei.xml")
    member["bytes"] = len(mutated_bytes)
    member["sha256"] = hashlib.sha256(mutated_bytes).hexdigest()
    package_manifest_path.write_text(
        json.dumps(package_manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    mutated = CandidatePackage.load(mutated_path)
    with pytest.raises(ValueError, match="differs|changed"):
        validate(manifest, mutated, _oracle)


@pytest.mark.parametrize("mutation", ["duplicate", "deleted", "moved", "reversed", "concatenated", "title", "shorttitle"])
def test_37c048_heading_mutations_rejected(tmp_path: Path, mutation: str) -> None:
    manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(manifest, tmp_path / "candidate", _convert)
    validate(manifest, candidate, _oracle)
    source = etree.fromstring(SOURCE.read_bytes(), etree.XMLParser(resolve_entities=False, no_network=True))
    nodes = [node for node in source.find("ThML.body/div1[@id='v']").iter() if isinstance(node.tag, str)]
    ending = next(node for node in nodes if node.get("id") == "v.IV_1.31")
    tree = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    output = tree.xpath("//*[@xml:id=$identity]", identity=f"src-{nodes.index(ending) + 1}")[0]
    member_name = "content.tei.xml"
    if mutation in ("title", "shorttitle"):
        member_name = "source-accountability.json"
        accounting = json.loads(candidate.member_bytes(member_name))
        record = next(item for item in accounting["selected_features"] if item["native_id"] == "v.IV_1.31")
        record["attributes"][mutation] = "invented navigation title"
        content = json.dumps(accounting).encode("utf-8")
    else:
        heading = output[0]
        if mutation == "duplicate":
            invented = etree.Element("{http://www.tei-c.org/ns/1.0}head")
            invented.text = ending.get("title")
            output.insert(0, invented)
        elif mutation == "deleted":
            output.remove(heading)
        elif mutation == "moved":
            output.remove(heading)
            output.append(heading)
        else:
            for child in list(heading):
                heading.remove(child)
            heading.text = ending.get("title") + (ending.get("shorttitle") if mutation == "concatenated" else " Chapter 31.")
        content = etree.tostring(tree, encoding="utf-8", xml_declaration=True)
    (candidate.path / member_name).write_bytes(content)
    package = json.loads((candidate.path / "manifest.json").read_bytes())
    member = next(item for item in package["members"] if item["name"] == member_name)
    member.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    (candidate.path / "manifest.json").write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        validate(manifest, CandidatePackage.load(candidate.path), _oracle)
