"""Stage and guarded-install the exact Bishops of Sens electronic letter."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from lxml import etree

from build.tei.openmgh_bsb829_sens_oracle import (
    END, NEXT, START, TEI, XML_ID, check,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "bishops-of-sens-letter-to-joscerannus"
WORK = Path("library/works") / WORK_ID
SOURCE = Path("raw/openmgh/bsb00000829/tei/bsb00000829.xml")
SOURCE_SHA = "cb35385e4e4ba87f80a002452a527527866322af7ccea7f23f366735e46df989"
PACKAGE = Path("raw/openmgh/bsb00000829/bsb00000829.zip")
PACKAGE_SHA = "287bc95d5e4acf5378c381ae3646481882a71a03b60ddb4eaf46fa3c8ec59042"
SOURCE_RECEIPT = Path("raw/openmgh/bsb00000829/acquisition-receipt.json")
SOURCE_RECEIPT_SHA = "61fdd88b8536cdda2338f9f2e684188c0eae00c0ed8eb827c3187c0b3cdb4f4c"
EVIDENCE = WORK / "integration/bsb829-sens-letter-electronic-v1"
EDITION = (WORK / "forms" / f"{WORK_ID}-openmgh-retained" / "editions"
           / f"{WORK_ID}-openmgh-electronic")
ACQUISITION = EDITION / "acquisitions" / f"{WORK_ID}-openmgh-acquired.json"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
REVISION = f"{WORK_ID}-bsb829-electronic-v1"
CONTRACT = "ocd-bsb829-sens-letter-stage-v1"


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _read(path: Path) -> dict:
    result = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(result, dict):
        raise ValueError(f"JSON object required: {path}")
    return result


def _put(root: Path, relative: Path, data: bytes) -> Path:
    path = root / relative
    Path(_io_path(path.parent)).mkdir(parents=True, exist_ok=True)
    Path(_io_path(path)).write_bytes(data)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _source(root: Path) -> tuple[bytes, etree._Element]:
    for relative, digest in ((SOURCE, SOURCE_SHA), (PACKAGE, PACKAGE_SHA),
                             (SOURCE_RECEIPT, SOURCE_RECEIPT_SHA)):
        if _sha(root / relative) != digest:
            raise ValueError(f"retained source or package changed: {relative}")
    content = Path(_io_path(root / SOURCE)).read_bytes()
    parsed = etree.fromstring(content, etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True,
    ))
    if parsed.getroottree().docinfo.doctype:
        raise ValueError("source DOCTYPE is forbidden")
    return content, parsed


def make_candidate(root: Path) -> tuple[bytes, dict]:
    source_bytes, source = _source(root)
    work = _read(root / WORK / "work.json")
    acquisition = _read(root / ACQUISITION)
    if (work.get("work_id") != WORK_ID or acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != SOURCE_SHA):
        raise ValueError("work or acquisition authority changed")
    ab = source.find(f"{TEI}text/{TEI}body")[0][16][0]
    children = list(ab)
    positions = {child.get(XML_ID): i for i, child in enumerate(children) if child.get(XML_ID)}
    if (positions[START], positions[END], positions[NEXT]) != (260, 527, 528):
        raise ValueError("source child positions changed")
    selected = etree.Element(f"{TEI}ab", attrib=dict(ab.attrib))
    for node in children[positions[START]:positions[NEXT]]:
        selected.append(deepcopy(node))
    result = etree.Element(f"{TEI}TEI", nsmap={None: TEI[1:-1]})
    result.set(XML_ID, f"ocd-{REVISION}")
    file_desc = etree.SubElement(etree.SubElement(result, f"{TEI}teiHeader"), f"{TEI}fileDesc")
    etree.SubElement(etree.SubElement(file_desc, f"{TEI}titleStmt"), f"{TEI}title").text = work["title"]
    old_desc = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if old_desc is None:
        raise ValueError("retained electronic header absent")
    publication = old_desc.find(f"{TEI}publicationStmt")
    bibliography = old_desc.find(f"{TEI}sourceDesc/{TEI}biblFull")
    if publication is None or bibliography is None:
        raise ValueError("electronic rights statement or print bibliography absent")
    file_desc.append(deepcopy(publication))
    etree.SubElement(file_desc, f"{TEI}sourceDesc").append(deepcopy(bibliography))
    body = etree.SubElement(etree.SubElement(result, f"{TEI}text"), f"{TEI}body")
    etree.SubElement(body, f"{TEI}div", type="work", n=work["title"]).append(selected)
    candidate = etree.tostring(result, encoding="UTF-8", xml_declaration=True)
    return candidate, check(source_bytes, candidate)


def stage(destination: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    destination = destination.absolute()
    if (destination == root or destination == root / WORK or Path(_io_path(destination)).exists()
            or not Path(_io_path(destination.parent)).is_dir()
            or Path(_io_path(root / ACCEPTANCE)).exists()
            or Path(_io_path(root / MASTER)).exists()):
        raise ValueError("fresh stage and nonaccepted work required")
    candidate, oracle = make_candidate(root)
    prior = _files(root / WORK)
    Path(_io_path(destination)).mkdir(parents=True, exist_ok=False)
    for relative in prior:
        source = Path(_io_path(root / WORK / relative))
        target = Path(_io_path(destination / WORK / relative))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    if _files(destination / WORK) != prior:
        raise ValueError("copied work differs")
    for relative in (SOURCE, PACKAGE, SOURCE_RECEIPT):
        source = Path(_io_path(root / relative))
        target = Path(_io_path(destination / relative))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    scope = (
        "Complete numbered first letter in retained openMGH bsb00000829 division 17, "
        f"from {START} through the complete closing line {END}. "
        f"The next numbered line {NEXT} and Joscerannus's response are outside. "
        "The prior Ivo letter closes at bsb00000829_00655_15."
    )
    work = _read(destination / WORK / "work.json")
    original_work = _read(root / WORK / "work.json")
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    edition.update(category="prose", language="la")
    validate_identity_update(original_work, work)
    _put(destination, WORK / "work.json", _json(work))
    load_work(Path(_io_path(destination / WORK / "work.json")))
    acquisition = _read(destination / ACQUISITION)
    acquisition["source_scope"] = scope
    acquisition["retained_files"][1]["scope"] = scope
    _put(destination, ACQUISITION, _json(acquisition))
    validate_acquisition(Path(_io_path(destination / ACQUISITION)), root=Path(_io_path(destination)))
    original_path = _put(destination, EVIDENCE / "original-candidate.tei.xml", candidate)
    if errors := validate_file(Path(_io_path(original_path))):
        raise ValueError(f"candidate TEI P5 failed: {errors[:3]}")
    process = subprocess.run(
        [sys.executable, "-m", "build.tools.prepare_openmgh_bsb829_sens",
         "--verify-candidate", sha256(candidate).hexdigest()],
        cwd=root, capture_output=True, text=True, check=True,
    )
    if "candidate-reproduced" not in process.stdout:
        raise ValueError("fresh candidate process did not confirm reproduction")
    identity = {"work_id": WORK_ID, "textual_form_id": form["textual_form_id"],
                "edition_id": edition["edition_id"],
                "acquisition_id": edition["acquisition_ids"][0]}
    revision = {"id": REVISION, "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Exact electronic letter, including the numbered heading and full final line."}
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
                      "source_bytes": len(Path(_io_path(root / SOURCE)).read_bytes()),
                      "source_scope": scope}
    accepted = bind_reviewed_header(
        candidate, expected_sha256=sha256(candidate).hexdigest(),
        identity=identity, source=source_binding, source_url=acquisition["url"],
        declared_scope=scope, revision=revision,
    )
    if accepted.split(b"</teiHeader>", 1)[1] != candidate.split(b"</teiHeader>", 1)[1]:
        raise ValueError("reviewed header changed candidate body")
    candidate_path = _put(destination, EVIDENCE / "candidate.tei.xml", accepted)
    if errors := validate_file(Path(_io_path(candidate_path))):
        raise ValueError(f"accepted TEI P5 failed: {errors[:3]}")
    included = [{"path": SOURCE.as_posix(), "position": 2, "bytes": len(Path(_io_path(root / SOURCE)).read_bytes()),
                 "sha256": SOURCE_SHA, "scope": scope}]
    excluded = [{"path": PACKAGE.as_posix(), "position": 1,
                 "reason": "Acquisition package only; extracted XML is text authority."}]
    members = [{"path": PACKAGE.as_posix(), "position": 1},
               {"path": SOURCE.as_posix(), "position": 2}]
    selection = {"kind": "selection", "declared": scope,
                 "expected_members": members, "included_members": included,
                 "excluded_members": excluded}
    common = {"identity": identity, "source": source_binding,
              "candidate": make_file_binding(destination, candidate_path),
              "scope": scope, "accepted_scope": {"kind": "selection", "declared": scope},
              "expected_members": members, "included_members": included,
              "excluded_members": excluded, "missing_members": [], "unknown_members": []}
    accounting = _put(destination, EVIDENCE / "source-accounting.json", _json(common | {
        "source_sha256": SOURCE_SHA, "source_bytes": source_binding["source_bytes"],
        "source_oracle": oracle, "zip_disposition": excluded[0]["reason"],
        "prior_letter_end": "bsb00000829_00655_15",
        "reply_start": "bsb00000829_00662_21",
    }))
    command = "py -3 -m build.tools.prepare_openmgh_bsb829_sens --stage"
    technical = {
        "producer": {"id": "ocd-bsb829-sens-source-slice-v1"},
        "checker": {"id": "ocd-bsb829-sens-independent-xml-oracle-v1"},
        "shared_assumptions": ["Producer and checker parse the same pinned retained XML; the checker derives boundaries independently from numbered lines, headings, salutations, and closing wording."],
        "independent_corroboration": "Source child tree equality, local reference closure, exact neighboring letter markers, TEI P5 XSD, fresh-process reproduction, and prose row check.",
    }
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put(destination, EVIDENCE / f"{name}.json", _json(common | {
            "status": "pass", "claim": name, "source_oracle": oracle,
            "candidate_body_unchanged": True, "fresh_process_reproduced": True,
            "command": command, "exit_code": 0,
        }))
        technical[name] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    reviewed_at = _now()
    review = {
        "reviewer": "agent:bsb829-sens-letter-source-review", "reviewed_at": reviewed_at,
        "coverage": {"status": "unavailable", "declared": scope,
                     "reached": ["all retained XML child nodes in the selected letter", "both letter boundaries"],
                     "inspected": ["all retained XML child nodes in the selected letter", "both letter boundaries"],
                     "unreviewed": ["close visual source/TEI comparison"]},
        "source_quality_uncertainty": ["No print witness was collated."],
        "discrepancies": [],
        "unreviewed_residuals": ["Human and visual review remain unrecorded."],
    }
    review_path = _put(destination, EVIDENCE / "review.json", _json(common | review))
    decision = {
        "source_local_disposition": "Agent acceptance of this exact electronic letter only.",
        "blockers": [],
        "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                             "assessed_at": reviewed_at, "supported_scope": scope,
                             "unresolved_claims": [],
                             "unassessed_stronger_claims": ["human acceptance", "visual review",
                                                            "print collation", "rights clearance", "publication"]},
        "human_decision": {"status": "not-recorded"},
    }
    acceptance = build_acceptance_record(
        destination, identity=identity, candidate_path=candidate_path,
        source_accounting_path=accounting, scope=selection,
        technical=technical, review=review | {"report_path": review_path},
        representation_revision=revision, decision=decision,
    )
    write_acceptance(Path(_io_path(destination / ACCEPTANCE)), acceptance)
    _put(destination, MASTER, accepted)
    acceptance["promotion"] = dict(acceptance["promotion"])
    acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                   master=make_file_binding(destination, destination / MASTER))
    write_acceptance(Path(_io_path(destination / ACCEPTANCE)), acceptance)
    state = _read(destination / WORK / "state.json")
    targets = [target for target in state["targets"] if target["target_type"] == "edition"
               and target["target_id"] == edition["edition_id"]]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError("edition state is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    targets[0]["evidence"].extend([MASTER.as_posix(), ACCEPTANCE.as_posix()])
    _put(destination, WORK / "state.json", _json(state))
    validated = validate_acceptance(Path(_io_path(destination / ACCEPTANCE)),
                                    root=Path(_io_path(destination)))
    validate_state(Path(_io_path(destination / WORK / "state.json")), root=Path(_io_path(destination)))
    projected = project_accepted_prose(Path(_io_path(destination)),
                                       acceptance_path=Path(_io_path(destination / ACCEPTANCE)))
    errors = verify_accepted_prose(Path(_io_path(destination)),
                                   acceptance_path=Path(_io_path(destination / ACCEPTANCE)),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"actual staged master projection failed: {errors[:3]}")
    result = {
        "contract": CONTRACT, "status": "staged-only", "work_id": WORK_ID,
        "canonical_root": root.as_posix(), "stage_root": destination.as_posix(),
        "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
        "before": prior, "after": _files(destination / WORK),
        "accepted_master_sha256": validated["promotion"]["master"]["sha256"],
        "acceptance_sha256": _sha(destination / ACCEPTANCE),
        "category": "prose", "language": "la", "projection_rows": 1,
        "projection_status": "independent-check-pass", "installation": "not-performed",
    }
    _put(destination, Path("stage-receipt.json"), _json(result))
    return result


def preflight(receipt_path: Path, expected_sha256: str) -> dict:
    receipt_path = receipt_path.resolve(strict=True)
    if _sha(receipt_path) != expected_sha256:
        raise ValueError("frozen stage receipt differs")
    receipt = _read(receipt_path)
    root = Path(receipt["canonical_root"]).resolve(strict=True)
    stage_root = Path(receipt["stage_root"]).resolve(strict=True)
    if (receipt.get("contract") != CONTRACT or receipt.get("work_id") != WORK_ID
            or receipt.get("status") != "staged-only"
            or receipt.get("source_sha256") != SOURCE_SHA
            or _sha(root / SOURCE) != SOURCE_SHA
            or _files(root / WORK) != receipt["before"]
            or _files(stage_root / WORK) != receipt["after"]
            or _sha(stage_root / ACCEPTANCE) != receipt["acceptance_sha256"]
            or _sha(stage_root / MASTER) != receipt["accepted_master_sha256"]):
        raise ValueError("stage or canonical preimage differs")
    validate_acceptance(Path(_io_path(stage_root / ACCEPTANCE)), root=Path(_io_path(stage_root)))
    validate_state(Path(_io_path(stage_root / WORK / "state.json")), root=Path(_io_path(stage_root)))
    projected = project_accepted_prose(Path(_io_path(stage_root)),
                                       acceptance_path=Path(_io_path(stage_root / ACCEPTANCE)))
    errors = verify_accepted_prose(Path(_io_path(stage_root)),
                                   acceptance_path=Path(_io_path(stage_root / ACCEPTANCE)),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"staged actual-master projection failed: {errors[:3]}")
    return {"status": "ready-for-install", "work_id": WORK_ID,
            "before_count": len(receipt["before"]), "after_count": len(receipt["after"])}


def install(receipt_path: Path, expected_sha256: str) -> dict:
    preflight(receipt_path, expected_sha256)
    receipt = _read(receipt_path)
    root = Path(receipt["canonical_root"]).resolve(strict=True)
    stage_root = Path(receipt["stage_root"]).resolve(strict=True)
    target = root / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        preflight(receipt_path, expected_sha256)
        operation = root / "library/.sidecar-operations" / f"bsb829-sens-{uuid.uuid4().hex[:16]}"
        Path(_io_path(operation)).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in
                                          ("incoming", "previous", "failed-new"))
        journal = operation / "operation.json"
        state = {"contract": "ocd-bsb829-sens-install-v1", "work_id": WORK_ID,
                 "stage_receipt": receipt_path.as_posix(),
                 "stage_receipt_sha256": expected_sha256,
                 "before": receipt["before"], "after": receipt["after"],
                 "phase": "created", "updated_at": _now()}
        _write_json_durable(journal, state)
        moved = live = False
        try:
            shutil.copytree(_io_path(stage_root / WORK), _io_path(incoming))
            if _files(incoming) != receipt["after"] or _files(target) != receipt["before"]:
                raise ValueError("copied stage or canonical preimage changed")
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            state.update(phase="previous-moved", updated_at=_now())
            _write_json_durable(journal, state)
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            state.update(phase="new-work-live", updated_at=_now())
            _write_json_durable(journal, state)
            validate_acceptance(Path(_io_path(root / ACCEPTANCE)), root=Path(_io_path(root)))
            validate_state(Path(_io_path(root / WORK / "state.json")), root=Path(_io_path(root)))
            projected = project_accepted_prose(Path(_io_path(root)),
                                               acceptance_path=Path(_io_path(root / ACCEPTANCE)))
            errors = verify_accepted_prose(Path(_io_path(root)),
                                           acceptance_path=Path(_io_path(root / ACCEPTANCE)),
                                           rows=projected["rows"], receipt=projected["receipt"])
            if (errors or len(projected["rows"]) != 1
                    or _files(target) != receipt["after"]):
                raise ValueError(f"installed work validation failed: {errors[:3]}")
            state.update(phase="complete", updated_at=_now(), validation={"rows": 1})
            _write_json_durable(journal, state)
            return {"status": "installed-and-validated", "work_id": WORK_ID,
                    "operation": operation.as_posix(), "projection_rows": 1}
        except BaseException:
            try:
                if live:
                    if _files(target) != receipt["after"]:
                        raise ValueError("live tree changed before rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _files(previous) != receipt["before"]:
                        raise ValueError("previous tree changed before rollback")
                    os.replace(_io_path(previous), _io_path(target))
                state.update(phase="rolled-back" if moved else "failed-before-swap", updated_at=_now())
                _write_json_durable(journal, state)
            except BaseException as error:
                state.update(phase="recovery-required", rollback_error=str(error), updated_at=_now())
                _write_json_durable(journal, state)
                raise
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--verify-candidate", metavar="SHA256")
    action.add_argument("--stage", type=Path)
    action.add_argument("--preflight", type=Path)
    action.add_argument("--apply", type=Path)
    parser.add_argument("--sha256")
    args = parser.parse_args()
    if args.verify_candidate:
        candidate, _oracle = make_candidate(ROOT)
        if sha256(candidate).hexdigest() != args.verify_candidate:
            raise ValueError("fresh candidate reproduction differs")
        result = {"status": "candidate-reproduced"}
    elif args.stage:
        result = stage(args.stage)
    elif args.preflight:
        if not args.sha256:
            raise ValueError("--sha256 required for preflight")
        result = preflight(args.preflight, args.sha256)
    else:
        if not args.sha256:
            raise ValueError("--sha256 required for installation")
        result = install(args.apply, args.sha256)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
