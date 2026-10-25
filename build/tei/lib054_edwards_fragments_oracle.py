"""Source-first enclosing-volume checker for the two Edwards extracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei.lib054_work_local_oracle import _verify as verify_fragment
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

TEI_NS = "http://www.tei-c.org/ns/1.0"
ORACLE_ID = "ocd-lib054-edwards-enclosing-volume-oracle"
ORACLE_VERSION = "1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _import_closure_sha256(root: Path) -> str:
    paths = [
        "build/tei/lib054_edwards_fragments_oracle.py",
        "build/tei/lib054_work_local_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
        "ocd_kernel/tei/validate.py",
    ]
    return _sha(_json([{"path": path, "sha256": _sha((root / path).read_bytes())} for path in paths]))


def _parse(data: bytes) -> etree._Element:
    return etree.fromstring(data, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True,
        remove_comments=False, huge_tree=True,
    ))


def _verify(manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    facts = verify_fragment(manifest, candidate)
    by_role: dict[str, list[dict[str, object]]] = {}
    for authority in manifest.record["authorities"]:
        by_role.setdefault(str(authority["role"]), []).append(authority)
    if len(by_role.get("primary-source", [])) != 1 or len(by_role.get("enclosing-volume", [])) != 1:
        raise ValueError("Edwards source and enclosing volume bindings are not unique")
    source_binding = by_role["primary-source"][0]
    volume_binding = by_role["enclosing-volume"][0]
    source = _parse(manifest.authority_path(str(source_binding["name"])).read_bytes())
    volume_bytes = manifest.authority_path(str(volume_binding["name"])).read_bytes()
    volume = _parse(volume_bytes)
    if (source.tag != "ThML" or len(source) != 1 or source[0].tag != "ThML.body"
            or len(source[0]) != 1 or source[0][0].tag != "div1"
            or volume.tag != "ThML" or len(volume.findall("ThML.head")) != 1
            or len(volume.findall("ThML.body")) != 1):
        raise ValueError("Edwards source or volume envelope changed")
    body = volume.find("ThML.body")
    assert body is not None
    if len(body) < 3 or any(child.tag != "div1" for child in body):
        raise ValueError("enclosing volume work inventory changed")
    source_division = source[0][0]
    exact = etree.tostring(source_division, encoding="UTF-8", with_tail=False)
    hits = [position for position, child in enumerate(body)
            if etree.tostring(child, encoding="UTF-8", with_tail=False) == exact]
    if len(hits) != 1 or hits[0] in (0, len(body) - 1):
        raise ValueError("extracted work division is not unique in enclosing volume")
    position = hits[0]
    if body[-1].get("title") != "Indexes" or body[0].get("id") != "i":
        raise ValueError("collection opening or index ownership changed")
    title = volume.findtext(".//ThML.head//DC.Title")
    if not title:
        raise ValueError("enclosing volume title is missing")
    ids = {node.get("id") for node in body[position].iter() if node.get("id")}
    backlinks = 0
    for link in body[-1].iter("a"):
        href = link.get("href", "")
        if "#" in href and href.rsplit("#", 1)[1] in ids:
            backlinks += 1
    for child in body[1:-1]:
        if child is body[position]:
            continue
        for link in child.iter("a"):
            href = link.get("href", "")
            if "#" in href and href.rsplit("#", 1)[1] in ids:
                raise ValueError("unaccounted sibling-to-work link")
    expected = {
        "path": volume_binding["path"], "sha256": _sha(volume_bytes),
        "title": title, "body_child_position": position + 1,
        "body_child_count": len(body), "source_division_id": source_division.get("id"),
        "source_division_xml_sha256": _sha(exact),
        "opening_matter_id": body[0].get("id"), "index_id": body[-1].get("id"),
        "index_backlinks_to_work": backlinks,
    }
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if accounting.get("enclosing_volume") != expected or provenance.get("enclosing_volume") != expected:
        raise ValueError("enclosing-volume extraction accounting differs")
    if provenance.get("extraction_provenance") != "exact-complete-enclosing-volume-div1":
        raise ValueError("enclosing-volume provenance is not established")
    tei = _parse(candidate.member_bytes("content.tei.xml"))
    notes = tei.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:note[@type='extracted-fragment']",
                      namespaces={"t": TEI_NS})
    expected_note = (f"Exact complete div1 {source_division.get('id')} of {volume_binding['path']} "
                     f"({title}); source child {position + 1} of {len(body)}. "
                     "Volume opening matter and final indexes remain collection-owned siblings.")
    if len(notes) != 1 or notes[0].text != expected_note:
        raise ValueError("TEI extraction provenance differs from enclosing volume")
    return facts | {"enclosing_volume_sha256": _sha(volume_bytes),
                    "body_child_position": position + 1,
                    "index_backlinks_to_work": backlinks}


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    _verify(manifest, candidate)
    root = manifest.repository_root
    primary = [item for item in manifest.record["authorities"] if item["role"] == "primary-source"][0]
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=_import_closure_sha256(root),
        source_sha256=str(primary["sha256"]),
        profile_sha256=_sha(manifest.authority_path("reconstruction-profile").read_bytes()),
        package_schema_sha256=_sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        xsd_sha256=_sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(manifest.authority_path("validation-policy").read_bytes()),
        findings=(),
    )
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
