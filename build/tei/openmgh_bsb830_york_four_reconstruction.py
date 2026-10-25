"""Faithful TEI for the whole retained fourth York electronic tractate."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _select(source: bytes, profile: dict) -> tuple[etree._Element, etree._Element]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False,
                             huge_tree=True)
    root = etree.fromstring(source, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("source DOCTYPE is forbidden")
    body = root.find(f"{TEI}text/{TEI}body")
    if body is None or len(body) != 1 or body[0].get("type") != "volume":
        raise ValueError("bsb830 volume envelope changed")
    works = list(body[0])
    if len(works) != 29 or works[21].get("n") != "Tract. Eboracenses":
        raise ValueError("York fourth parent work division changed")
    parent = works[21]
    parts = list(parent)
    ordinal = profile["source_part_ordinal"]
    if (len(parts) != 7 or ordinal != 4
            or parts[0].tag != f"{TEI}ab"
            or any(part.tag != f"{TEI}div" or part.get("type") != "part" for part in parts[1:])):
        raise ValueError("York fourth part inventory changed")
    selected = parts[ordinal]
    if _sha(etree.tostring(selected, method="c14n", with_comments=True)) != profile["selection_c14n_sha256"]:
        raise ValueError("selected York fourth part changed")
    ids = [node.get(XML_ID) for node in selected.iter() if (node.get(XML_ID) or "").startswith("bsb00000830_")]
    if (not ids or ids[0] != profile["start_xml_id"]
            or ids[-1] != profile["end_xml_id"]):
        raise ValueError("York fourth part locator boundaries changed")
    return root, selected


def _candidate(root: etree._Element, selected: etree._Element, profile: dict) -> bytes:
    result = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    result.set(XML_ID, f"ocd-{profile['work_id']}-bsb830-york-four-electronic-v1")
    header = etree.SubElement(result, f"{TEI}teiHeader")
    file_desc = etree.SubElement(header, f"{TEI}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{TEI}titleStmt")
    etree.SubElement(title_stmt, f"{TEI}title").text = profile["work_title"]
    source_file = root.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if source_file is None:
        raise ValueError("source header missing")
    publication = source_file.find(f"{TEI}publicationStmt")
    bibliography = source_file.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError("source electronic publication or print bibliography missing")
    file_desc.append(deepcopy(publication))
    notes = etree.SubElement(file_desc, f"{TEI}notesStmt")
    etree.SubElement(notes, f"{TEI}note").text = profile["source_breakoff"]
    source_desc = etree.SubElement(file_desc, f"{TEI}sourceDesc")
    source_desc.append(deepcopy(bibliography))
    body = etree.SubElement(etree.SubElement(result, f"{TEI}text"), f"{TEI}body")
    wrapper = etree.SubElement(body, f"{TEI}div", type="work", n=profile["work_title"])
    wrapper.append(deepcopy(selected))
    return etree.tostring(result, encoding="UTF-8", xml_declaration=True)


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("contract") != "ocd-openmgh-bsb830-york-four-profile-v1":
        raise ValueError("York fourth profile contract changed")
    source = source_manifest.authority_path("extracted-xml").read_bytes()
    if _sha(source) != profile["source_sha256"]:
        raise ValueError("retained extracted XML changed")
    root, selected = _select(source, profile)
    work = json.loads(source_manifest.authority_path("work-sidecar").read_bytes())
    if work.get("work_id") != profile["work_id"] or work.get("title") != profile["work_title"]:
        raise ValueError("installed work identity changed")
    boundary = json.loads(source_manifest.authority_path("boundary-review").read_bytes())
    accounting = {
        "contract": "ocd-openmgh-bsb830-york-four-accounting-v1",
        "work_id": profile["work_id"], "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"], "source_path": profile["source_path"],
        "source_sha256": _sha(source), "source_division_ordinal": 22,
        "source_part_ordinal": profile["source_part_ordinal"], "native_type": "part",
        "start_xml_id": profile["start_xml_id"], "end_xml_id": profile["end_xml_id"],
        "catalog_start_xml_id": profile["catalog_start_xml_id"],
        "catalog_end_xml_id": profile["catalog_end_xml_id"],
        "selection_c14n_sha256": profile["selection_c14n_sha256"],
        "shared_matter_disposition": boundary["shared_matter_disposition"],
        "unassigned_fragment_disposition": boundary["unassigned_fragment_disposition"],
        "source_breakoff": profile["source_breakoff"],
        "volume_inventory": boundary["volume_inventory"],
        "york_inventory": boundary["york_inventory"],
        "zip_disposition": "Retained acquisition package only; not text authority.",
    }
    provenance = {
        "contract": "ocd-openmgh-bsb830-york-four-provenance-v1", "status": "nonaccepted",
        "work_id": profile["work_id"], "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"], "source_path": profile["source_path"],
        "source_sha256": _sha(source), "canonical_ir_written": False,
        "publication": "not-ready",
    }
    unresolved = [
        {"status": "unresolved", "item": profile["source_breakoff"]},
        {"status": "unresolved", "item": "Close visual comparison and print collation are not performed."},
        {"status": "unresolved", "item": "Human acceptance, rights clearance, and publication are separate."},
    ]
    readme = (
        f"# {profile['work_title']} — openMGH York fourth part candidate\n\n"
        f"Exact extracted text source: {profile['source_path']} (SHA-256 {profile['source_sha256']}).\n"
        f"Volume work division 22 of 29, complete retained native tractate {profile['source_part_ordinal']} of 6. "
        "The shared collection heading and all sibling tractates remain in the retained source outside this candidate. "
        f"{profile['source_breakoff']} "
        "The electronic publication statement and print bibliography are preserved. "
        "Monumenta Germaniae Historica and the Bavarian State Library request derivative attribution. "
        "Rights and publication decisions remain separate.\n"
    ).encode()
    return {
        "content.tei.xml": _candidate(root, selected, profile),
        "source-accountability.json": _json(accounting),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": b"".join(_json(x) for x in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = "ocd-openmgh-bsb830-york-four-part-to-tei"
_convert.converter_version = "1"
