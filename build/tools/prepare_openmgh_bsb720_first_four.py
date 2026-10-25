"""Prepare four source-defined Lambert poems from the extracted bsb720 TEI.

This is a work-local, nonaccepted candidate stage. Native source line nodes and
their text remain intact; no line or stanza units are invented.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.openmgh_bsb720_first_four_oracle import check_candidate
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file
from build.tools.openmgh_review import load_bound_work as _shared_work


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000720/tei/bsb00000720.xml")
SOURCE_SHA256 = "2a096d80ae17e4f701fdce91585d77afb5d69e385167a46f45173e887dc38ce5"
PACKAGE = Path("raw/openmgh/bsb00000720/bsb00000720.zip")
PACKAGE_SHA256 = "d4399d2e138f4c4f4dfb27a21294b71fa66a76b7b96e427ee0867055472f0dcd"
RECEIPT = Path("raw/openmgh/bsb00000720/acquisition-receipt.json")
RECEIPT_SHA256 = "0bda7667b5337ad4466bd2f8d78a8bd12cef3f7f7db8f345b6141af3b0171696"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORKS = (
    ("lambertus-circa-reliquias", 1),
    ("lambertus-ad-altare-sancti-benedicti", 2),
    ("lambertus-in-trabe-crucis", 3),
    ("lambertus-in-ianua-ecclesie", 4),
)


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
    carmina = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']/t:div[@n='Carmina']/t:ab", namespaces=ns)
    if len(carmina) != 1:
        raise ValueError("Carmina source container changed")
    children = list(carmina[0])
    section_ends = [i for i, node in enumerate(children)
                    if node.tag == f"{TEI}lb" and (node.tail or "").strip() == "〈II.〉"]
    if section_ends != [145]:
        raise ValueError("opening Lambert section endpoint changed")
    headings = {}
    for i, node in enumerate(children[:section_ends[0]]):
        if node.tag == f"{TEI}lb" and node.tail:
            for n in range(1, 6):
                if node.tail.strip().startswith(f"〈{n}.〉"):
                    if n in headings:
                        raise ValueError(f"repeated poem heading {n}")
                    headings[n] = i
    if set(headings) != set(range(1, 6)) or not (headings[1] < headings[2] < headings[3] < headings[4] < headings[5]):
        raise ValueError("first five numbered poem headings changed")
    selected = children[headings[number]:headings[number + 1]]
    if selected and selected[-1].tag == f"{TEI}pb":
        if number != 2 or selected[-1].get(XML_ID) != "bsb00000720_00268":
            raise ValueError("unreviewed page marker at poem boundary")
        selected = selected[:-1]
    if not selected or selected[0].tag != f"{TEI}lb":
        raise ValueError("work does not start at a native line")
    if any(node.tag != f"{TEI}lb" for node in selected):
        raise ValueError("page marker or unsupported node inside selected poem")
    output = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    output.set(XML_ID, f"ocd-{work['work_id']}-bsb720-electronic-v1")
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
    poem = etree.SubElement(body, f"{TEI}div", type="work", n=work["title"])
    block = etree.SubElement(poem, f"{TEI}ab")
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
        revision = f"{work_id}-bsb720-poem-v1"
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
                        "line_count": checked["line_count"],
                        "work_path": work_path.as_posix(),
                        "work_sha256": _sha(root / work_path),
                        "acquisition_path": acquisition_path.as_posix(),
                        "acquisition_sha256": _sha(root / acquisition_path),
                        "candidate_path": candidate_path.as_posix(),
                        "candidate_sha256": sha256(candidate).hexdigest(),
                        "independent_oracle": checked, "tei_xsd": "pass",
                        "native_poetry_rows": 1, "native_poetry_verify": "pass"})
    receipt = {"contract": "ocd-openmgh-bsb720-first-four-direct-candidates-v1",
               "status": "nonaccepted", "source_path": SOURCE.as_posix(),
               "source_sha256": SOURCE_SHA256, "package_path": PACKAGE.as_posix(),
               "package_sha256": PACKAGE_SHA256, "acquisition_receipt": RECEIPT.as_posix(),
               "acquisition_receipt_sha256": RECEIPT_SHA256,
               "shared_collection_heading": ["bsb00000720_00267_1", "bsb00000720_00267_2"],
               "intervening_page_break": "bsb00000720_00268",
               "source_scope": "Four complete numbered Lambert poems inside the flat Carmina ab; native source line nodes and their following text are retained intact.",
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
