"""Prepare the complete Desiderii hymn part from extracted bsb753 TEI.

This is a work-local, nonaccepted candidate stage. Native source lines, title highlight, column spans, and anchors remain intact;
no text units are invented.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.openmgh_bsb753_desiderii_hymn_oracle import check_candidate
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file
from build.tools.openmgh_review import load_bound_work as _shared_work


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000753/tei/bsb00000753.xml")
SOURCE_SHA256 = "550c090dad42988c5a8c95adc3328a3b5ef93dcfeaa8f91354fe6a03995f9b27"
PACKAGE = Path("raw/openmgh/bsb00000753/bsb00000753.zip")
PACKAGE_SHA256 = "ff5203afca88460696e59645610cccd241d0cbe5651e5dde095a787238a33ad8"
RECEIPT = Path("raw/openmgh/bsb00000753/acquisition-receipt.json")
RECEIPT_SHA256 = "e27e77597ea0fb304a4485a7adeb9b2bc75e2d8e296bd3b6df22a1b98af39eed"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORKS = (("hymnus-desiderii-et-reginfridi", 1),)


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _source(root: Path) -> tuple[bytes, etree._Element]:
    for relative, expected in ((SOURCE, SOURCE_SHA256), (PACKAGE, PACKAGE_SHA256),
                               (RECEIPT, RECEIPT_SHA256)):
        if _sha(root / relative) != expected:
            raise ValueError(f"retained acquisition bytes changed: {relative}")
    data = Path(_io_path(root / SOURCE)).read_bytes()
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    source = etree.fromstring(data, parser)
    if source.getroottree().docinfo.doctype:
        raise ValueError("source DOCTYPE is forbidden")
    return data, source


def _work(root: Path, work_id: str) -> tuple[dict, dict, Path, Path]:
    return _shared_work(root, work_id, PACKAGE=PACKAGE, SOURCE=SOURCE,
        SOURCE_SHA256=SOURCE_SHA256, _read=_read)


def _candidate(source: etree._Element, work: dict, number: int) -> bytes:
    ns = {"t": TEI[1:-1]}
    parts = source.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='volume']/t:div[@n='Pass. Des. ep. et Reginfr. diac. Alsegaudiensium']/t:div[@type='part']",
        namespaces=ns,
    )
    if number != 1 or len(parts) != 2:
        raise ValueError("unrecognized Desiderii hymn part")
    part = parts[number]
    if (len(part) != 1 or part[0].tag != f"{TEI}ab" or len(part[0]) != 43
            or part[0][0].get(XML_ID) != "bsb00000753_00071_10"
            or part[0][-1].get(XML_ID) != "bsb00000753_00071_47"
            or (part[0][-1].tail or "").strip() != "Amen."):
        raise ValueError("Desiderii part or catalog endpoint changed")
    output = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    output.set(XML_ID, f"ocd-{work['work_id']}-bsb753-electronic-v1")
    file_desc = etree.SubElement(etree.SubElement(output, f"{TEI}teiHeader"), f"{TEI}fileDesc")
    etree.SubElement(etree.SubElement(file_desc, f"{TEI}titleStmt"), f"{TEI}title").text = work["title"]
    original = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original is None:
        raise ValueError("source header missing")
    publication = original.find(f"{TEI}publicationStmt")
    bibliography = original.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError("source rights statement or print bibliography missing")
    file_desc.append(deepcopy(publication))
    etree.SubElement(file_desc, f"{TEI}sourceDesc").append(deepcopy(bibliography))
    body = etree.SubElement(etree.SubElement(output, f"{TEI}text"), f"{TEI}body")
    outer = etree.SubElement(body, f"{TEI}div", type="work", n=work["title"])
    outer.append(deepcopy(part))
    return etree.tostring(output, encoding="UTF-8", xml_declaration=True)


def prepare(destination: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    destination = destination.absolute()
    if (destination == root or root in destination.parents
            or Path(_io_path(destination)).exists()):
        raise ValueError("fresh external candidate destination required")
    source_bytes, source = _source(root)
    prepared = []
    for work_id, number in WORKS:
        work, acquisition, work_path, acquisition_path = _work(root, work_id)
        candidate = _candidate(source, work, number)
        checked = check_candidate(source_bytes, candidate, work, acquisition,
                                  number=number)
        prepared.append((work_id, work, acquisition, work_path, acquisition_path,
                         candidate, checked))
    Path(_io_path(destination)).mkdir(parents=True)
    results = []
    for work_id, work, acquisition, work_path, acquisition_path, candidate, checked in prepared:
        candidate_path = destination / work_id / "candidate.tei.xml"
        target = Path(_io_path(candidate_path))
        target.parent.mkdir(parents=True)
        target.write_bytes(candidate)
        if errors := validate_file(candidate_path):
            raise ValueError(f"TEI P5 XSD failed for {work_id}: {errors[:3]}")
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                    "edition_id": edition["edition_id"]}
        revision = f"{work_id}-bsb753-hymn-v1"
        projection = project_document(candidate_path, identity=identity, language="la",
                                      representation_revision=revision,
                                      edition_title=edition["title"],
                                      _allow_acceptance_metadata=True, category="poetry")
        errors = verify_document(candidate_path, projection["rows"], projection["receipt"],
                                 identity=identity, language="la",
                                 representation_revision=revision,
                                 edition_title=edition["title"],
                                 _allow_acceptance_metadata=True, category="poetry")
        if errors or len(projection["rows"]) != 1:
            raise ValueError(f"native poetry projection failed for {work_id}: {errors[:3]}")
        results.append({"work_id": work_id, "number": checked["number"],
                        "source_heading_id": checked["source_heading_id"],
                        "source_last_line_id": checked["source_last_line_id"],
                        "source_end_id": checked["source_end_id"],
                        "line_count": checked["line_count"],
                        "work_path": work_path.as_posix(),
                        "work_sha256": _sha(root / work_path),
                        "acquisition_path": acquisition_path.as_posix(),
                        "acquisition_sha256": _sha(root / acquisition_path),
                        "candidate_path": candidate_path.as_posix(),
                        "candidate_sha256": sha256(candidate).hexdigest(),
                        "independent_oracle": checked, "tei_xsd": "pass",
                        "native_poetry_rows": 1, "native_poetry_verify": "pass"})
    receipt = {"contract": "ocd-openmgh-bsb753-desiderii-hymn-direct-candidates-v1",
               "status": "nonaccepted", "source_path": SOURCE.as_posix(),
               "source_sha256": SOURCE_SHA256, "package_path": PACKAGE.as_posix(),
               "package_sha256": PACKAGE_SHA256, "acquisition_receipt": RECEIPT.as_posix(),
               "acquisition_receipt_sha256": RECEIPT_SHA256,
               "shared_collection_heading": [],
               "internal_page_breaks": [],
               "source_scope": "The complete Desiderii and Reginfridi hymn in the second native part, including its title highlight, all 38 line markers, two column spans, and both closing anchors; the preceding prose part remains outside this scope.",
               "works": results, "acceptance_stage": "not-prepared",
               "canonical_install": "not-performed"}
    Path(_io_path(destination / "receipt.json")).write_bytes(_json(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    receipt = prepare(args.destination)
    print(json.dumps({"works": len(receipt["works"]), "receipt": str(args.destination / "receipt.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
