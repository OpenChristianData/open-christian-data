"""Prepare two complete bsb830 Gerhoh nested prose parts as nonaccepted candidates."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.openmgh_bsb830_gerhoh_nested_pair_oracle import check
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml")
SOURCE_SHA = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
PACKAGE = Path("raw/openmgh/bsb00000830/bsb00000830.zip")
PACKAGE_SHA = "3cc84719875aec1c7a3bceb9cb754f55d191705bce73f628f93135bad6e8f1e5"
ACQUISITION_RECEIPT = Path("raw/openmgh/bsb00000830/acquisition-receipt.json")
ACQUISITION_RECEIPT_SHA = "6937a8c05fc2c094ae1b9ab57f34fe639e77972877976474ba2513de0d8b885c"
CONTRACT = "ocd-openmgh-bsb830-gerhoh-nested-pair-direct-v1"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SELECTIONS = {
    "gerhoh-de-edificio-dei": (6, (0,)),
    "gerhoh-de-investigatione-antichristi": (6, (6,)),
}
HELD_PARTS = {1, 2, 3, 4, 5, 7, 8, 9, 10}


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _source() -> tuple[bytes, etree._Element, list[etree._Element]]:
    for relative, digest in ((SOURCE, SOURCE_SHA), (PACKAGE, PACKAGE_SHA),
                             (ACQUISITION_RECEIPT, ACQUISITION_RECEIPT_SHA)):
        if _sha(ROOT / relative) != digest:
            raise ValueError(f"bsb830 source/package/receipt changed: {relative}")
    content = _io_path(ROOT / SOURCE).read_bytes()
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True,
                                                      remove_comments=False, huge_tree=True))
    if root.getroottree().docinfo.doctype:
        raise ValueError("bsb830 source DOCTYPE is forbidden")
    volumes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces={"t": TEI[1:-1]})
    if len(volumes) != 1 or len(volumes[0]) != 29:
        raise ValueError("bsb830 volume division count differs")
    works = list(volumes[0])
    if any(node.tag != f"{TEI}div" or node.get("type") != "work" for node in works):
        raise ValueError("bsb830 volume has unaccounted direct matter")
    if works[6].get("n") != "Gerhohi praepos. Reichersb. libelli sel." or len(works[6]) != 11:
        raise ValueError("bsb830 selected carrier part count differs")
    if any(node.tag != f"{TEI}div" or node.get("type") != "part" for node in works[6]):
        raise ValueError("bsb830 Gerhoh carrier has nonpart matter")
    return content, root, works


def _candidate(root: etree._Element, selected: list[etree._Element], work: dict) -> bytes:
    result = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    result.set(XML_ID, f"ocd-{work['work_id']}-bsb830-gerhoh-electronic-v1")
    file_desc = etree.SubElement(etree.SubElement(result, f"{TEI}teiHeader"), f"{TEI}fileDesc")
    etree.SubElement(etree.SubElement(file_desc, f"{TEI}titleStmt"), f"{TEI}title").text = work["title"]
    original = root.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original is None:
        raise ValueError("bsb830 source header missing")
    publication = original.find(f"{TEI}publicationStmt")
    bibliography = original.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError("bsb830 source publication/bibliography missing")
    file_desc.append(deepcopy(publication))
    etree.SubElement(file_desc, f"{TEI}sourceDesc").append(deepcopy(bibliography))
    wrapper = etree.SubElement(etree.SubElement(etree.SubElement(result, f"{TEI}text"), f"{TEI}body"),
                               f"{TEI}div", type="work", n=work["title"])
    for part in selected:
        wrapper.append(deepcopy(part))
    return etree.tostring(result, encoding="UTF-8", xml_declaration=True)


def prepare(destination: Path) -> dict:
    destination = destination.absolute()
    if _io_path(destination).exists() or not _io_path(destination.parent).is_dir() or ROOT in destination.parents:
        raise ValueError("fresh external bsb830 direct destination required")
    source_bytes, root, works = _source()
    selected = {(index, part) for index, ordinals in SELECTIONS.values() for part in ordinals}
    if ({part for index, part in selected if index == 6} | HELD_PARTS != set(range(11))
            or selected & {(6, part) for part in HELD_PARTS}
            or any(index != 6 for index, _part in selected)):
        raise ValueError("bsb830 eleven-part carrier partition differs")
    prepared = []
    for work_id, (index, ordinals) in SELECTIONS.items():
        work_path = Path("library/works") / work_id / "work.json"
        work = _read(ROOT / work_path)
        forms = work.get("textual_forms", [])
        if work.get("work_id") != work_id or len(forms) != 1 or len(forms[0].get("editions", [])) != 1:
            raise ValueError(f"bsb830 work/edition identity differs: {work_id}")
        form, edition = forms[0], forms[0]["editions"][0]
        if len(edition.get("acquisition_ids", [])) != 1:
            raise ValueError(f"bsb830 acquisition identity differs: {work_id}")
        acquisition_path = (work_path.parent / "forms" / form["textual_form_id"] / "editions" /
                            edition["edition_id"] / "acquisitions" / f"{edition['acquisition_ids'][0]}.json")
        acquisition = _read(ROOT / acquisition_path)
        retained = acquisition.get("retained_files", [])
        if (acquisition.get("source_path") != SOURCE.as_posix()
                or acquisition.get("source_sha256") != SOURCE_SHA or len(retained) != 2
                or {entry["path"] for entry in retained} != {SOURCE.as_posix(), PACKAGE.as_posix()}):
            raise ValueError(f"bsb830 XML/package acquisition binding differs: {work_id}")
        state = _read(ROOT / work_path.parent / "state.json")
        if len([item for item in state["targets"] if item["target_type"] == "edition"
                and item["target_id"] == edition["edition_id"] and item["stage"] == "acquired"]) != 1:
            raise ValueError(f"bsb830 edition not uniquely acquired: {work_id}")
        candidate = _candidate(root, [works[index][ordinal] for ordinal in ordinals], work)
        oracle = check(source_bytes, candidate, work, acquisition)
        prepared.append((work_id, index, ordinals, work_path, acquisition_path, work, candidate, oracle))
    _io_path(destination).mkdir(parents=True)
    results = []
    for work_id, index, ordinals, work_path, acquisition_path, work, candidate, oracle in prepared:
        candidate_path = destination / work_id / "candidate.tei.xml"
        _io_path(candidate_path).parent.mkdir(parents=True)
        _io_path(candidate_path).write_bytes(candidate)
        if errors := validate_file(_io_path(candidate_path)):
            raise ValueError(f"bsb830 P5 failed for {work_id}: {errors[:3]}")
        form, edition = work["textual_forms"][0], work["textual_forms"][0]["editions"][0]
        identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                    "edition_id": edition["edition_id"]}
        revision = f"{work_id}-bsb830-prose-v1"
        projected = project_document(_io_path(candidate_path), identity=identity, language="la",
                                     representation_revision=revision, edition_title=edition["title"],
                                     _allow_acceptance_metadata=True, category="prose")
        errors = verify_document(_io_path(candidate_path), projected["rows"], projected["receipt"],
                                 identity=identity, language="la", representation_revision=revision,
                                 edition_title=edition["title"], _allow_acceptance_metadata=True,
                                 category="prose")
        if errors or len(projected["rows"]) != 1:
            raise ValueError(f"bsb830 native prose failed for {work_id}: {errors[:3]}")
        results.append({
            "work_id": work_id, "source_work_div_index": index, "source_part_indexes": list(ordinals),
            "source_work_div_n": works[index].get("n"), "candidate_path": candidate_path.as_posix(),
            "candidate_sha256": sha256(candidate).hexdigest(), "work_path": work_path.as_posix(),
            "work_sha256": _sha(ROOT / work_path), "acquisition_path": acquisition_path.as_posix(),
            "acquisition_sha256": _sha(ROOT / acquisition_path), "oracle": oracle,
            "tei_xsd": "pass", "native_prose_rows": 1, "native_verify": "pass",
        })
    receipt = {
        "contract": CONTRACT, "status": "nonaccepted", "source_path": SOURCE.as_posix(),
        "source_sha256": SOURCE_SHA, "source_bytes": len(source_bytes),
        "package_path": PACKAGE.as_posix(), "package_sha256": PACKAGE_SHA,
        "acquisition_receipt_path": ACQUISITION_RECEIPT.as_posix(),
        "acquisition_receipt_sha256": ACQUISITION_RECEIPT_SHA,
        "selected_part_count": 2, "selected_works": results,
        "held_parts": [{"source_work_div_index": 6, "source_part_index": part,
                        "reason": "Outside the two nested Gerhoh part batch; simple, larger nested, or different catalog ownership requires separate review."}
                       for part in sorted(HELD_PARTS)],
        "other_source_divisions": [{"index": i, "literal_n": node.get("n"), "disposition": "outside batch"}
                                   for i, node in enumerate(works) if i != 6],
        "canonical_install": "not-performed",
    }
    _io_path(destination / "receipt.json").write_bytes(_json(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    result = prepare(parser.parse_args().destination)
    print(json.dumps({"works": len(result["selected_works"]), "status": result["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
