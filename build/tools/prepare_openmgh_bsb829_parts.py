"""Prepare separately addressable bsb829 part/letter electronic candidates.

This route does not edit the frozen whole-division bsb829 files or install a
master. Its only text input is the pinned extracted XML, never the ZIP.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.openmgh_bsb829_parts_oracle import check as oracle_check
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.projection.categories.native_documents import (
    project_document, verify_document,
)
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000829/tei/bsb00000829.xml")
SOURCE_SHA = "cb35385e4e4ba87f80a002452a527527866322af7ccea7f23f366735e46df989"
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb829-inspected-batch-20260926.json")
BATCH_SHA = "6623a27ea9998fbd9fad1379eafa3fc6b58d887ad00b8b42b92f5441e86cf947"
RECEIPT = Path("raw/openmgh/bsb00000829/acquisition-receipt.json")
RECEIPT_SHA = "61fdd88b8536cdda2338f9f2e684188c0eae00c0ed8eb827c3187c0b3cdb4f4c"
SIDE_HOME = Path("sources/openmgh-bsb829-parts")
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"existing evidence differs: {path}")
        return
    path.write_bytes(data)


def _locator_pair(work: dict) -> tuple[str, str]:
    editions = [e for f in work["textual_forms"] for e in f["editions"]]
    if len(editions) != 1 or len(editions[0]["acquisition_ids"]) != 1:
        raise ValueError(f"ambiguous edition/acquisition for {work['work_id']}")
    parts = editions[0]["containing_source"]["locator"].split("; ")
    if len(parts) != 2 or any(not p.startswith(SOURCE.as_posix() + "#") for p in parts):
        raise ValueError(f"ambiguous locator pair for {work['work_id']}")
    return parts[0].split("#", 1)[1], parts[1].split("#", 1)[1]


def _source() -> tuple[bytes, etree._Element, list[etree._Element]]:
    for path, digest in ((SOURCE, SOURCE_SHA), (BATCH, BATCH_SHA), (RECEIPT, RECEIPT_SHA)):
        if _sha(ROOT / path) != digest:
            raise ValueError(f"frozen source or receipt changed: {path}")
    data = (ROOT / SOURCE).read_bytes()
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_comments=False, huge_tree=True)
    root = etree.fromstring(data, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("source DOCTYPE is forbidden")
    body = root.find(f"{TEI}text/{TEI}body")
    if body is None or len(body) != 1 or body[0].get("type") != "volume":
        raise ValueError("source volume envelope changed")
    divisions = list(body[0])
    if len(divisions) != 21 or len(divisions[0]) != 17:
        raise ValueError("bsb829 division/part inventory changed")
    return data, root, list(divisions[0])


def _selection(parts: list[etree._Element], first: str, last: str) -> tuple[etree._Element, int, int | None]:
    matches = [node for part in parts for node in part.iter() if node.get(XML_ID) == first]
    ends = [node for part in parts for node in part.iter() if node.get(XML_ID) == last]
    if len(matches) != 1 or len(ends) != 1:
        raise ValueError("declared XML locator is not unique in division 1")
    start, end = matches[0], ends[0]
    def container(node: etree._Element, kind: str) -> etree._Element | None:
        return next((a for a in node.iterancestors()
                     if a.tag == f"{TEI}div" and a.get("type") == kind), None)
    first_section = container(start, "section")
    last_section = container(end, "section")
    if (first_section is not None and last_section is not None
            and first_section is not last_section):
        raise ValueError("locator pair crosses source sections")
    if first_section is not None and first_section is last_section:
        selected = first_section
        part = selected.getparent()
        section_ordinal = list(part).index(selected)
    else:
        first_part = container(start, "part")
        last_part = container(end, "part")
        if first_part is None or first_part is not last_part:
            raise ValueError("locator pair crosses source parts")
        selected = first_part
        part = selected
        section_ordinal = None
    if part not in parts:
        raise ValueError("selected part is not a division-1 child")
    bsb_ids = [node.get(XML_ID) for node in selected.iter()
               if (node.get(XML_ID) or "").startswith("bsb00000829_")]
    if (first not in bsb_ids or bsb_ids[-1] != last
            or bsb_ids.index(first) > 2):
        raise ValueError("locators do not bound complete native container")
    return selected, parts.index(part) + 1, section_ordinal


def _candidate(root: etree._Element, selected: etree._Element, work: dict) -> bytes:
    result = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    result.set(XML_ID, f"ocd-{work['work_id']}-bsb829-parts-electronic-v1")
    header = etree.SubElement(result, f"{TEI}teiHeader")
    file_desc = etree.SubElement(header, f"{TEI}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{TEI}titleStmt")
    etree.SubElement(title_stmt, f"{TEI}title").text = work["title"]
    source_file_desc = root.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if source_file_desc is None:
        raise ValueError("source header missing")
    publication = source_file_desc.find(f"{TEI}publicationStmt")
    bibliography = source_file_desc.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError("source publication/license/bibliography missing")
    file_desc.append(deepcopy(publication))
    source_desc = etree.SubElement(file_desc, f"{TEI}sourceDesc")
    source_desc.append(deepcopy(bibliography))
    body = etree.SubElement(etree.SubElement(result, f"{TEI}text"), f"{TEI}body")
    wrapper = etree.SubElement(body, f"{TEI}div", type="work", n=work["title"])
    wrapper.append(deepcopy(selected))
    return etree.tostring(result, encoding="UTF-8", xml_declaration=True)


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    """Make five package members from one pinned native part or section."""
    source_manifest.verify()
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("contract") != "ocd-openmgh-bsb829-parts-profile-v1":
        raise ValueError("parts profile contract changed")
    source = source_manifest.authority_path("extracted-xml").read_bytes()
    if sha256(source).hexdigest() != profile["source_sha256"]:
        raise ValueError("extracted source changed")
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_comments=False, huge_tree=True)
    root = etree.fromstring(source, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("source DOCTYPE is forbidden")
    body = root.find(f"{TEI}text/{TEI}body")
    if body is None or len(body) != 1 or len(body[0]) != 21:
        raise ValueError("source volume changed")
    parts = list(body[0][0])
    if len(parts) != 17:
        raise ValueError("source parts changed")
    ordinal = profile["source_part_ordinal"]
    section = profile["source_section_ordinal_zero_based"]
    if not isinstance(ordinal, int) or not 1 <= ordinal <= 17:
        raise ValueError("source part ordinal changed")
    selected = parts[ordinal - 1] if section is None else parts[ordinal - 1][section]
    if selected.get("type") != profile["native_type"]:
        raise ValueError("source selected type changed")
    if sha256(etree.tostring(selected, method="c14n", with_comments=True)).hexdigest() != profile["selection_c14n_sha256"]:
        raise ValueError("selected source subtree changed")
    work = json.loads(source_manifest.authority_path("work-sidecar").read_bytes())
    if work.get("work_id") != profile["work_id"] or work.get("title") != profile["work_title"]:
        raise ValueError("work sidecar changed")
    candidate = _candidate(root, selected, work)
    accounting = {
        "contract": "ocd-openmgh-bsb829-parts-accounting-v1",
        "work_id": profile["work_id"], "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"],
        "source_path": profile["source_path"], "source_sha256": profile["source_sha256"],
        "source_division_ordinal": 1, "source_part_ordinal": ordinal,
        "source_section_ordinal_zero_based": section,
        "native_type": profile["native_type"],
        "start_xml_id": profile["start_xml_id"], "end_xml_id": profile["end_xml_id"],
        "selection_c14n_sha256": profile["selection_c14n_sha256"],
        "shared_matter_disposition": profile["shared_matter_disposition"],
        "unassigned_fragment_disposition": profile["unassigned_fragment_disposition"],
        "zip_disposition": "Retained acquisition package only; not text authority.",
    }
    provenance = {
        "contract": "ocd-openmgh-bsb829-parts-provenance-v1", "status": "nonaccepted",
        "work_id": profile["work_id"], "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"],
        "source_path": profile["source_path"], "source_sha256": profile["source_sha256"],
        "canonical_ir_written": False, "publication": "not-ready",
    }
    unresolved = [
        {"status": "unresolved", "item": "Close visual comparison and print collation are not performed."},
        {"status": "unresolved", "item": "Human acceptance, rights clearance, and publication are separate."},
    ]
    readme = (
        f"# {profile['work_title']} — openMGH bsb829 part candidate\n\n"
        f"Text source: {profile['source_path']} (SHA-256 {profile['source_sha256']}).\n"
        f"Division 1, part {ordinal}, {profile['native_type']} selection.\n"
        "The source electronic publication statement and print bibliography are preserved. "
        "Monumenta Germaniae Historica and the Bavarian State Library request derivative attribution. "
        "Rights and publication decisions remain separate.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": candidate,
        "source-accountability.json": _json(accounting),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = "ocd-openmgh-bsb829-parts-to-tei"
_convert.converter_version = "1"


def prepare(destination: Path) -> dict[str, object]:
    destination = destination.resolve()
    if ROOT == destination or ROOT in destination.parents:
        raise ValueError("candidate destination must be outside the repository")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("candidate destination must be fresh")
    source_bytes, root, parts = _source()
    batch = json.loads((ROOT / BATCH).read_bytes())
    held = sorted(work_id for work_id, reason in batch["holds"].items()
                  if reason.startswith("Shared source division 1;"))
    if len(held) != 24:
        raise ValueError("frozen division-1 held identity set changed")
    selections = []
    for work_id in held:
        work_path = ROOT / "library/works" / work_id / "work.json"
        work = json.loads(work_path.read_bytes())
        if work.get("work_id") != work_id:
            raise ValueError("work sidecar identity differs")
        first, last = _locator_pair(work)
        selected, part_ordinal, section_ordinal = _selection(parts, first, last)
        selections.append((work_id, work, work_path, first, last, selected,
                           part_ordinal, section_ordinal))
    selected_nodes = [entry[5] for entry in selections]
    if len({id(node) for node in selected_nodes}) != 24:
        raise ValueError("two works select the same native container")
    if any(a in b.iterancestors() or b in a.iterancestors()
           for i, a in enumerate(selected_nodes) for b in selected_nodes[i + 1:]):
        raise ValueError("selected containers overlap")
    selected_parts = {entry[6] for entry in selections if entry[7] is None}
    if selected_parts != {3, 4, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 17}:
        raise ValueError("whole-part coverage changed")
    for ordinal, expected_sections in ((1, 6), (2, 3), (7, 2)):
        actual = {entry[7] for entry in selections if entry[6] == ordinal}
        if actual != set(range(1, expected_sections + 1)):
            raise ValueError(f"letter section coverage changed in part {ordinal}")
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    for work_id, work, work_path, first, last, selected, part_ordinal, section_ordinal in selections:
        scope_type = selected.get("type")
        candidate = _candidate(root, selected, work)
        oracle = oracle_check(source_bytes, candidate, first_id=first,
                              last_id=last, selected_type=scope_type,
                              part_ordinal=part_ordinal, section_ordinal=section_ordinal)
        path = destination / work_id / "candidate.tei.xml"
        _write_once(path, candidate)
        errors = validate_file(path)
        if errors:
            raise ValueError(f"TEI P5 XSD failure for {work_id}: {errors[:3]}")
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        public_identity = {
            "work_id": work_id,
            "textual_form_id": form["textual_form_id"],
            "edition_id": edition["edition_id"],
        }
        revision = f"{work_id}-bsb829-parts-v1"
        projection = project_document(
            path, identity=public_identity, language="la",
            representation_revision=revision, edition_title=edition["title"],
            _allow_acceptance_metadata=True, category="prose",
        )
        projection_errors = verify_document(
            path, projection["rows"], projection["receipt"],
            identity=public_identity, language="la", representation_revision=revision,
            edition_title=edition["title"], _allow_acceptance_metadata=True,
            category="prose",
        )
        if len(projection["rows"]) != 1 or projection_errors:
            raise ValueError(f"native prose projection failed for {work_id}: {projection_errors[:3]}")
        shared = ("The parent part's preceding shared heading remains in the retained XML; "
                  "its title context is represented by this work's header title."
                  if scope_type == "section" else
                  "The complete part, including its title, is copied; sibling parts remain in the retained XML.")
        boundary = {
            "contract": "ocd-openmgh-bsb829-parts-boundary-v1", "work_id": work_id,
            "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
            "source_division_ordinal": 1, "source_part_ordinal": part_ordinal,
            "source_section_ordinal_zero_based": section_ordinal,
            "native_type": scope_type, "start_xml_id": first, "end_xml_id": last,
            "selection_c14n_sha256": oracle["selection_c14n_sha256"],
            "shared_matter_disposition": shared,
            "unassigned_fragment_disposition": "Part 13 is a separately labeled fragment outside all 24 declared work identities; it remains in the retained source and is held.",
            "other_divisions_disposition": "The volume shell and 20 other work divisions remain in the retained extracted XML.",
            "zip_disposition": "Retained acquisition package only; not text authority.",
            "opening": " ".join(" ".join(selected.itertext()).split())[:120],
            "closing": " ".join(" ".join(selected.itertext()).split())[-120:],
        }
        sidecar = ROOT / SIDE_HOME / work_id / "boundary-review.json"
        _write_once(sidecar, _json(boundary))
        results.append({
            "work_id": work_id, "work_sidecar_path": work_path.relative_to(ROOT).as_posix(),
            "work_sidecar_sha256": _sha(work_path),
            "boundary_path": sidecar.relative_to(ROOT).as_posix(),
            "boundary_sha256": _sha(sidecar), "candidate_path": path.as_posix(),
            "candidate_sha256": sha256(candidate).hexdigest(), "oracle": oracle,
            "xsd_status": "pass", "part_ordinal": part_ordinal,
            "native_prose_projection_rows": 1,
            "native_prose_independent_check": "pass",
            "section_ordinal_zero_based": section_ordinal,
        })
    receipt = {
        "contract": "ocd-openmgh-bsb829-parts-candidates-v1", "status": "nonaccepted",
        "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
        "frozen_inspection_receipt": BATCH.as_posix(), "frozen_inspection_receipt_sha256": BATCH_SHA,
        "acquisition_receipt": RECEIPT.as_posix(), "acquisition_receipt_sha256": RECEIPT_SHA,
        "candidates": results, "held_unassigned_source_part": 13,
        "acceptance_stage": "not-prepared", "canonical_install": "not-performed",
    }
    _write_once(destination / "receipt.json", _json(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    receipt = prepare(args.destination)
    print(json.dumps({"candidate_count": len(receipt["candidates"]),
                      "receipt": str(args.destination / "receipt.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
