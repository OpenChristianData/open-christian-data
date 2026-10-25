"""Prepare the eleven exclusive complete bsb751 nested-part candidates."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tools.inventory_openmgh_exact_sources import inventory
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000751/tei/bsb00000751.xml")
SOURCE_SHA = "a33fd966810db4657f4e03ceb94431615e8d24c2a3bbd183d9a9dc287cd88d8b"
PACKAGE = Path("raw/openmgh/bsb00000751/bsb00000751.zip")
PACKAGE_SHA = "e4b5e24b38733009acb72ee248336b09c9d1b80e38303c008317b171a3200a87"
ACQUISITION_RECEIPT = Path("raw/openmgh/bsb00000751/acquisition-receipt.json")
ACQUISITION_RECEIPT_SHA = "e020efcab75e595ca059aeb6b83f303abbcf2ba646c8a2807ec1d5d0d6656b50"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CONTRACT = "ocd-openmgh-bsb751-exclusive-nested-parts-v1"
SELECTIONS = {
    "vita-sancti-austrigisili": (3, (0,)),
    "miracula-sancti-austrigisili": (3, (1,)),
    "vita-sancti-amati": (4, (0,)),
    "vita-sancti-romarici": (4, (1,)),
    "vita-sancti-adelphi": (4, (2,)),
    "vita-sancti-fursei": (11, (0,)),
    "virtutes-sancti-fursei": (11, (1,)),
    "vita-sancti-eligii-dadonis": (17, (0, 1, 2, 3)),
    "epistola-dadonis-ad-rodobertum": (17, (4,)),
    "rescriptum-rodoberti-ad-dadonem": (17, (5,)),
}
HELD_PARTS = {
    (11, 2): "Source-labeled Additamentum Nivialense de Fuilano has no separately established current work/edition identity in this batch.",
    (17, 6): "Alterius manu conscripta Vita Eligii, liber III, is a separate source-labeled textual version; catalog edition/variant ownership remains unresolved.",
    (17, 7): "Final separate Eligius source part has no safely established work/edition ownership in this batch.",
}


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _source() -> tuple[bytes, etree._Element, list[etree._Element]]:
    for path, expected in ((SOURCE, SOURCE_SHA), (PACKAGE, PACKAGE_SHA), (ACQUISITION_RECEIPT, ACQUISITION_RECEIPT_SHA)):
        if _sha(ROOT / path) != expected:
            raise ValueError(f"bsb751 source/package/receipt pin changed: {path}")
    content = _io_path(ROOT / SOURCE).read_bytes()
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    if root.getroottree().docinfo.doctype:
        raise ValueError("bsb751 source DOCTYPE is forbidden")
    volume = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces={"t": TEI[1:-1]})
    if len(volume) != 1 or len(volume[0]) != 18:
        raise ValueError("bsb751 source volume direct division count changed")
    works = [item for item in volume[0] if item.tag == f"{TEI}div" and item.get("type") == "work"]
    if len(works) != 18 or any(item not in volume[0] for item in works):
        raise ValueError("bsb751 source top-level interstitial matter changed")
    expected_carriers = {3: 2, 4: 3, 11: 3, 17: 8}
    if {index: len(works[index]) for index in expected_carriers} != expected_carriers:
        raise ValueError("bsb751 shared-carrier part census changed")
    for index, count in expected_carriers.items():
        if any(item.tag != f"{TEI}div" or item.get("type") != "part" for item in works[index]):
            raise ValueError(f"bsb751 carrier {index} has nonpart shared matter")
    return content, root, works


def _c14n(element: etree._Element) -> str:
    detached = deepcopy(element)
    etree.cleanup_namespaces(detached)
    return sha256(etree.tostring(detached, method="c14n", with_comments=True)).hexdigest()


def _candidate(root: etree._Element, selected: list[etree._Element], work: dict) -> bytes:
    result = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    result.set(XML_ID, f"ocd-{work['work_id']}-bsb751-nested-electronic-v1")
    file_desc = etree.SubElement(etree.SubElement(result, f"{TEI}teiHeader"), f"{TEI}fileDesc")
    etree.SubElement(etree.SubElement(file_desc, f"{TEI}titleStmt"), f"{TEI}title").text = work["title"]
    original = root.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original is None:
        raise ValueError("bsb751 source header missing")
    publication = original.find(f"{TEI}publicationStmt")
    bibliography = original.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError("bsb751 publication/bibliography missing")
    file_desc.append(deepcopy(publication))
    etree.SubElement(file_desc, f"{TEI}sourceDesc").append(deepcopy(bibliography))
    wrapper = etree.SubElement(etree.SubElement(etree.SubElement(result, f"{TEI}text"), f"{TEI}body"), f"{TEI}div", type="work", n=work["title"])
    for part in selected:
        wrapper.append(deepcopy(part))
    return etree.tostring(result, encoding="UTF-8", xml_declaration=True)


def _locators(work: dict, source: Path) -> tuple[str, str]:
    if len(work.get("textual_forms", [])) != 1 or len(work["textual_forms"][0].get("editions", [])) != 1:
        raise ValueError(f"ambiguous bsb751 work/edition: {work['work_id']}")
    edition = work["textual_forms"][0]["editions"][0]
    if len(edition.get("acquisition_ids", [])) != 1:
        raise ValueError(f"ambiguous bsb751 acquisition: {work['work_id']}")
    pair = edition["containing_source"]["locator"].split("; ")
    prefix = source.as_posix() + "#"
    if len(pair) != 2 or any(not part.startswith(prefix) for part in pair):
        raise ValueError(f"ambiguous bsb751 locator pair: {work['work_id']}")
    first, last = pair[0][len(prefix):], pair[1][len(prefix):]
    if work["work_id"] == "epistola-dadonis-ad-rodobertum":
        if (first, last) != ("bsb00000751_00749_13", "bsb00000751_00749_4"):
            raise ValueError("Dadonis literal reversed catalog locator pair changed")
        return last, first
    return first, last


def _check(source_parts: list[etree._Element], candidate: bytes, locators: tuple[str, str]) -> dict:
    root = etree.fromstring(candidate, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    wrapper = root.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces={"t": TEI[1:-1]})
    if len(wrapper) != 1 or len(wrapper[0]) != len(source_parts):
        raise ValueError("bsb751 candidate native part count differs")
    candidate_parts = list(wrapper[0])
    source_c14n = [_c14n(part) for part in source_parts]
    candidate_c14n = [_c14n(part) for part in candidate_parts]
    if candidate_c14n != source_c14n:
        raise ValueError("bsb751 selected source part C14N differs from candidate")
    ids = [node.get(XML_ID) for part in source_parts for node in part.iter() if (node.get(XML_ID) or "").startswith("bsb00000751_")]
    if len(ids) != len(set(ids)) or locators[0] not in ids or locators[1] not in ids:
        raise ValueError("bsb751 catalog locator not unique inside complete parts")
    if ids.index(locators[0]) > 2 or ids[-1] != locators[1]:
        raise ValueError("bsb751 catalog locators do not cover complete selected parts")
    return dict(source_part_c14n_sha256=source_c14n, candidate_part_c14n_sha256=candidate_c14n,
                start_xml_id=locators[0], end_xml_id=locators[1], source_milestone_count=len(ids))


def prepare(destination: Path) -> dict:
    destination = destination.absolute()
    if _io_path(destination).exists() or not _io_path(destination.parent).is_dir() or ROOT in destination.parents:
        raise ValueError("fresh external bsb751 destination required")
    source_bytes, source, source_works = _source()
    inv = next(group for group in inventory()["groups"] if group["source_path"] == SOURCE.as_posix())
    catalog = {item["work_id"]: item for item in inv["works"]}
    selected_parts = {(i, j) for i, indexes in SELECTIONS.values() for j in indexes}
    if selected_parts & set(HELD_PARTS) or selected_parts | set(HELD_PARTS) != {(i, j) for i in (3, 4, 11, 17) for j in range(len(source_works[i]))}:
        raise ValueError("bsb751 five shared carriers are not fully dispositioned")
    prepared = []
    for work_id, (index, ordinals) in SELECTIONS.items():
        item = catalog[work_id]
        if item["accepted_master_present"]:
            raise ValueError(f"bsb751 selected work already accepted: {work_id}")
        work_path = ROOT / item["work_path"]
        acquisition_path = ROOT / item["acquisition_path"]
        if _sha(work_path) != item["work_sha256"] or _sha(acquisition_path) != item["acquisition_sha256"]:
            raise ValueError(f"bsb751 work/acquisition changed: {work_id}")
        work = json.loads(_io_path(work_path).read_bytes())
        acquisition = json.loads(_io_path(acquisition_path).read_bytes())
        retained = acquisition.get("retained_files", [])
        if (acquisition.get("source_path") != SOURCE.as_posix() or acquisition.get("source_sha256") != SOURCE_SHA
                or len(retained) != 2 or {entry["path"] for entry in retained} != {SOURCE.as_posix(), PACKAGE.as_posix()}):
            raise ValueError(f"bsb751 extracted XML/package binding differs: {work_id}")
        locators = _locators(work, SOURCE)
        parts = [source_works[index][j] for j in ordinals]
        candidate = _candidate(source, parts, work)
        oracle = _check(parts, candidate, locators)
        prepared.append((work_id, index, ordinals, work, item, acquisition, candidate, oracle))
    _io_path(destination).mkdir(parents=True)
    results = []
    for work_id, index, ordinals, work, item, acquisition, candidate, oracle in prepared:
        path = destination / work_id / "candidate.tei.xml"
        _io_path(path).parent.mkdir(parents=True)
        _io_path(path).write_bytes(candidate)
        if errors := validate_file(_io_path(path)):
            raise ValueError(f"bsb751 TEI P5 XSD failed for {work_id}: {errors[:3]}")
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = dict(work_id=work_id, textual_form_id=form["textual_form_id"], edition_id=edition["edition_id"])
        revision = work_id + "-bsb751-nested-electronic-v1"
        projection = project_document(_io_path(path), identity=identity, language="la", representation_revision=revision,
                                      edition_title=edition["title"], _allow_acceptance_metadata=True, category="prose")
        errors = verify_document(_io_path(path), projection["rows"], projection["receipt"], identity=identity,
                                 language="la", representation_revision=revision, edition_title=edition["title"],
                                 _allow_acceptance_metadata=True, category="prose")
        if errors or len(projection["rows"]) != 1:
            raise ValueError(f"bsb751 native projection failed for {work_id}: {errors[:3]}")
        results.append(dict(work_id=work_id, source_work_div_index=index, source_part_indexes=list(ordinals),
                            source_work_div_n=source_works[index].get("n"), candidate_path=path.as_posix(),
                            candidate_sha256=sha256(candidate).hexdigest(), work_path=item["work_path"],
                            work_sha256=item["work_sha256"], acquisition_path=item["acquisition_path"],
                            acquisition_sha256=item["acquisition_sha256"], oracle=oracle,
                            catalog_locator_ids=item["catalog_locator_ids"],
                            ordered_source_locator_ids=[oracle["start_xml_id"], oracle["end_xml_id"]],
                            locator_order_disposition=("literal catalog pair is reversed; source-order endpoints are used for complete-part verification"
                                                       if work_id == "epistola-dadonis-ad-rodobertum" else "catalog pair is in source order"),
                            tei_xsd="pass", native_projection_rows=1, native_verify="pass"))
    other_divisions = []
    for index, div in enumerate(source_works):
        if index in {3, 4, 11, 17}:
            continue
        owners = [item for item in inv["works"] if index in item["top_work_div_indexes"]]
        other_divisions.append(dict(index=index, literal_n=div.get("n"),
                                    catalog_owners=[dict(work_id=o["work_id"], accepted_master_present=o["accepted_master_present"]) for o in owners],
                                    disposition="outside this nested-part batch; already accepted" if owners and all(o["accepted_master_present"] for o in owners) else "outside this nested-part batch; independently held or uncataloged"))
    receipt = dict(contract=CONTRACT, status="nonaccepted", source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                   source_bytes=len(source_bytes), package_path=PACKAGE.as_posix(), package_sha256=PACKAGE_SHA,
                   package_disposition="acquisition package only; extracted XML is text authority",
                   acquisition_receipt_path=ACQUISITION_RECEIPT.as_posix(), acquisition_receipt_sha256=ACQUISITION_RECEIPT_SHA,
                   selected_part_count=len(selected_parts), selected_works=results,
                   held_parts=[dict(source_work_div_index=i, source_part_index=j, reason=reason, source_c14n_sha256=_c14n(source_works[i][j])) for (i,j),reason in sorted(HELD_PARTS.items())],
                   other_source_divisions=other_divisions, canonical_install="not-performed")
    _io_path(destination / "receipt.json").write_bytes(_json(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    result = prepare(parser.parse_args().destination)
    print(json.dumps(dict(status=result["status"], works=len(result["selected_works"]),
                          selected_parts=result["selected_part_count"], held_parts=len(result["held_parts"])), sort_keys=True))


if __name__ == "__main__":
    main()
