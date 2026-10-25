"""Prepare five exclusive complete bsb754 nested-part candidates."""

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
SOURCE = Path("raw/openmgh/bsb00000754/tei/bsb00000754.xml")
SOURCE_SHA = "3349fbef5e7e957e964433d097e94a4a35d84addcbd6a314a88819e6a53039ff"
PACKAGE = Path("raw/openmgh/bsb00000754/bsb00000754.zip")
PACKAGE_SHA = "f25422ac5fb447be60d9d6fcc99509a546144224ac68b370c220b89df0a715fe"
ACQUISITION_RECEIPT = Path("raw/openmgh/bsb00000754/acquisition-receipt.json")
ACQUISITION_RECEIPT_SHA = "67f23305c57ba40d40f351393c3dd7408b36bbcdaeef27113fb6bd2b7ee0eeb2"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CONTRACT = "ocd-openmgh-bsb754-exclusive-nested-parts-v1"
SELECTIONS = {
    "vita-sancti-leutfredi": (0, (0,)),
    "miracula-ad-sepulchrum-leutfredi": (0, (1,)),
    "vita-sancti-gangulfi": (4, (0,)),
    "vita-sancti-germani-parisiaci-fortunati": (12, (0,)),
    "translatio-sancti-germani-parisiaci": (12, (2,)),
}
HELD_PARTS = {
    (4, 1): "Separately labeled Gangulfi hymn is verse and requires a native verse representation decision.",
    (12, 1): "Separately labeled shorter Vita Germani is an alternate textual version without an established catalog edition owner in this batch.",
}
HELD_DIVISIONS = {
    2: "Single unsplit ab carries catalog Eucherii and Rigobertus spans; no native sibling work boundary.",
    7: "Supplementary Passio Afrae has no current catalog work identity in this source inventory.",
    9: "Vita Lupi has another retained bsb750 electronic edition; this batch does not choose between editions.",
    11: "Vita abbatum Acaunensium has another retained bsb750 electronic edition; this batch does not choose between editions.",
    14: "Vita Richarii has no current catalog work identity in this source inventory.",
    16: "Chronologica regum Francorum has no current catalog work identity in this source inventory.",
    17: "Origo Francorum duplex requires a representation and work-boundary decision for its double text.",
    18: "Gregorii Passio septem dormientium has another retained bsb50862 electronic edition; this batch does not choose between editions.",
    19: "Catalogus regum Francorum has no current catalog work identity in this source inventory.",
}


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _source() -> tuple[bytes, etree._Element, list[etree._Element]]:
    for path, expected in ((SOURCE, SOURCE_SHA), (PACKAGE, PACKAGE_SHA), (ACQUISITION_RECEIPT, ACQUISITION_RECEIPT_SHA)):
        if _sha(ROOT / path) != expected:
            raise ValueError(f"bsb754 source/package/receipt pin changed: {path}")
    content = _io_path(ROOT / SOURCE).read_bytes()
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    if root.getroottree().docinfo.doctype:
        raise ValueError("bsb754 source DOCTYPE is forbidden")
    volume = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces={"t": TEI[1:-1]})
    if len(volume) != 1 or len(volume[0]) != 20:
        raise ValueError("bsb754 source volume direct division count changed")
    works = [item for item in volume[0] if item.tag == f"{TEI}div" and item.get("type") == "work"]
    if len(works) != 20 or any(item not in volume[0] for item in works):
        raise ValueError("bsb754 source top-level interstitial matter changed")
    expected_carriers = {0: 2, 4: 2, 12: 3}
    if {index: len(works[index]) for index in expected_carriers} != expected_carriers:
        raise ValueError("bsb754 shared-carrier part census changed")
    for index, count in expected_carriers.items():
        if any(item.tag != f"{TEI}div" or item.get("type") != "part" for item in works[index]):
            raise ValueError(f"bsb754 carrier {index} has nonpart shared matter")
    return content, root, works


def _c14n(element: etree._Element) -> str:
    detached = deepcopy(element)
    etree.cleanup_namespaces(detached)
    return sha256(etree.tostring(detached, method="c14n", with_comments=True)).hexdigest()


def _candidate(root: etree._Element, selected: list[etree._Element], work: dict) -> bytes:
    result = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    result.set(XML_ID, f"ocd-{work['work_id']}-bsb754-nested-electronic-v1")
    file_desc = etree.SubElement(etree.SubElement(result, f"{TEI}teiHeader"), f"{TEI}fileDesc")
    etree.SubElement(etree.SubElement(file_desc, f"{TEI}titleStmt"), f"{TEI}title").text = work["title"]
    original = root.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original is None:
        raise ValueError("bsb754 source header missing")
    publication = original.find(f"{TEI}publicationStmt")
    bibliography = original.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError("bsb754 publication/bibliography missing")
    file_desc.append(deepcopy(publication))
    etree.SubElement(file_desc, f"{TEI}sourceDesc").append(deepcopy(bibliography))
    wrapper = etree.SubElement(etree.SubElement(etree.SubElement(result, f"{TEI}text"), f"{TEI}body"), f"{TEI}div", type="work", n=work["title"])
    for part in selected:
        wrapper.append(deepcopy(part))
    return etree.tostring(result, encoding="UTF-8", xml_declaration=True)


def _locators(work: dict, source: Path) -> tuple[str, str]:
    if len(work.get("textual_forms", [])) != 1 or len(work["textual_forms"][0].get("editions", [])) != 1:
        raise ValueError(f"ambiguous bsb754 work/edition: {work['work_id']}")
    edition = work["textual_forms"][0]["editions"][0]
    if len(edition.get("acquisition_ids", [])) != 1:
        raise ValueError(f"ambiguous bsb754 acquisition: {work['work_id']}")
    pair = edition["containing_source"]["locator"].split("; ")
    prefix = source.as_posix() + "#"
    if len(pair) != 2 or any(not part.startswith(prefix) for part in pair):
        raise ValueError(f"ambiguous bsb754 locator pair: {work['work_id']}")
    first, last = pair[0][len(prefix):], pair[1][len(prefix):]
    return first, last


def _check(source_parts: list[etree._Element], candidate: bytes, locators: tuple[str, str]) -> dict:
    root = etree.fromstring(candidate, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    wrapper = root.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces={"t": TEI[1:-1]})
    if len(wrapper) != 1 or len(wrapper[0]) != len(source_parts):
        raise ValueError("bsb754 candidate native part count differs")
    candidate_parts = list(wrapper[0])
    source_c14n = [_c14n(part) for part in source_parts]
    candidate_c14n = [_c14n(part) for part in candidate_parts]
    if candidate_c14n != source_c14n:
        raise ValueError("bsb754 selected source part C14N differs from candidate")
    ids = [node.get(XML_ID) for part in source_parts for node in part.iter() if (node.get(XML_ID) or "").startswith("bsb00000754_")]
    if len(ids) != len(set(ids)) or locators[0] not in ids or locators[1] not in ids:
        raise ValueError("bsb754 catalog locator not unique inside complete parts")
    if ids.index(locators[0]) > 2 or ids[-1] != locators[1]:
        raise ValueError("bsb754 catalog locators do not cover complete selected parts")
    return dict(source_part_c14n_sha256=source_c14n, candidate_part_c14n_sha256=candidate_c14n,
                start_xml_id=locators[0], end_xml_id=locators[1], source_milestone_count=len(ids))


def prepare(destination: Path) -> dict:
    destination = destination.absolute()
    if _io_path(destination).exists() or not _io_path(destination.parent).is_dir() or ROOT in destination.parents:
        raise ValueError("fresh external bsb754 destination required")
    source_bytes, source, source_works = _source()
    inv = next(group for group in inventory()["groups"] if group["source_path"] == SOURCE.as_posix())
    catalog = {item["work_id"]: item for item in inv["works"]}
    selected_parts = {(i, j) for i, indexes in SELECTIONS.values() for j in indexes}
    if selected_parts & set(HELD_PARTS) or selected_parts | set(HELD_PARTS) != {(i, j) for i in (0, 4, 12) for j in range(len(source_works[i]))}:
        raise ValueError("bsb754 three shared carriers are not fully dispositioned")
    prepared = []
    for work_id, (index, ordinals) in SELECTIONS.items():
        item = catalog[work_id]
        if item["accepted_master_present"]:
            raise ValueError(f"bsb754 selected work already accepted: {work_id}")
        work_path = ROOT / item["work_path"]
        acquisition_path = ROOT / item["acquisition_path"]
        if _sha(work_path) != item["work_sha256"] or _sha(acquisition_path) != item["acquisition_sha256"]:
            raise ValueError(f"bsb754 work/acquisition changed: {work_id}")
        work = json.loads(_io_path(work_path).read_bytes())
        acquisition = json.loads(_io_path(acquisition_path).read_bytes())
        retained = acquisition.get("retained_files", [])
        if (acquisition.get("source_path") != SOURCE.as_posix() or acquisition.get("source_sha256") != SOURCE_SHA
                or len(retained) != 2 or {entry["path"] for entry in retained} != {SOURCE.as_posix(), PACKAGE.as_posix()}):
            raise ValueError(f"bsb754 extracted XML/package binding differs: {work_id}")
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
            raise ValueError(f"bsb754 TEI P5 XSD failed for {work_id}: {errors[:3]}")
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = dict(work_id=work_id, textual_form_id=form["textual_form_id"], edition_id=edition["edition_id"])
        revision = work_id + "-bsb754-nested-electronic-v1"
        projection = project_document(_io_path(path), identity=identity, language="la", representation_revision=revision,
                                      edition_title=edition["title"], _allow_acceptance_metadata=True, category="prose")
        errors = verify_document(_io_path(path), projection["rows"], projection["receipt"], identity=identity,
                                 language="la", representation_revision=revision, edition_title=edition["title"],
                                 _allow_acceptance_metadata=True, category="prose")
        if errors or len(projection["rows"]) != 1:
            raise ValueError(f"bsb754 native projection failed for {work_id}: {errors[:3]}")
        results.append(dict(work_id=work_id, source_work_div_index=index, source_part_indexes=list(ordinals),
                            source_work_div_n=source_works[index].get("n"), candidate_path=path.as_posix(),
                            candidate_sha256=sha256(candidate).hexdigest(), work_path=item["work_path"],
                            work_sha256=item["work_sha256"], acquisition_path=item["acquisition_path"],
                            acquisition_sha256=item["acquisition_sha256"], oracle=oracle,
                            catalog_locator_ids=item["catalog_locator_ids"],
                            ordered_source_locator_ids=[oracle["start_xml_id"], oracle["end_xml_id"]],
                            locator_order_disposition="catalog pair is in source order",
                            tei_xsd="pass", native_projection_rows=1, native_verify="pass"))
    other_divisions = []
    for index, div in enumerate(source_works):
        if index in {0, 4, 12}:
            continue
        owners = [item for item in inv["works"] if index in item["top_work_div_indexes"]]
        if owners and all(o["accepted_master_present"] for o in owners):
            disposition = "outside this nested-part batch; already accepted"
        else:
            disposition = HELD_DIVISIONS.get(index)
            if disposition is None:
                raise ValueError(f"bsb754 direct source division {index} lacks a hold reason")
        other_divisions.append(dict(index=index, literal_n=div.get("n"),
                                    catalog_owners=[dict(work_id=o["work_id"], accepted_master_present=o["accepted_master_present"]) for o in owners],
                                    disposition=disposition))
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
