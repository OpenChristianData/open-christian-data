"""Prepare three exact single-work openMGH electronic candidates; never install."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.openmgh_three_whole_oracle import check_candidate
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORKS = (
    "alexander-minorita-expositio-in-apocalypsim",
    "gregory-of-tours-libri-historiarum-x",
    "vita-anskarii-auctore-rimberto",
)
SOURCES = {
    WORKS[0]: {
        "bsb": "bsb00000626", "sha256": "f596d9710a838a09005292f2304d7658614a2e9432e8ed15635c8f9c538e0aa4",
        "zip_sha256": "c2b40e0893d3d2dc108ee8cfcc96d2453f265ea89b6f752f9bb208089e204d35",
        "receipt_sha256": "a49bcaf853e15b551a0cf7efcb6cd2dfb8d48b618b6db867df45f9ed22adc46b",
        "native_label": "Alex. Minorita", "parts": 24,
        "heading_id": "bsb00000626_00061_1", "end_id": "bsb00000626_00570_28",
    },
    WORKS[1]: {
        "bsb": "bsb00000747", "sha256": "75036def8d9e57260daf2bbc7b1d51b73e2f5d20d3a580db402eb39a090086f0",
        "zip_sha256": "fe46e9d86ca2b3521a6defbc2a09c19689766128fafa4510effb2f59a47b1bbb",
        "receipt_sha256": "8b1dbb0b3f982f29b5e8909cf9841a925e544d3a4311578c62b4e2ad203111ff",
        "native_label": "Greg. Tur. hist.", "parts": 11,
        "heading_id": "bsb00000747_00043_1", "end_id": "bsb00000747_00579_10",
    },
    WORKS[2]: {
        "bsb": "bsb00000703", "sha256": "44517a090c08145812fb06f6bfc9d693363acaefa667e9c4857380bdb4b08f7c",
        "zip_sha256": "d81bb3a385abbfdef024dc9ad5013646c2b65b2f410158f7fc9fe17e3846d02e",
        "receipt_sha256": "9a501daf1c4612ca3c519299b704e9c21d3585d864868f9644ec5a62760e1280",
        "native_label": "Vita Anskarii", "parts": 2,
        "heading_id": "bsb00000703_00013_1", "end_id": "bsb00000703_00100_17",
    },
}


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _paths(work_id: str) -> tuple[Path, Path, Path]:
    bsb = SOURCES[work_id]["bsb"]
    base = Path("raw/openmgh") / bsb
    return base / "tei" / f"{bsb}.xml", base / f"{bsb}.zip", base / "acquisition-receipt.json"


def _source(root: Path, work_id: str) -> tuple[bytes, etree._Element]:
    spec = SOURCES[work_id]
    xml, package, receipt = _paths(work_id)
    for relative, digest in ((xml, spec["sha256"]), (package, spec["zip_sha256"]),
                             (receipt, spec["receipt_sha256"])):
        if _sha(root / relative) != digest:
            raise ValueError(f"retained acquisition bytes changed: {relative}")
    data = Path(_io_path(root / xml)).read_bytes()
    tree = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True,
                                                  huge_tree=True))
    if tree.getroottree().docinfo.doctype:
        raise ValueError(f"source DOCTYPE forbidden: {work_id}")
    return data, tree


def _work(root: Path, work_id: str) -> tuple[dict, dict, Path, Path]:
    work_path = Path("library/works") / work_id / "work.json"
    work = _read(root / work_path)
    if work.get("work_id") != work_id or len(work.get("textual_forms", [])) != 1:
        raise ValueError(f"work identity changed: {work_id}")
    form = work["textual_forms"][0]
    if len(form.get("editions", [])) != 1:
        raise ValueError(f"edition identity ambiguous: {work_id}")
    edition = form["editions"][0]
    if len(edition.get("acquisition_ids", [])) != 1:
        raise ValueError(f"acquisition identity ambiguous: {work_id}")
    acquisition_path = (work_path.parent / "forms" / form["textual_form_id"] / "editions"
                        / edition["edition_id"] / "acquisitions"
                        / f"{edition['acquisition_ids'][0]}.json")
    acquisition = _read(root / acquisition_path)
    xml, package, _ = _paths(work_id)
    if (acquisition.get("source_path") != xml.as_posix()
            or acquisition.get("source_sha256") != SOURCES[work_id]["sha256"]
            or len(acquisition.get("retained_files", [])) != 2
            or acquisition["retained_files"][0].get("path") != package.as_posix()
            or acquisition["retained_files"][1].get("path") != xml.as_posix()):
        raise ValueError(f"extracted-XML text authority changed: {work_id}")
    return work, acquisition, work_path, acquisition_path


def _candidate(source: etree._Element, work: dict, work_id: str) -> bytes:
    ns = {"t": TEI[1:-1]}
    selected = source.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='volume']/t:div[@type='work']", namespaces=ns)
    spec = SOURCES[work_id]
    if len(selected) != 1 or selected[0].get("n") != spec["native_label"] or len(selected[0]) != spec["parts"]:
        raise ValueError(f"unrecognized sole native work: {work_id}")
    lines = selected[0].xpath(".//t:lb", namespaces=ns)
    if lines[0].get(XML_ID) != spec["heading_id"] or lines[-1].get(XML_ID) != spec["end_id"]:
        raise ValueError(f"source heading or ending differs: {work_id}")
    output = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    output.set(XML_ID, f"ocd-{work_id}-{spec['bsb']}-electronic-v1")
    file_desc = etree.SubElement(etree.SubElement(output, f"{TEI}teiHeader"), f"{TEI}fileDesc")
    etree.SubElement(etree.SubElement(file_desc, f"{TEI}titleStmt"), f"{TEI}title").text = work["title"]
    original = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original is None:
        raise ValueError(f"source header missing: {work_id}")
    publication = original.find(f"{TEI}publicationStmt")
    bibliography = original.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError(f"source rights or bibliography missing: {work_id}")
    file_desc.append(deepcopy(publication))
    etree.SubElement(file_desc, f"{TEI}sourceDesc").append(deepcopy(bibliography))
    body = etree.SubElement(etree.SubElement(output, f"{TEI}text"), f"{TEI}body")
    body.append(deepcopy(selected[0]))
    return etree.tostring(output, encoding="UTF-8", xml_declaration=True)


def prepare(destination: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    destination = destination.absolute()
    if destination == root or root in destination.parents or Path(_io_path(destination)).exists():
        raise ValueError("fresh external candidate destination required")
    prepared = []
    for work_id in WORKS:
        source_bytes, tree = _source(root, work_id)
        work, acquisition, work_path, acquisition_path = _work(root, work_id)
        candidate = _candidate(tree, work, work_id)
        checked = check_candidate(source_bytes, candidate, work, acquisition, work_id=work_id)
        prepared.append((work_id, work, acquisition, work_path, acquisition_path,
                         candidate, checked))
    Path(_io_path(destination)).mkdir(parents=True)
    results = []
    for work_id, work, acquisition, work_path, acquisition_path, candidate, checked in prepared:
        path = destination / work_id / "candidate.tei.xml"
        target = Path(_io_path(path))
        target.parent.mkdir(parents=True)
        target.write_bytes(candidate)
        if errors := validate_file(target):
            raise ValueError(f"TEI P5 XSD failed for {work_id}: {errors[:3]}")
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                    "edition_id": edition["edition_id"]}
        revision = f"{work_id}-openmgh-whole-v1"
        projection = project_document(target, identity=identity, language="la",
                                      representation_revision=revision, edition_title=edition["title"],
                                      _allow_acceptance_metadata=True, category="prose")
        errors = verify_document(target, projection["rows"], projection["receipt"],
                                 identity=identity, language="la",
                                 representation_revision=revision, edition_title=edition["title"],
                                 _allow_acceptance_metadata=True, category="prose")
        if errors or len(projection["rows"]) != 1:
            raise ValueError(f"native prose projection failed for {work_id}: {errors[:3]}")
        xml, package, receipt = _paths(work_id)
        results.append({"work_id": work_id, "source_path": xml.as_posix(),
                        "source_sha256": SOURCES[work_id]["sha256"],
                        "package_path": package.as_posix(), "package_sha256": SOURCES[work_id]["zip_sha256"],
                        "acquisition_receipt": receipt.as_posix(),
                        "acquisition_receipt_sha256": SOURCES[work_id]["receipt_sha256"],
                        "work_path": work_path.as_posix(), "work_sha256": _sha(root / work_path),
                        "acquisition_path": acquisition_path.as_posix(),
                        "acquisition_sha256": _sha(root / acquisition_path),
                        "candidate_path": path.as_posix(), "candidate_sha256": sha256(candidate).hexdigest(),
                        "independent_oracle": checked, "tei_xsd": "pass",
                        "native_prose_rows": 1, "native_prose_verify": "pass"})
    receipt = {"contract": "ocd-openmgh-three-whole-direct-candidates-v1", "status": "nonaccepted",
               "works": results, "acceptance_stage": "not-prepared", "canonical_install": "not-performed"}
    Path(_io_path(destination / "receipt.json")).write_bytes(_json(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.destination)
    print(json.dumps({"works": len(result["works"]),
                      "receipt": str(args.destination / "receipt.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
