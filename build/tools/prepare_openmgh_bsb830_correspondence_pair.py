"""Prepare two source-native correspondence slices from extracted bsb830 TEI.

This is a work-local, nonaccepted candidate stage. Native source line and
word, highlight, and page nodes remain intact; no text units are invented.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.openmgh_bsb830_correspondence_pair_oracle import check_candidate
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file
from build.tools.openmgh_review import load_bound_work as _shared_work


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml")
SOURCE_SHA256 = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
PACKAGE = Path("raw/openmgh/bsb00000830/bsb00000830.zip")
PACKAGE_SHA256 = "3cc84719875aec1c7a3bceb9cb754f55d191705bce73f628f93135bad6e8f1e5"
RECEIPT = Path("raw/openmgh/bsb00000830/acquisition-receipt.json")
RECEIPT_SHA256 = "6937a8c05fc2c094ae1b9ab57f34fe639e77972877976474ba2513de0d8b885c"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORKS = (
    ("cameracenses-letter-to-reims-church", 1),
    ("noviomenses-reply-to-cameracenses", 2),
)
SPANS = {1: (4, 143), 2: (144, 260)}
BOUNDARY_PAGE: dict[int, str] = {}
INTERNAL_PAGES = {
    1: ("bsb00000830_00583", "bsb00000830_00584"),
    2: ("bsb00000830_00585", "bsb00000830_00586"),
}


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
    blocks = source.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='volume']/t:div[@n='Cameracensium et Noviomensium cler. ep.']/t:ab",
        namespaces=ns,
    )
    if len(blocks) != 1 or number not in SPANS:
        raise ValueError("unrecognized correspondence carrier or selection")
    children = list(blocks[0])
    start, end = SPANS[number]
    next_index = end + 1
    if number in BOUNDARY_PAGE:
        page = children[next_index]
        if page.tag != f"{TEI}pb" or page.get(XML_ID) != BOUNDARY_PAGE[number]:
            raise ValueError("source-owned boundary page changed")
        next_index += 1
    openings = {
        1: ("bsb00000830_00582_19", "Sanctae matri nostrae Remensi ecclesiae omnibusque ipsius diocesi", "bsb00000830_00584_22"),
        2: ("bsb00000830_00584_22", "Sanctae Cameracensis ecclesiae fratribus in Christo dilectis", None),
    }
    start_id, opening, next_id = openings[number]
    if (children[start].get(XML_ID) != start_id or (children[start].tail or "").strip() != opening
            or (next_id is not None and children[next_index].get(XML_ID) != next_id)
            or (next_id is None and next_index != len(children))
            or tuple(node.get(XML_ID) for node in children[start:end + 1] if node.tag == f"{TEI}pb")
               != INTERNAL_PAGES[number]):
        raise ValueError("literal letter span or neighboring salutation changed")
    selected = children[start:end + 1]
    output = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    output.set(XML_ID, f"ocd-{work['work_id']}-bsb830-electronic-v1")
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
    block = etree.SubElement(etree.SubElement(body, f"{TEI}div", type="work", n=work["title"]), f"{TEI}ab")
    for node in selected:
        block.append(deepcopy(node))
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
        revision = f"{work_id}-bsb830-correspondence-v1"
        projection = project_document(candidate_path, identity=identity, language="la",
                                      representation_revision=revision,
                                      edition_title=edition["title"],
                                      _allow_acceptance_metadata=True, category="prose")
        errors = verify_document(candidate_path, projection["rows"], projection["receipt"],
                                 identity=identity, language="la",
                                 representation_revision=revision,
                                 edition_title=edition["title"],
                                 _allow_acceptance_metadata=True, category="prose")
        if errors or len(projection["rows"]) != 1:
            raise ValueError(f"native prose projection failed for {work_id}: {errors[:3]}")
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
                        "native_prose_rows": 1, "native_prose_verify": "pass"})
    receipt = {"contract": "ocd-openmgh-bsb830-correspondence-pair-direct-candidates-v1",
               "status": "nonaccepted", "source_path": SOURCE.as_posix(),
               "source_sha256": SOURCE_SHA256, "package_path": PACKAGE.as_posix(),
               "package_sha256": PACKAGE_SHA256, "acquisition_receipt": RECEIPT.as_posix(),
               "acquisition_receipt_sha256": RECEIPT_SHA256,
               "shared_collection_heading": ["bsb00000830_00581_1", "bsb00000830_00581_2"],
               "internal_page_breaks": [page for pages in INTERNAL_PAGES.values() for page in pages],
               "source_scope": "Two complete correspondence slices, each beginning at its own salutation and preserving every native line, word, highlight, and page node; the shared collection heading remains source-owned.",
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
