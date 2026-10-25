"""Independent source-aware checker for the current reviewed-header ASV TEI."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree
from build.tei.asv_oracle import check_content as _check_base_content
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

_NS = "http://www.tei-c.org/ns/1.0"
_XML = "http://www.w3.org/XML/1998/namespace"
_SCOPE = "complete retained ASV JSON electronic witness; no claim to complete physical 1901 print"
_REVISION = {"id": "asv-reviewed-header-v1", "date": "2026-09-24", "note": "Acceptance identity and retained JSON source bindings added; original TEI text bytes are unchanged."}
_DESCRIPTION = "Complete retained JSON witness: raw/bible_databases/formats/json/ASV.json. The provider label is preserved; a complete physical 1901 edition is not asserted."


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _closure_digest() -> str:
    root = Path(__file__).resolve().parents[2]
    members = [
        "ocd_kernel/__init__.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
        "build/tei/asv_oracle.py",
    ]
    return _digest(_canonical({name: _digest((root / name).read_bytes()) for name in members}))


def _json_no_duplicates(data: bytes, label: str):
    def pairs(values):
        names = [key for key, _ in values]
        if len(names) != len(set(names)):
            raise ValueError(f"ASV duplicate JSON key in {label}")
        return dict(values)
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs)


def _expected_base_header(source) -> bytes:
    translation = etree.Element(f"{{{_NS}}}TEI", nsmap={None: _NS}, attrib={f"{{{_XML}}}id": "asv"})
    header = etree.SubElement(translation, f"{{{_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_NS}}}titleStmt")
    title = etree.SubElement(title_stmt, f"{{{_NS}}}title", attrib={f"{{{_XML}}}id": "asv-title"})
    title.text = source["translation"]
    pub = etree.SubElement(etree.SubElement(file_desc, f"{{{_NS}}}publicationStmt"), f"{{{_NS}}}p")
    pub.text = "Nonaccepted reconstruction for review; publication is not authorized."
    desc = etree.SubElement(etree.SubElement(file_desc, f"{{{_NS}}}sourceDesc"), f"{{{_NS}}}p")
    desc.text = _DESCRIPTION
    serialized = etree.tostring(translation, encoding="utf-8", xml_declaration=True, with_tail=False)
    return serialized.rsplit(b"</TEI>", 1)[0]


def _verify_header(tei_bytes: bytes, source, manifest) -> None:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    root = etree.fromstring(tei_bytes, parser)
    q = lambda name: f"{{{_NS}}}{name}"
    if root.tag != q("TEI") or dict(root.attrib) != {f"{{{_XML}}}id": "asv"} or [child.tag for child in root] != [q("teiHeader"), q("text")]:
        raise ValueError("ASV reviewed-header TEI root topology or identity differs")
    header = root[0]
    if [child.tag for child in header] != [q("fileDesc"), q("revisionDesc")]:
        raise ValueError("ASV reviewed header has unexpected header divisions")
    file_desc = header[0]
    if [child.tag for child in file_desc] != [q("titleStmt"), q("publicationStmt"), q("sourceDesc")]:
        raise ValueError("ASV reviewed header file description order differs")
    title_stmt, publication, source_desc = file_desc
    if len(title_stmt) != 1 or title_stmt[0].tag != q("title") or dict(title_stmt[0].attrib) != {f"{{{_XML}}}id": "asv-title"} or title_stmt[0].text != source["translation"] or len(title_stmt[0]):
        raise ValueError("ASV title identity differs from retained JSON")
    if len(publication) != 1 or publication[0].tag != q("p") or publication[0].text != "Nonaccepted reconstruction for review; publication is not authorized." or len(publication[0]):
        raise ValueError("ASV publication header text differs")
    if len(source_desc) != 1 or source_desc[0].tag != q("bibl") or dict(source_desc[0].attrib):
        raise ValueError("ASV source description is not one bound bibliography record")
    bibl = source_desc[0]
    source_authority = next(item for item in manifest.record["authorities"] if item["name"] == "asv-source")
    acquisition = _json_no_duplicates(manifest.authority_path("asv-acquisition").read_bytes(), "acquisition")
    expected = [
        ("note", {"type": "historical-source-description"}, _DESCRIPTION),
        ("ptr", {"target": acquisition["url"]}, None),
        ("idno", {"type": "work_id"}, "asv"),
        ("idno", {"type": "textual_form_id"}, "english-asv"),
        ("idno", {"type": "edition_id"}, "retained-json"),
        ("idno", {"type": "acquisition_id"}, "scrollmapper-retained-json"),
        ("idno", {"type": "source_sha256"}, source_authority["sha256"]),
        ("idno", {"type": "source_bytes"}, str(source_authority["bytes"])),
        ("idno", {"type": "representation_revision"}, _REVISION["id"]),
        ("idno", {"type": "sha256"}, source_authority["sha256"]),
        ("note", {"type": "source-location"}, source_authority["path"]),
        ("note", {"type": "source-scope"}, _SCOPE),
    ]
    if len(bibl) != len(expected):
        raise ValueError("ASV source bibliography binding count differs")
    for node, (tag, attrs, text) in zip(bibl, expected, strict=True):
        if node.tag != q(tag) or dict(node.attrib) != attrs or node.text != text or len(node):
            raise ValueError(f"ASV source bibliography binding differs at {tag} {attrs}")
    rev = header[1]
    if len(rev) != 1 or rev[0].tag != q("change") or dict(rev[0].attrib) != {f"{{{_XML}}}id": _REVISION["id"], "when": _REVISION["date"]} or rev[0].text != _REVISION["note"] or len(rev[0]):
        raise ValueError("ASV representation revision header differs")
    if any(node.tail is not None and node.tail.strip() for node in root.iter() if isinstance(node.tag, str)):
        raise ValueError("ASV reviewed TEI contains unexpected tail text")


def _verify_context(manifest) -> None:
    work = _json_no_duplicates(manifest.authority_path("asv-work").read_bytes(), "work")
    acquisition = _json_no_duplicates(manifest.authority_path("asv-acquisition").read_bytes(), "acquisition")
    expected_source = next(item for item in manifest.record["authorities"] if item["name"] == "asv-source")
    edition = acquisition["retained_files"]
    if work.get("work_id") != "asv" or work.get("title") != "ASV: American Standard Version (1901)":
        raise ValueError("ASV work sidecar identity differs")
    form = work["textual_forms"][0]
    selected = form["editions"][0]
    if form.get("textual_form_id") != "english-asv" or selected.get("edition_id") != "retained-json" or "scrollmapper-retained-json" not in selected.get("acquisition_ids", []):
        raise ValueError("ASV form/edition sidecar identity differs")
    if acquisition.get("acquisition_id") != "scrollmapper-retained-json" or acquisition.get("edition_id") != "retained-json" or len(edition) != 1 or any(edition[0].get(key) != value for key, value in (("path", expected_source["path"]), ("bytes", expected_source["bytes"]), ("sha256", expected_source["sha256"]))):
        raise ValueError("ASV acquisition sidecar does not bind the primary source")
    worklist = manifest.authority_path("asv-current-worklist").read_text(encoding="utf-8")
    rows = [line for line in worklist.splitlines() if "**L223**" in line]
    if len(rows) != 1 or "American Standard Version (ASV)" not in rows[0] or "ASV.json" not in rows[0] or "31,086 verses" not in rows[0]:
        raise ValueError("Bound current Workspace L223 row is absent or changed")
    research = manifest.authority_path("asv-current-research-manifest").read_text(encoding="utf-8")
    rows = [line for line in research.splitlines() if line.startswith("| American Standard Version (ASV) |")]
    if len(rows) != 1 or "ASV.json" not in rows[0] or "ASV 1901" not in rows[0]:
        raise ValueError("Bound current Workspace ASV manifest row is absent or changed")


def oracle(manifest, candidate):
    manifest.verify()
    candidate.verify_integrity()
    source_bytes = manifest.authority_path("asv-source").read_bytes()
    tei_bytes = candidate.member_bytes("content.tei.xml")
    source = _json_no_duplicates(source_bytes, "source")
    _verify_context(manifest)
    _verify_header(tei_bytes, source, manifest)
    marker = b"</teiHeader>"
    if tei_bytes.count(marker) != 1:
        raise ValueError("ASV candidate does not contain one header boundary")
    normalized = _expected_base_header(source) + tei_bytes.split(marker, 1)[1]
    _check_base_content(source_bytes, normalized, candidate.member_bytes("source-accountability.json"))
    schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
    schema.assertValid(etree.fromstring(tei_bytes, etree.XMLParser(resolve_entities=False, no_network=True)))
    for member, authority in (("README.source.md", "asv-readme"), ("unresolved.jsonl", "asv-unresolved")):
        if candidate.member_bytes(member) != manifest.authority_path(authority).read_bytes():
            raise ValueError(f"ASV supporting member drift: {member}")
    bindings = {item["name"]: item["sha256"] for item in manifest.record["authorities"]}
    expected_provenance = {"source_manifest_sha256": manifest.sha256, "authorities": bindings, "converter": dict(manifest.record["converter"]), "scope": "complete retained ASV JSON; no complete-print-edition claim"}
    if _json_no_duplicates(candidate.member_bytes("provenance.json"), "provenance") != expected_provenance:
        raise ValueError("ASV provenance does not bind current source manifest authorities")
    facts = MechanicalFacts(_digest(Path(__file__).read_bytes()), _closure_digest(), _digest(source_bytes), bindings["asv-profile"], bindings["candidate-package-schema"], bindings["tei-p5-xsd"], bindings["asv-policy"], ())
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


oracle.oracle_id = "ocd-lib223-asv-reviewed-header-independent-oracle"
oracle.oracle_version = "2"
