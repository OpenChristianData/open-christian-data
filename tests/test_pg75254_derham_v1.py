from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest
from build.tei import pg75254_derham_v1 as producer
from build.tei import pg75254_derham_v1_oracle as oracle

ROOT = Path(__file__).resolve().parents[1]
TEI = "http://www.tei-c.org/ns/1.0"
MANIFEST = ROOT / "sources/manifest-acquisitions/pg75254-william-derham-1720/source-manifest.json"


class MemoryCandidate:
    def __init__(self, members: dict[str, bytes]):
        self.members = members
        self.sha256 = hashlib.sha256(members["content.tei.xml"]).hexdigest()

    def member_bytes(self, name: str) -> bytes:
        return self.members[name]


def source_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


def reseal_candidate(members: dict[str, bytes]) -> dict[str, bytes]:
    changed = dict(members)
    account = json.loads(changed["source-accountability.json"])
    account["candidate_sha256"] = hashlib.sha256(changed["content.tei.xml"]).hexdigest()
    account["candidate_bytes"] = len(changed["content.tei.xml"])
    changed["source-accountability.json"] = (
        json.dumps(account, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return changed


def mutated_xml(members: dict[str, bytes], selector: str, transform) -> dict[str, bytes]:
    changed = dict(members)
    tree = etree.fromstring(changed["content.tei.xml"], etree.XMLParser(resolve_entities=False, no_network=True))
    node = tree.find(f".//{{{TEI}}}body//{{{TEI}}}{selector}")
    assert node is not None
    transform(node)
    changed["content.tei.xml"] = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    return reseal_candidate(changed)


def test_pg75254_complete_source_mapping_and_meaningful_mutations():
    manifest = source_manifest()
    baseline = dict(producer._convert(manifest))
    report = oracle._oracle(manifest, MemoryCandidate(baseline))
    assert report["status"] == "pass", report["findings"]

    profile = json.loads(manifest.authority_path("profile").read_bytes())
    assert profile["source_features"]["figures"] == 42
    assert profile["source_features"]["figcaptions"] == 1
    assert profile["source_features"]["images"] == 57
    tei = etree.fromstring(baseline["content.tei.xml"])
    assert len(tei.xpath("/*[local-name()='TEI']")) == 1
    assert len(tei.xpath("//tei:figure[@type='source-html-figure']", namespaces={"tei": TEI})) == 42
    assert len(tei.xpath("//tei:figure/tei:figDesc", namespaces={"tei": TEI})) == 1
    assert len(tei.xpath("//tei:milestone[@unit='source-image-reference']", namespaces={"tei": TEI})) == 57
    schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-validation-schema"))))
    assert schema.validate(tei), str(schema.error_log.last_error)

    prose = mutated_xml(baseline, "p", lambda node: setattr(node, "text", (node.text or "") + " [mutated]"))
    assert any("normalized source body text differs" in finding for finding in oracle._oracle(manifest, MemoryCandidate(prose))["findings"])

    heading = mutated_xml(baseline, "head", lambda node: node.set("type", "h6"))
    assert any("heading level, wording, or order differs" in finding for finding in oracle._oracle(manifest, MemoryCandidate(heading))["findings"])

    caption = mutated_xml(baseline, "figDesc", lambda node: setattr(node, "text", (node.text or "") + " altered"))
    assert any("figure caption count, order, or text differs" in finding for finding in oracle._oracle(manifest, MemoryCandidate(caption))["findings"])

    def change_image_reference(node):
        value = node.get("rend") or ""
        node.set("rend", value.replace("source-image-member:", "source-image-member:mutated/", 1))

    image = mutated_xml(baseline, "milestone[@unit='source-image-reference']", change_image_reference)
    assert any("image reference differs" in finding for finding in oracle._oracle(manifest, MemoryCandidate(image))["findings"])

    bad_support = dict(baseline)
    account = json.loads(bad_support["source-accountability.json"])
    account["source_image_references"][0]["sha256"] = "0" * 64
    bad_support["source-accountability.json"] = (json.dumps(account, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    assert any("source image support hash differs" in finding for finding in oracle._oracle(manifest, MemoryCandidate(bad_support))["findings"])

    omitted_member = dict(baseline)
    account = json.loads(omitted_member["source-accountability.json"])
    account["archive_members"] = account["archive_members"][:-1]
    omitted_member["source-accountability.json"] = (json.dumps(account, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    assert any("exact archive and member set" in finding for finding in oracle._oracle(manifest, MemoryCandidate(omitted_member))["findings"])
