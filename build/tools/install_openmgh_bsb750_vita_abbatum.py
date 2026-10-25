"""Stage and guarded-install the retained bsb750 Vita abbatum electronic part.

The default preflight is read-only. Stage creation requires an explicit fresh
destination; installation requires the exact reviewed receipt SHA-256.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from lxml import etree

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "vita-sanctorum-abbatum-acaunensium"
FORM_ID = f"{WORK_ID}-openmgh-retained"
EDITION_ID = f"{WORK_ID}-bsb00000750-electronic"
OTHER_EDITION_ID = f"{WORK_ID}-bsb00000754-electronic"
SOURCE = Path("raw/openmgh/bsb00000750/tei/bsb00000750.xml")
SOURCE_SHA = "a88f93a090b6fd452a05b3cbc39a50f7bd7059cd94547f3cd712a4937243f0fc"
PACKAGE = Path("raw/openmgh/bsb00000750/bsb00000750.zip")
PACKAGE_SHA = "71542cfb4f7372efd3908996848052cdf3fcc2a0d7c14348dc16fa407338a22c"
RECEIPT = Path("raw/openmgh/bsb00000750/acquisition-receipt.json")
RECEIPT_SHA = "fae4db8f39ebf080e3a9b499a7bd29b5c26ceef277fb360191753cb5fd7aab5d"
OTHER_SOURCE = Path("raw/openmgh/bsb00000754/tei/bsb00000754.xml")
OTHER_SOURCE_SHA = "3349fbef5e7e957e964433d097e94a4a35d84addcbd6a314a88819e6a53039ff"
OTHER_PACKAGE = Path("raw/openmgh/bsb00000754/bsb00000754.zip")
OTHER_PACKAGE_SHA = "f25422ac5fb447be60d9d6fcc99509a546144224ac68b370c220b89df0a715fe"
OTHER_RECEIPT = Path("raw/openmgh/bsb00000754/acquisition-receipt.json")
OTHER_RECEIPT_SHA = "67f23305c57ba40d40f351393c3dd7408b36bbcdaeef27113fb6bd2b7ee0eeb2"
PART_C14N = "7b29fba6a41ac05280dba98a210e1c37a861d7febc2e4b951852618b700f02fb"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
EVIDENCE = "openmgh-bsb750-vita-abbatum-v1"
REVISION = f"{WORK_ID}-bsb750-electronic-v1"
CONTRACT = "ocd-openmgh-bsb750-vita-abbatum-stage-v1"


def _bytes(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _sha(path: Path) -> str:
    return sha256(_bytes(path)).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _read(path: Path) -> dict:
    value = json.loads(_bytes(path))
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _put(root: Path, relative: Path, data: bytes) -> Path:
    target = root / relative
    output = Path(_io_path(target))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return target


def _put_json(root: Path, relative: Path, value: object) -> Path:
    return _put(root, relative, _json(value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _paths() -> tuple[Path, Path, Path, Path, Path]:
    work = Path("library/works") / WORK_ID
    edition = work / "forms" / FORM_ID / "editions" / EDITION_ID
    other = work / "forms" / FORM_ID / "editions" / OTHER_EDITION_ID
    acquisition = edition / "acquisitions" / f"{WORK_ID}-bsb00000750-acquired.json"
    return work, edition, other, acquisition, work / "state.json"


def _source(root: Path) -> tuple[bytes, etree._Element]:
    for relative, expected in ((SOURCE, SOURCE_SHA), (PACKAGE, PACKAGE_SHA),
                               (RECEIPT, RECEIPT_SHA), (OTHER_SOURCE, OTHER_SOURCE_SHA),
                               (OTHER_PACKAGE, OTHER_PACKAGE_SHA), (OTHER_RECEIPT, OTHER_RECEIPT_SHA)):
        if _sha(root / relative) != expected:
            raise PipelineError(f"retained source dependency changed: {relative}")
    data = _bytes(root / SOURCE)
    with ZipFile(_io_path(root / PACKAGE)) as archive:
        names = archive.namelist()
        if names != ["bsb00000750.xml"] or archive.read(names[0]) != data:
            raise PipelineError("bsb750 ZIP member differs from extracted text authority")
    parsed = etree.fromstring(data, etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    if parsed.getroottree().docinfo.doctype or parsed.tag != f"{TEI}TEI":
        raise PipelineError("entity-free retained TEI required")
    return data, parsed


def _context(root: Path) -> tuple[dict, dict]:
    work_path, _, other_path, acquisition_path, _ = _paths()
    work = _read(root / work_path / "work.json")
    acquisition = _read(root / acquisition_path)
    if (work.get("work_id") != WORK_ID or len(work.get("textual_forms", [])) != 1
            or work["textual_forms"][0].get("textual_form_id") != FORM_ID
            or [e.get("edition_id") for e in work["textual_forms"][0].get("editions", [])]
               != [EDITION_ID, OTHER_EDITION_ID]
            or acquisition.get("edition_id") != EDITION_ID
            or acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != SOURCE_SHA
            or acquisition.get("acquisition_id") != f"{WORK_ID}-bsb00000750-acquired"
            or not Path(_io_path(root / other_path / "acceptance.json")).is_file()):
        raise PipelineError("two-edition work, bsb750 acquisition, or installed bsb754 changed")
    return work, acquisition


def _native_part(source: etree._Element) -> tuple[etree._Element, dict]:
    """Locate the cataloged title by unique endpoints, then inspect its part."""
    ns = {"t": TEI[1:-1], "xml": "http://www.w3.org/XML/1998/namespace"}
    works = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']/t:div[@type='work']", namespaces=ns)
    first = source.xpath("//*[@xml:id='bsb00000750_00182_32']", namespaces=ns)
    last = source.xpath("//*[@xml:id='bsb00000750_00189_21']", namespaces=ns)
    if len(works) != 39 or len(first) != 1 or len(last) != 1:
        raise PipelineError("bsb750 volume or catalog endpoint changed")
    containing = [w for w in works if first[0] in w.iter() and last[0] in w.iter()]
    if len(containing) != 1 or containing[0] is not works[13] or works[13].get("n") != "Vita abb. Acaunensium":
        raise PipelineError("catalog endpoints do not identify the expected work division")
    parts = list(works[13])
    if (len(parts) != 3 or any(p.tag != f"{TEI}div" or p.get("type") != "part" for p in parts)
            or first[0] not in parts[0].iter() or last[0] not in parts[0].iter()):
        raise PipelineError("three native parts or first-part boundary changed")
    opening = " ".join(" ".join(parts[0].itertext()).split())
    later = [" ".join(" ".join(p.itertext()).split()) for p in parts[1:]]
    if (not opening.startswith("I. VITA SANCTORUM ABBATUM ACAUNENSIUM.")
            or not opening.endswith("EXPLICIT FILICITER .")
            or not later[0].startswith("II. INCIPIUNT VERSUS DE VITA SANCTI PROBI.")
            or not later[1].startswith("III. Catalogus abbatum Acaunensium.")):
        raise PipelineError("source-attested part titles or explicit ending changed")
    part = parts[0]
    c14n = sha256(etree.tostring(part, method="c14n", with_comments=True)).hexdigest()
    ids = [node.get(XML_ID) for node in part.iter() if node.get(XML_ID)]
    lines = part.xpath(".//t:lb", namespaces=ns)
    pages = part.xpath(".//t:pb", namespaces=ns)
    tags = {tag: len(part.xpath(f".//t:{tag}", namespaces=ns))
            for tag in ("ab", "lb", "pb", "w", "hi", "note", "gap", "unclear")}
    if (c14n != PART_C14N or len(ids) != len(set(ids))
            or lines[0].get(XML_ID) != "bsb00000750_00182_32"
            or lines[-1].get(XML_ID) != "bsb00000750_00189_21"
            or tags != {"ab": 1, "lb": 233, "pb": 8, "w": 86, "hi": 4,
                        "note": 0, "gap": 0, "unclear": 0}):
        raise PipelineError("complete first native part changed")
    local = set(ids)
    for node in part.iter():
        for attr in ("target", "corresp", "sameAs", "ana"):
            for value in (node.get(attr) or "").split():
                if value.startswith("#") and value[1:] not in local:
                    raise PipelineError(f"selected part has an external fragment: {value}")
    return part, {"source_work_index": 13, "source_volume_works": 39,
                  "source_part_index": 0, "source_sibling_parts": 2,
                  "selected_c14n_sha256": c14n, "source_xml_id_count": len(ids),
                  "line_count": len(lines), "page_count": len(pages), "tags": tags,
                  "first_id": lines[0].get(XML_ID), "last_id": lines[-1].get(XML_ID),
                  "following_titles": [later[0][:72], later[1][:72]]}


def _candidate(source: etree._Element, work: dict) -> bytes:
    ns = {"t": TEI[1:-1]}
    selected = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']/t:div[@type='work'][14]/t:div[@type='part'][1]", namespaces=ns)
    if len(selected) != 1:
        raise PipelineError("selected native part missing")
    output = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    output.set(XML_ID, f"ocd-{WORK_ID}-bsb750-electronic-v1")
    file_desc = etree.SubElement(etree.SubElement(output, f"{TEI}teiHeader"), f"{TEI}fileDesc")
    etree.SubElement(etree.SubElement(file_desc, f"{TEI}titleStmt"), f"{TEI}title").text = work["title"]
    original = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original is None:
        raise PipelineError("source header missing")
    publication = original.find(f"{TEI}publicationStmt")
    bibliography = original.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise PipelineError("source publication or bibliography missing")
    file_desc.append(deepcopy(publication))
    etree.SubElement(file_desc, f"{TEI}sourceDesc").append(deepcopy(bibliography))
    etree.SubElement(etree.SubElement(output, f"{TEI}text"), f"{TEI}body").append(deepcopy(selected[0]))
    return etree.tostring(output, encoding="UTF-8", xml_declaration=True)


def _equal_native(left: etree._Element, right: etree._Element, *, outer: bool = False) -> bool:
    if (left.tag != right.tag or dict(left.attrib) != dict(right.attrib)
            or left.text != right.text or len(left) != len(right)
            or (not outer and left.tail != right.tail)):
        return False
    return all(_equal_native(a, b) for a, b in zip(left, right, strict=True))


def _check(source_bytes: bytes, candidate: bytes, work: dict, acquisition: dict) -> dict:
    source = etree.fromstring(source_bytes, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    selected, detail = _native_part(source)
    edition = work["textual_forms"][0]["editions"][0]
    locator = f"{SOURCE.as_posix()}#bsb00000750_00182_32; {SOURCE.as_posix()}#bsb00000750_00189_21"
    if (edition["containing_source"]["locator"] != locator
            or edition["acquisition_ids"] != [acquisition["acquisition_id"]]):
        raise PipelineError("catalog work/edition locator changed")
    parsed = etree.fromstring(candidate, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))
    body = parsed.find(f"{TEI}text/{TEI}body")
    if (body is None or len(body) != 1
            or parsed.get(XML_ID) != f"ocd-{WORK_ID}-bsb750-electronic-v1"
            or not _equal_native(body[0], selected, outer=True)):
        raise PipelineError("candidate differs from complete source-native first part")
    old = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    new = parsed.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if old is None or new is None or new.find(f"{TEI}titleStmt/{TEI}title").text != work["title"]:
        raise PipelineError("candidate title or source header missing")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        a, b = old.find(suffix), new.find(suffix)
        if a is None or b is None or not _equal_native(a, b, outer=True):
            raise PipelineError("source electronic publication or bibliography changed")
    return {"status": "pass", "source_sha256": SOURCE_SHA, **detail}


def candidate_only(output: Path) -> dict:
    source_bytes, parsed = _source(ROOT)
    work, acquisition = _context(ROOT)
    candidate = _candidate(parsed, work)
    checked = _check(source_bytes, candidate, work, acquisition)
    output = output.absolute()
    if Path(_io_path(output)).exists():
        raise PipelineError("candidate output must be fresh")
    Path(_io_path(output)).parent.mkdir(parents=True, exist_ok=True)
    Path(_io_path(output)).write_bytes(candidate)
    if errors := validate_file(Path(_io_path(output))):
        raise PipelineError(f"candidate TEI P5 XSD failed: {errors[:3]}")
    edition = work["textual_forms"][0]["editions"][0]
    identity = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID}
    projection = project_document(Path(_io_path(output)), identity=identity, language="la",
                                  representation_revision=REVISION, edition_title=edition["title"],
                                  _allow_acceptance_metadata=True, category="prose")
    failures = verify_document(Path(_io_path(output)), projection["rows"], projection["receipt"],
                               identity=identity, language="la", representation_revision=REVISION,
                               edition_title=edition["title"], _allow_acceptance_metadata=True,
                               category="prose")
    if failures or len(projection["rows"]) != 1:
        raise PipelineError(f"candidate native prose projection failed: {failures[:3]}")
    return {"candidate": output.as_posix(), "candidate_sha256": sha256(candidate).hexdigest(),
            "source_check": checked, "projection_rows": 1}


def stage(destination: Path) -> dict:
    root = ROOT.resolve(strict=True)
    destination = destination.absolute()
    if (destination == root or root in destination.parents or destination in root.parents
            or Path(_io_path(destination)).exists()):
        raise PipelineError("fresh external stage required")
    work_rel, edition_rel, other_rel, acquisition_rel, state_rel = _paths()
    source_bytes, parsed = _source(root)
    work, acquisition = _context(root)
    if Path(_io_path(root / edition_rel / "acceptance.json")).exists():
        raise PipelineError("bsb750 already accepted")
    candidate = _candidate(parsed, work)
    checked = _check(source_bytes, candidate, work, acquisition)
    destination.mkdir(parents=True)
    for relative in (SOURCE, PACKAGE, RECEIPT, OTHER_SOURCE, OTHER_PACKAGE, OTHER_RECEIPT):
        target = Path(_io_path(destination / relative))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(root / relative), target)
    before = _files(root / work_rel)
    shutil.copytree(_io_path(root / work_rel), _io_path(destination / work_rel))
    evidence = work_rel / "integration" / EVIDENCE
    direct = _put(destination, evidence / "inputs/candidate.tei.xml", candidate)
    if errors := validate_file(Path(_io_path(direct))):
        raise PipelineError(f"candidate TEI P5 XSD failed: {errors[:3]}")
    with TemporaryDirectory(prefix="bsb750-vita-repro-", dir=destination) as temp:
        reproduced = Path(temp) / "candidate.tei.xml"
        process = subprocess.run([sys.executable, "-m", "build.tools.install_openmgh_bsb750_vita_abbatum",
                                  "--candidate-only", str(reproduced)],
                                 cwd=root, check=True, capture_output=True, text=True)
        if not process.stdout.strip() or _bytes(reproduced) != candidate:
            raise PipelineError("clean-process candidate bytes differ")
    revised = _read(destination / work_rel / "work.json")
    revised["textual_forms"][0]["editions"][0].update(category="prose", language="la")
    if revised["textual_forms"][0]["editions"][1] != work["textual_forms"][0]["editions"][1]:
        raise PipelineError("accepted bsb754 edition metadata changed")
    validate_identity_update(work, revised)
    _put_json(destination, work_rel / "work.json", revised)
    load_work(Path(_io_path(destination / work_rel / "work.json")))
    scope_text = ("The complete first native part of bsb00000750 work division 14, "
                  "Vita sanctorum abbatum Acaunensium, from bsb00000750_00182_32 "
                  "through its explicit ending at bsb00000750_00189_21. Its separately "
                  "headed Probus verses and abbot catalog remain retained sibling parts "
                  "outside this edition selection. Bsb00000754 is a separate accepted "
                  "electronic edition; no print witness was collated.")
    identity = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID,
                "acquisition_id": acquisition["acquisition_id"]}
    revision = {"id": REVISION, "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Accept the source-attested first bsb750 part as a separate electronic edition."}
    derived = bind_reviewed_header(candidate, expected_sha256=sha256(candidate).hexdigest(),
                                   identity=identity,
                                   source={"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
                                           "source_bytes": len(source_bytes), "source_scope": scope_text},
                                   source_url=acquisition["url"], declared_scope=scope_text,
                                   revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != candidate.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("accepted header binding changed source body")
    candidate_path = _put(destination, evidence / "candidate.tei.xml", derived)
    if errors := validate_file(Path(_io_path(candidate_path))):
        raise PipelineError(f"accepted TEI P5 XSD failed: {errors[:3]}")
    expected = [{"path": PACKAGE.as_posix(), "position": 1}, {"path": SOURCE.as_posix(), "position": 2}]
    included = [{"path": SOURCE.as_posix(), "position": 2, "bytes": len(source_bytes),
                 "sha256": SOURCE_SHA, "scope": scope_text}]
    excluded = [{"path": PACKAGE.as_posix(), "position": 1,
                 "reason": "ZIP is acquisition packaging; the extracted XML is text authority."}]
    common = {"identity": identity,
              "source": {key: acquisition[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope")},
              "candidate": make_file_binding(destination, candidate_path),
              "scope": scope_text, "accepted_scope": {"kind": "selection", "declared": scope_text},
              "expected_members": expected, "included_members": included,
              "excluded_members": excluded, "missing_members": [], "unknown_members": []}
    account = _put_json(destination, evidence / "source-accounting.json", common | {
        "scope": acquisition["source_scope"],
        "source_sha256": SOURCE_SHA, "source_bytes": len(source_bytes),
        "source_check": checked, "source_part_c14n_sha256": PART_C14N,
        "unselected_parts": ["Verses on St. Probus", "Catalog of Acaunum abbots"],
        "direct_candidate_sha256": sha256(candidate).hexdigest(),
    })
    proof = common | {"status": "pass", "command": "py -3 -m build.tools.install_openmgh_bsb750_vita_abbatum --stage",
                      "exit_code": 0, "source_check": checked, "tei_xsd": "pass",
                      "clean_process_reproduction": "pass", "accepted_body_unchanged": True}
    technical = {"producer": {"id": "ocd-openmgh-bsb750-vita-abbatum-part-v1"},
                 "checker": {"id": "ocd-openmgh-bsb750-vita-abbatum-source-part-oracle-v1"},
                 "shared_assumptions": ["Producer and checker parse the same retained XML; the checker independently locates unique catalog endpoints, source part titles, the explicit ending, and all native nodes."],
                 "independent_corroboration": "Catalog endpoints, source part boundary, complete native C14N, TEI P5, clean-process reproduction, and native prose row agree."}
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(destination, evidence / f"{name}.json", proof | {"claim": name})
        technical[name] = {"path": path, "status": "pass", "command": proof["command"], "exit_code": 0}
    reviewed_at = _now()
    review = {"reviewer": f"agent:{WORK_ID}-bsb750-source-part-review", "reviewed_at": reviewed_at,
              "coverage": {"status": "unavailable", "declared": scope_text,
                           "reached": ["retained bsb750 first part", "retained bsb750 part titles and ending",
                                       "exact candidate/source tree comparison"],
                           "inspected": ["retained bsb750 part titles and ending", "exact candidate/source tree comparison"],
                           "unreviewed": ["close CVW visual source/TEI comparison"]},
              "source_quality_uncertainty": ["No print witness was collated."],
              "discrepancies": [], "unreviewed_residuals": ["Visual and human review remain unrecorded."]}
    review_path = _put_json(destination, evidence / "review.json", common | review)
    decision = {"source_local_disposition": "Agent acceptance of the complete first source-native bsb750 part only.",
                "blockers": [],
                "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                                     "assessed_at": reviewed_at, "supported_scope": scope_text,
                                     "unresolved_claims": [],
                                     "unassessed_stronger_claims": ["close visual review", "human acceptance", "print collation", "rights clearance", "publication"]},
                "human_decision": {"status": "not-recorded"}}
    acceptance = build_acceptance_record(
        destination, identity=identity, candidate_path=candidate_path,
        source_accounting_path=account,
        scope={"kind": "selection", "declared": scope_text,
               "expected_members": expected, "included_members": included, "excluded_members": excluded},
        technical=technical, review=review | {"report_path": review_path},
        representation_revision=revision, decision=decision)
    acceptance_path = edition_rel / "acceptance.json"
    master_path = edition_rel / "master.tei.xml"
    write_acceptance(Path(_io_path(destination / acceptance_path)), acceptance)
    _put(destination, master_path, derived)
    acceptance["promotion"] = dict(acceptance["promotion"])
    acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                   master=make_file_binding(destination, destination / master_path))
    write_acceptance(Path(_io_path(destination / acceptance_path)), acceptance)
    state = _read(destination / state_rel)
    targets = [target for target in state["targets"]
               if target["target_type"] == "edition" and target["target_id"] == EDITION_ID]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise PipelineError("bsb750 edition target is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    targets[0]["evidence"].extend([master_path.as_posix(), acceptance_path.as_posix()])
    _put_json(destination, state_rel, state)
    _put(destination, edition_rel / "README.source.md", (
        f"# Source and attribution for {WORK_ID}, bsb00000750\n\n"
        "Text witness: extracted openMGH bsb00000750 TEI XML, first native part only. "
        "The Monumenta Germaniae Historica and Bavarian State Library, Munich, "
        "request attribution for copies or derivatives of the electronic file. "
        "Its publication statement labels digital annotations CC BY 4.0 and "
        "describes the underlying text as believed public domain. See the retained "
        "TEI header for the exact statement. This note is not rights clearance.\n").encode())
    validate_acceptance(destination / acceptance_path, root=destination)
    validate_state(destination / state_rel, root=destination)
    projected = project_accepted_prose(destination, acceptance_path=destination / acceptance_path)
    failures = verify_accepted_prose(destination, acceptance_path=destination / acceptance_path,
                                     rows=projected["rows"], receipt=projected["receipt"])
    if failures or len(projected["rows"]) != 1:
        raise PipelineError(f"actual-master native prose projection failed: {failures[:3]}")
    if (_files(destination / other_rel) != _files(root / other_rel)
            or _read(destination / state_rel)["targets"][2:]
               != _read(root / state_rel)["targets"][2:]):
        raise PipelineError("accepted bsb754 edition or state target changed")
    result = {"contract": CONTRACT, "status": "staged-only", "work_id": WORK_ID,
              "edition_id": EDITION_ID, "canonical_root": root.as_posix(),
              "stage_root": destination.as_posix(), "source_path": SOURCE.as_posix(),
              "source_sha256": SOURCE_SHA, "source_check": checked,
              "before": before, "after": _files(destination / work_rel),
              "master_sha256": _sha(destination / master_path),
              "acceptance_sha256": _sha(destination / acceptance_path),
              "candidate_sha256": sha256(candidate).hexdigest(),
              "projection_rows": 1, "projection_status": "independent-check-pass",
              "installation": "not-performed"}
    _put_json(destination, Path("stage-receipt.json"), result)
    return result


def preflight(receipt: Path, expected_sha256: str) -> dict:
    receipt = receipt.resolve(strict=True)
    if _sha(receipt) != expected_sha256:
        raise PipelineError("exact reviewed stage receipt hash changed")
    record = _read(receipt)
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage_root = Path(record["stage_root"]).resolve(strict=True)
    work_rel, edition_rel, other_rel, acquisition_rel, state_rel = _paths()
    if (record.get("contract") != CONTRACT or record.get("status") != "staged-only"
            or record.get("work_id") != WORK_ID or record.get("edition_id") != EDITION_ID
            or record.get("source_path") != SOURCE.as_posix()
            or record.get("source_sha256") != SOURCE_SHA
            or record.get("projection_rows") != 1
            or record.get("projection_status") != "independent-check-pass"
            or record.get("installation") != "not-performed"
            or root != ROOT.resolve(strict=True) or receipt != stage_root / "stage-receipt.json"
            or _files(root / work_rel) != record["before"]
            or _files(stage_root / work_rel) != record["after"]):
        raise PipelineError("reviewed stage or canonical preimage differs")
    source_bytes, _ = _source(root)
    work, acquisition = _context(root)
    staged_source, _ = _source(stage_root)
    if staged_source != source_bytes:
        raise PipelineError("staged retained source differs")
    candidate = _bytes(stage_root / work_rel / "integration" / EVIDENCE / "inputs/candidate.tei.xml")
    if (sha256(candidate).hexdigest() != record["candidate_sha256"]
            or _check(source_bytes, candidate, work, acquisition) != record["source_check"]):
        raise PipelineError("reviewed source/candidate oracle changed")
    if (_sha(stage_root / edition_rel / "master.tei.xml") != record["master_sha256"]
            or _sha(stage_root / edition_rel / "acceptance.json") != record["acceptance_sha256"]
            or _files(stage_root / other_rel) != _files(root / other_rel)
            or _read(stage_root / state_rel)["targets"][2:] != _read(root / state_rel)["targets"][2:]):
        raise PipelineError("staged master, acceptance, or bsb754 preservation changed")
    if Path(_io_path(root / edition_rel / "master.tei.xml")).exists():
        raise PipelineError("bsb750 already has a canonical master")
    validate_acceptance(stage_root / edition_rel / "acceptance.json", root=stage_root)
    validate_state(stage_root / state_rel, root=stage_root)
    if errors := validate_file(Path(_io_path(stage_root / edition_rel / "master.tei.xml"))):
        raise PipelineError(f"staged master TEI P5 XSD failed: {errors[:3]}")
    projection = project_accepted_prose(stage_root,
                                        acceptance_path=stage_root / edition_rel / "acceptance.json")
    failures = verify_accepted_prose(stage_root,
                                     acceptance_path=stage_root / edition_rel / "acceptance.json",
                                     rows=projection["rows"], receipt=projection["receipt"])
    if failures or len(projection["rows"]) != 1:
        raise PipelineError(f"staged actual-master projection failed: {failures[:3]}")
    return {"status": "ready-for-review", "work_id": WORK_ID,
            "before_files": len(record["before"]), "after_files": len(record["after"]),
            "projection_rows": 1, "installation": "not-performed"}


def install(receipt: Path, expected_sha256: str) -> dict:
    preflight(receipt, expected_sha256)
    record = _read(receipt)
    stage_root = Path(record["stage_root"]).resolve(strict=True)
    work_rel, _, _, _, _ = _paths()
    target = ROOT / work_rel
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        preflight(receipt, expected_sha256)
        return _commit_generation(ROOT, target, stage_root / work_rel,
                                  work_id=WORK_ID, before=record["before"],
                                  after=record["after"], existed=True, replacement=False,
                                  operation_kind="openmgh-bsb750-vita-abbatum-edition-install",
                                  result_status="installed-and-validated", accepted_editions=1,
                                  fail_at=None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--candidate-only", type=Path)
    group.add_argument("--stage", type=Path)
    group.add_argument("--receipt", type=Path)
    parser.add_argument("--sha256", help="Exact reviewed stage receipt SHA-256 for preflight/apply")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.candidate_only:
        result = candidate_only(args.candidate_only)
    elif args.stage:
        if args.apply or args.sha256:
            parser.error("stage creation does not accept --apply or --sha256")
        result = stage(args.stage)
    else:
        if not args.sha256 or len(args.sha256) != 64:
            parser.error("--receipt requires its exact --sha256")
        result = install(args.receipt, args.sha256) if args.apply else preflight(args.receipt, args.sha256)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
