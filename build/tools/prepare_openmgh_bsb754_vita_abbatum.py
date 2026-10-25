"""Prepare the exact bsb754 Vita abbatum electronic candidate; never install."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from build.tei.openmgh_bsb754_vita_abbatum_oracle import check_candidate
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "vita-sanctorum-abbatum-acaunensium"
FORM_ID = f"{WORK_ID}-openmgh-retained"
EDITION_ID = f"{WORK_ID}-bsb00000754-electronic"
OTHER_EDITION_ID = f"{WORK_ID}-bsb00000750-electronic"
SOURCE = Path("raw/openmgh/bsb00000754/tei/bsb00000754.xml")
SOURCE_SHA256 = "3349fbef5e7e957e964433d097e94a4a35d84addcbd6a314a88819e6a53039ff"
PACKAGE = Path("raw/openmgh/bsb00000754/bsb00000754.zip")
PACKAGE_SHA256 = "f25422ac5fb447be60d9d6fcc99509a546144224ac68b370c220b89df0a715fe"
RECEIPT = Path("raw/openmgh/bsb00000754/acquisition-receipt.json")
RECEIPT_SHA256 = "67f23305c57ba40d40f351393c3dd7408b36bbcdaeef27113fb6bd2b7ee0eeb2"
OTHER_ACQUISITION_SHA256 = "174d82631e97c9c4efa3fa3eba5276dd14b9566ed2d0bb0407aa8fd8979e8811"
OTHER_SOURCE = Path("raw/openmgh/bsb00000750/tei/bsb00000750.xml")
OTHER_SOURCE_SHA256 = "a88f93a090b6fd452a05b3cbc39a50f7bd7059cd94547f3cd712a4937243f0fc"
OTHER_PACKAGE = Path("raw/openmgh/bsb00000750/bsb00000750.zip")
OTHER_PACKAGE_SHA256 = "71542cfb4f7372efd3908996848052cdf3fcc2a0d7c14348dc16fa407338a22c"
OTHER_RECEIPT = Path("raw/openmgh/bsb00000750/acquisition-receipt.json")
OTHER_RECEIPT_SHA256 = "fae4db8f39ebf080e3a9b499a7bd29b5c26ceef277fb360191753cb5fd7aab5d"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _source(root: Path) -> tuple[bytes, etree._Element]:
    for relative, digest in ((SOURCE, SOURCE_SHA256), (PACKAGE, PACKAGE_SHA256),
                             (RECEIPT, RECEIPT_SHA256)):
        if _sha(root / relative) != digest:
            raise ValueError(f"retained acquisition bytes changed: {relative}")
    data = Path(_io_path(root / SOURCE)).read_bytes()
    with ZipFile(_io_path(root / PACKAGE)) as archive:
        members = archive.namelist()
        if members != ["bsb00000754.xml"] or archive.read(members[0]) != data:
            raise ValueError("bsb754 acquisition ZIP is not the exact extracted XML")
    tree = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True,
                                                  remove_comments=False, huge_tree=True))
    if tree.getroottree().docinfo.doctype:
        raise ValueError("source DOCTYPE forbidden")
    return data, tree


def _work(root: Path) -> tuple[dict, dict, Path, Path, Path]:
    work_path = Path("library/works") / WORK_ID / "work.json"
    work = _read(root / work_path)
    if work.get("work_id") != WORK_ID or len(work.get("textual_forms", [])) != 1:
        raise ValueError("Vita abbatum work identity changed")
    form = work["textual_forms"][0]
    if form["textual_form_id"] != FORM_ID or [item["edition_id"] for item in form["editions"]] != [OTHER_EDITION_ID, EDITION_ID]:
        raise ValueError("Vita abbatum two-edition identity or ordering changed")
    other, edition = form["editions"]
    if len(other.get("acquisition_ids", [])) != 1 or len(edition.get("acquisition_ids", [])) != 1:
        raise ValueError("Vita abbatum acquisition identities changed")
    other_path = (work_path.parent / "forms" / FORM_ID / "editions" / OTHER_EDITION_ID /
                  "acquisitions" / f"{other['acquisition_ids'][0]}.json")
    acquisition_path = (work_path.parent / "forms" / FORM_ID / "editions" / EDITION_ID /
                        "acquisitions" / f"{edition['acquisition_ids'][0]}.json")
    if _sha(root / other_path) != OTHER_ACQUISITION_SHA256:
        raise ValueError("bsb750 edition acquisition changed")
    acquisition = _read(root / acquisition_path)
    if (acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != SOURCE_SHA256
            or acquisition.get("edition_id") != EDITION_ID
            or len(acquisition.get("retained_files", [])) != 2
            or [(item.get("path"), item.get("sha256")) for item in acquisition["retained_files"]]
               != [(PACKAGE.as_posix(), PACKAGE_SHA256), (SOURCE.as_posix(), SOURCE_SHA256)]):
        raise ValueError("bsb754 extracted-XML and ZIP roles changed")
    return work, acquisition, work_path, acquisition_path, other_path


def _candidate(source: etree._Element, work: dict) -> bytes:
    ns = {"t": TEI[1:-1]}
    volumes = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 20:
        raise ValueError("bsb754 source volume changed")
    selected = volumes[0][11]
    if selected.get("n") != "Vita abbatum Acaunensium" or selected.get("type") != "work":
        raise ValueError("bsb754 selected native work changed")
    output = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    output.set(XML_ID, f"ocd-{WORK_ID}-bsb754-electronic-v1")
    file_desc = etree.SubElement(etree.SubElement(output, f"{TEI}teiHeader"), f"{TEI}fileDesc")
    etree.SubElement(etree.SubElement(file_desc, f"{TEI}titleStmt"), f"{TEI}title").text = work["title"]
    original = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original is None:
        raise ValueError("source header missing")
    publication = original.find(f"{TEI}publicationStmt")
    bibliography = original.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError("source publication or bibliography missing")
    file_desc.append(deepcopy(publication))
    etree.SubElement(file_desc, f"{TEI}sourceDesc").append(deepcopy(bibliography))
    etree.SubElement(etree.SubElement(output, f"{TEI}text"), f"{TEI}body").append(deepcopy(selected))
    return etree.tostring(output, encoding="UTF-8", xml_declaration=True)


def prepare(destination: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    destination = destination.absolute()
    if destination == root or root in destination.parents or Path(_io_path(destination)).exists():
        raise ValueError("fresh external candidate destination required")
    source_bytes, tree = _source(root)
    work, acquisition, work_path, acquisition_path, other_path = _work(root)
    candidate = _candidate(tree, work)
    checked = check_candidate(source_bytes, candidate, work, acquisition)
    candidate_path = destination / WORK_ID / "candidate.tei.xml"
    target = Path(_io_path(candidate_path))
    target.parent.mkdir(parents=True)
    target.write_bytes(candidate)
    if errors := validate_file(target):
        raise ValueError(f"TEI P5 XSD failed: {errors[:3]}")
    edition = work["textual_forms"][0]["editions"][1]
    identity = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID}
    revision = f"{WORK_ID}-bsb754-vita-abbatum-v1"
    projection = project_document(target, identity=identity, language="la",
                                  representation_revision=revision, edition_title=edition["title"],
                                  _allow_acceptance_metadata=True, category="prose")
    errors = verify_document(target, projection["rows"], projection["receipt"], identity=identity,
                             language="la", representation_revision=revision,
                             edition_title=edition["title"], _allow_acceptance_metadata=True,
                             category="prose")
    if errors or len(projection["rows"]) != 1:
        raise ValueError(f"native prose projection failed: {errors[:3]}")
    result = {
        "contract": "ocd-openmgh-bsb754-vita-abbatum-direct-v1", "status": "nonaccepted",
        "work_id": WORK_ID, "edition_id": EDITION_ID,
        "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA256,
        "package_path": PACKAGE.as_posix(), "package_sha256": PACKAGE_SHA256,
        "acquisition_receipt": RECEIPT.as_posix(), "acquisition_receipt_sha256": RECEIPT_SHA256,
        "work_path": work_path.as_posix(), "work_sha256": _sha(root / work_path),
        "acquisition_path": acquisition_path.as_posix(),
        "acquisition_sha256": _sha(root / acquisition_path),
        "other_acquisition_path": other_path.as_posix(),
        "other_acquisition_sha256": OTHER_ACQUISITION_SHA256,
        "candidate_path": candidate_path.as_posix(), "candidate_sha256": sha256(candidate).hexdigest(),
        "independent_oracle": checked, "tei_xsd": "pass", "native_prose_rows": 1,
        "native_prose_verify": "pass", "canonical_install": "not-performed",
    }
    Path(_io_path(destination / "receipt.json")).write_bytes(_json(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.destination)
    print(json.dumps({"candidate": result["candidate_path"],
                      "receipt": (args.destination / "receipt.json").as_posix()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
