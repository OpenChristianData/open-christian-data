"""Prepare the exact bsb754 Vita Rigoberti electronic candidate; never install."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from build.tei.openmgh_bsb754_rigoberti_oracle import (
    FIRST_CHILD,
    LAST_CHILD,
    NEXT_CHILD,
    SOURCE_PATH,
    SOURCE_SHA256,
    TEI_NS,
    check_candidate,
)
from ocd_kernel.projection.categories.native_documents import (
    project_document,
    verify_document,
)
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "vita-sancti-rigoberti"
FORM_ID = f"{WORK_ID}-openmgh-retained"
EDITION_ID = f"{WORK_ID}-openmgh-electronic"
SOURCE = Path(SOURCE_PATH)
PACKAGE = Path("raw/openmgh/bsb00000754/bsb00000754.zip")
PACKAGE_SHA256 = "f25422ac5fb447be60d9d6fcc99509a546144224ac68b370c220b89df0a715fe"
ACQUISITION_RECEIPT = Path("raw/openmgh/bsb00000754/acquisition-receipt.json")
ACQUISITION_RECEIPT_SHA256 = "67f23305c57ba40d40f351393c3dd7408b36bbcdaeef27113fb6bd2b7ee0eeb2"
ACQUISITION_ID = "vita-sancti-rigoberti-openmgh-acquired"
REVISION_ID = f"{WORK_ID}-bsb754-vita-v1"
REVISION_DATE = "2026-10-01"
REVISION_NOTE = "Accept the exact section-I Vita span; exclude the adjacent 894 and arm translations."
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(Path(_io_path(path)).read_bytes())


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _source(root: Path) -> tuple[bytes, etree._Element]:
    source_path = Path(_io_path(root / SOURCE))
    package_path = Path(_io_path(root / PACKAGE))
    receipt_path = Path(_io_path(root / ACQUISITION_RECEIPT))
    source_bytes = source_path.read_bytes()
    if _sha_bytes(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained source XML hash differs")
    if _sha(package_path) != PACKAGE_SHA256:
        raise ValueError("retained ZIP package hash differs")
    if _sha(receipt_path) != ACQUISITION_RECEIPT_SHA256:
        raise ValueError("openMGH acquisition receipt hash differs")
    with ZipFile(package_path) as archive:
        if archive.namelist() != ["bsb00000754.xml"]:
            raise ValueError("retained ZIP package member set changed")
        if archive.read("bsb00000754.xml") != source_bytes:
            raise ValueError("retained ZIP package does not contain the exact TEI source")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_comments=False,
        huge_tree=True,
    )
    source = etree.fromstring(source_bytes, parser)
    if source.getroottree().docinfo.doctype:
        raise ValueError("DOCTYPE is forbidden in retained source")
    return source_bytes, source


def _authority(root: Path) -> tuple[dict, dict, dict, Path, Path]:
    work_path = Path("library/works") / WORK_ID / "work.json"
    state_path = work_path.with_name("state.json")
    work = _read(root / work_path)
    state = _read(root / state_path)
    if work.get("work_id") != WORK_ID or state.get("work_id") != WORK_ID:
        raise ValueError("canonical work identity changed")
    forms = work.get("textual_forms", [])
    if len(forms) != 1 or forms[0].get("textual_form_id") != FORM_ID:
        raise ValueError("textual form identity changed")
    editions = forms[0].get("editions", [])
    if len(editions) != 1 or editions[0].get("edition_id") != EDITION_ID:
        raise ValueError("edition identity changed")
    edition = editions[0]
    if edition.get("acquisition_ids") != [ACQUISITION_ID]:
        raise ValueError("edition acquisition identity changed")
    acquisition_path = (
        work_path.parent
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
        / "acquisitions"
        / f"{ACQUISITION_ID}.json"
    )
    acquisition = _read(root / acquisition_path)
    if (
        acquisition.get("acquisition_id") != ACQUISITION_ID
        or acquisition.get("edition_id") != EDITION_ID
        or acquisition.get("source_path") != SOURCE.as_posix()
        or acquisition.get("source_sha256") != SOURCE_SHA256
        or acquisition.get("url") != "https://data.mgh.de/openmgh/bsb00000754.zip"
        or len(acquisition.get("retained_files", [])) != 2
        or [item.get("path") for item in acquisition["retained_files"]]
        != [PACKAGE.as_posix(), SOURCE.as_posix()]
        or [item.get("sha256") for item in acquisition["retained_files"]]
        != [PACKAGE_SHA256, SOURCE_SHA256]
    ):
        raise ValueError("edition acquisition no longer binds the exact XML and package")
    targets = state.get("targets", [])
    edition_targets = [
        item
        for item in targets
        if item.get("target_type") == "edition" and item.get("target_id") == EDITION_ID
    ]
    acquisition_targets = [
        item
        for item in targets
        if item.get("target_type") == "acquisition"
        and item.get("target_id") == ACQUISITION_ID
    ]
    if (
        len(edition_targets) != 1
        or edition_targets[0].get("stage") != "acquired"
        or len(acquisition_targets) != 1
        or acquisition_targets[0].get("stage") != "acquired"
    ):
        raise ValueError("the exact edition and acquisition must still be acquired")
    edition_root = work_path.parent / "forms" / FORM_ID / "editions" / EDITION_ID
    for relative in (edition_root / "acceptance.json", edition_root / "master.tei.xml"):
        if Path(_io_path(root / relative)).exists():
            raise ValueError("an accepted master already exists for this edition")
    return work, state, acquisition, work_path, acquisition_path


def _candidate(source: etree._Element, work: dict) -> bytes:
    namespace = {"t": TEI_NS}
    carriers = source.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='volume']"
        "/t:div[@n='Vita Eucherii']/t:ab",
        namespaces=namespace,
    )
    if len(carriers) != 1:
        raise ValueError("the single flat bsb754 source carrier is missing or ambiguous")
    children = list(carriers[0])
    if len(children) != 1249:
        raise ValueError("the inspected bsb754 carrier child count changed")
    if (
        children[FIRST_CHILD].get(XML_ID) != "bsb00000754_00068"
        or children[LAST_CHILD].get(XML_ID) != "bsb00000754_00088_12"
        or children[NEXT_CHILD].get(XML_ID) != "bsb00000754_00088_13"
    ):
        raise ValueError("the selected source span or next-section boundary changed")
    selected = children[FIRST_CHILD : LAST_CHILD + 1]
    result = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    result.set(XML_ID, f"ocd-{WORK_ID}-bsb754-electronic-v1")
    header = etree.SubElement(result, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title").text = work["title"]
    source_file_desc = source.find(
        f"{{{TEI_NS}}}teiHeader/{{{TEI_NS}}}fileDesc"
    )
    if source_file_desc is None:
        raise ValueError("source file description is missing")
    publication = source_file_desc.find(f"{{{TEI_NS}}}publicationStmt")
    bibliography = source_file_desc.find(
        f"{{{TEI_NS}}}sourceDesc/{{{TEI_NS}}}biblFull"
    )
    if publication is None or bibliography is None:
        raise ValueError("source publication statement or bibliography is missing")
    file_desc.append(deepcopy(publication))
    etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc").append(
        deepcopy(bibliography)
    )
    revision = etree.SubElement(header, f"{{{TEI_NS}}}revisionDesc")
    etree.SubElement(
        revision,
        f"{{{TEI_NS}}}change",
        when=REVISION_DATE,
    ).text = "Prepared from the retained source as a nonaccepted candidate."
    body = etree.SubElement(etree.SubElement(result, f"{{{TEI_NS}}}text"), f"{{{TEI_NS}}}body")
    work_div = etree.SubElement(
        body,
        f"{{{TEI_NS}}}div",
        type="work",
        n=work["title"],
    )
    ab = etree.SubElement(work_div, f"{{{TEI_NS}}}ab")
    for child in selected:
        ab.append(deepcopy(child))
    return etree.tostring(result, encoding="UTF-8", xml_declaration=True)


def _challenge(source_bytes: bytes, candidate_bytes: bytes) -> dict[str, str]:
    namespace = {"t": TEI_NS}
    root = etree.fromstring(candidate_bytes)
    body = root.xpath("/t:TEI/t:text/t:body/t:div[@type='work']/t:ab", namespaces=namespace)[0]
    cases: dict[str, bytes] = {}

    omitted = deepcopy(root)
    omitted.xpath("/t:TEI/t:text/t:body/t:div[@type='work']/t:ab", namespaces=namespace)[0].remove(
        omitted.xpath("/t:TEI/t:text/t:body/t:div[@type='work']/t:ab", namespaces=namespace)[0][-1]
    )
    cases["omit-vita-final-line"] = etree.tostring(
        omitted, encoding="UTF-8", xml_declaration=True
    )

    include_next = deepcopy(root)
    include_next.xpath("/t:TEI/t:text/t:body/t:div[@type='work']/t:ab", namespaces=namespace)[0].append(
        deepcopy(
            etree.fromstring(source_bytes).xpath(
                "/t:TEI/t:text/t:body/t:div[@type='volume']"
                "/t:div[@n='Vita Eucherii']/t:ab",
                namespaces=namespace,
            )[0][NEXT_CHILD]
        )
    )
    cases["include-translation-II"] = etree.tostring(
        include_next, encoding="UTF-8", xml_declaration=True
    )

    changed_text = deepcopy(root)
    changed_body = changed_text.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='work']/t:ab", namespaces=namespace
    )[0]
    changed_body[-1].tail = (changed_body[-1].tail or "") + " MUTATION"
    cases["alter-final-text"] = etree.tostring(
        changed_text, encoding="UTF-8", xml_declaration=True
    )

    rejected: dict[str, str] = {}
    for name, mutated in cases.items():
        try:
            check_candidate(source_bytes, mutated)
        except ValueError as error:
            rejected[name] = str(error)
        else:
            raise ValueError(f"independent oracle accepted mutation: {name}")
    try:
        check_candidate(source_bytes + b" ", candidate_bytes)
    except ValueError as error:
        rejected["substitute-source-bytes"] = str(error)
    else:
        raise ValueError("independent oracle accepted substituted source bytes")
    if len(rejected) != 4:
        raise ValueError("not all required source-oracle mutations were rejected")
    return rejected


def prepare(destination: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    destination = destination.absolute()
    if (
        destination == root
        or root in destination.parents
        or Path(_io_path(destination)).exists()
    ):
        raise ValueError("a fresh external candidate destination is required")
    source_bytes, source = _source(root)
    work, state, acquisition, work_path, acquisition_path = _authority(root)
    candidate = _candidate(source, work)
    oracle = check_candidate(source_bytes, candidate)
    if errors := validate_file_bytes(candidate):
        raise ValueError(f"candidate TEI P5 validation failed: {errors[:3]}")
    edition = work["textual_forms"][0]["editions"][0]
    identity = {
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
    }
    revision = f"{WORK_ID}-bsb754-vita-v1"
    candidate_path = destination / WORK_ID / "candidate.tei.xml"
    target = Path(_io_path(candidate_path))
    target.parent.mkdir(parents=True)
    target.write_bytes(candidate)
    projection = project_document(
        candidate_path,
        identity=identity,
        language="la",
        representation_revision=revision,
        edition_title=edition["title"],
        _allow_acceptance_metadata=True,
        category="prose",
    )
    projection_errors = verify_document(
        candidate_path,
        projection["rows"],
        projection["receipt"],
        identity=identity,
        language="la",
        representation_revision=revision,
        edition_title=edition["title"],
        _allow_acceptance_metadata=True,
        category="prose",
    )
    if projection_errors or len(projection["rows"]) != 1:
        raise ValueError(f"native prose projection failed: {projection_errors[:3]}")
    record = {
        "contract": "ocd-openmgh-bsb754-rigoberti-direct-v1",
        "status": "nonaccepted",
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "source_path": SOURCE.as_posix(),
        "source_sha256": SOURCE_SHA256,
        "source_bytes": len(source_bytes),
        "package_path": PACKAGE.as_posix(),
        "package_sha256": PACKAGE_SHA256,
        "package_contains_exact_source": True,
        "acquisition_receipt": ACQUISITION_RECEIPT.as_posix(),
        "acquisition_receipt_sha256": ACQUISITION_RECEIPT_SHA256,
        "work_path": work_path.as_posix(),
        "work_sha256": _sha(root / work_path),
        "state_path": work_path.with_name("state.json").as_posix(),
        "state_sha256": _sha(root / work_path.with_name("state.json")),
        "acquisition_path": acquisition_path.as_posix(),
        "acquisition_sha256": _sha(root / acquisition_path),
        "candidate_path": candidate_path.as_posix(),
        "candidate_sha256": _sha_bytes(candidate),
        "source_oracle": oracle,
        "mutation_challenges": _challenge(source_bytes, candidate),
        "tei_p5": "pass",
        "native_prose_rows": 1,
        "native_prose_verification": "pass",
        "native_row": projection["rows"][0],
        "native_receipt": projection["receipt"],
        "canonical_install": "not-performed",
        "human_review": "not-recorded",
        "rights_clearance": "not-recorded",
    }
    Path(_io_path(destination / "receipt.json")).write_bytes(_json(record))
    return record


def validate_file_bytes(data: bytes) -> list[str]:
    """Validate in-memory TEI through the maintained validator's temp-file API."""

    from tempfile import TemporaryDirectory

    with TemporaryDirectory(prefix="rigoberti-p5-") as temporary:
        path = Path(temporary) / "candidate.tei.xml"
        path.write_bytes(data)
        return validate_file(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.destination)
    print(
        json.dumps(
            {
                "candidate": result["candidate_path"],
                "candidate_sha256": result["candidate_sha256"],
                "receipt": (args.destination / "receipt.json").as_posix(),
                "row_count": result["native_prose_rows"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
