"""Prepare, preflight, and guarded-install the scoped Evans/Cheevers A63318 work."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import runpy
import shutil

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.projection.categories.native_documents import verify_document
from ocd_kernel.projection.categories.prose import project_prose_document
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import (
    _commit_generation, _files, _io_path, _validate_state_transition,
)
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
BOUNDARY = ROOT / "library/stages/a63318-boundary-20260930"
WORK_ID = "evans-cheevers-malta-narrative"
WORK = Path("library/works") / WORK_ID
FORM_ID = WORK_ID + "-tcp-retained"
EDITION_ID = WORK_ID + "-tcp-electronic"
ACQUISITION_ID = WORK_ID + "-tcp-acquired"
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
CANDIDATE = WORK / "integration/a63318-boundary-v1/candidate.tei.xml"
EVIDENCE = WORK / "integration/a63318-acceptance-v1"
SOURCE = Path("raw/tcp/high-range/A63318/A63318.xml")
SOURCE_RECEIPT = Path("raw/tcp/high-range/A63318/acquisition-receipt.json")
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
SOURCE_SHA = "24f98b7387a6f3932f4ff5fcecd371457b0bc6a03d6dd8bb0e21a74b944ad2e8"
CANDIDATE_SHA = "aca0e5fde447ac87207059b5e37edef56db7973ebe65f7b9f6d3846d6dbe3ea2"
REVISION = dict(
    id="evans-cheevers-malta-narrative-a63318-scoped-candidate-v1",
    date="2026-09-30",
    note="Reconstruct the exact separately addressed constituent of the shared A63318 book; candidate only.",
)
COMMAND = "py -3 -m build.tools.stage_evans_a63318_acceptance --prepare --stage <fresh-stage-root>"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    raw = _io_path(path).read_bytes()
    if expected is not None and sha256(raw).hexdigest() != expected:
        raise PipelineError(f"Evans/Cheevers input SHA-256 differs: {path}")
    return raw


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise PipelineError(f"Evans/Cheevers JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, raw: bytes) -> Path:
    path = stage / relative
    _io_path(path).parent.mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(raw)
    return path


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return _put(stage, relative, raw)


def _pinned_inputs() -> tuple[dict, dict]:
    freeze = _json(BOUNDARY / "freeze.json")
    index = _json(BOUNDARY / "stage-index.json")
    if (freeze.get("contract") != "ocd-a63318-scoped-frozen-stage-v1"
            or index.get("source_path") != SOURCE.as_posix()
            or index.get("source_sha256") != SOURCE_SHA
            or index["works"][WORK_ID]["candidate_sha256"] != CANDIDATE_SHA):
        raise PipelineError("Evans/Cheevers frozen stage contract differs")
    for relative, digest in freeze["files"].items():
        _read(BOUNDARY / relative, digest)
    for relative, digest in freeze["canonical_evans_preimages"].items():
        _read(ROOT / relative, digest)
    _read(ROOT / SOURCE, SOURCE_SHA)
    if _io_path(ROOT / ACCEPTANCE).exists() or _io_path(ROOT / MASTER).exists():
        raise PipelineError("Evans/Cheevers already has an accepted master")
    if set(_files(ROOT / WORK)) != {
        "work.json", "state.json", ACQUISITION.relative_to(WORK).as_posix(),
        "integration/evans-a63318-whole-publication-v1/handoff.md",
    }:
        raise PipelineError("Evans/Cheevers complete canonical preimage differs")
    result = runpy.run_path(str(BOUNDARY / "verify_stage.py"))["verify"]()
    if result.get("status") != "pass" or result["candidate_sha256"][WORK_ID] != CANDIDATE_SHA:
        raise PipelineError("Evans/Cheevers frozen source/TEI check differs")
    return freeze, index


def _candidate_projection(path: Path, work: dict) -> dict:
    edition = work["textual_forms"][0]["editions"][0]
    result = project_prose_document(
        _io_path(path), identity={key: IDENTITY[key] for key in ("work_id", "textual_form_id", "edition_id")},
        language="en", representation_revision=REVISION["id"],
        edition_title=edition["title"], _allow_acceptance_metadata=True,
    )
    errors = verify_document(
        _io_path(path), result["rows"], result["receipt"],
        identity={key: IDENTITY[key] for key in ("work_id", "textual_form_id", "edition_id")},
        language="en", representation_revision=REVISION["id"],
        edition_title=edition["title"], category="prose", _allow_acceptance_metadata=True,
    )
    if errors or len(result["rows"]) != 4:
        raise PipelineError(f"Evans/Cheevers candidate projection differs: {errors[:3]}")
    def nodes(value: dict):
        yield value
        for child in value.get("content", []):
            if isinstance(child, dict) and "content" in child:
                yield from nodes(child)
    count = sum(node.get("kind") == "postscript" for row in result["rows"]
                for part in row["structure"] for node in nodes(part))
    if count != 4:
        raise PipelineError("Evans/Cheevers four source postscripts are not public carriers")
    return result


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (_io_path(stage).exists() or not stage.parent.is_dir()
            or stage == ROOT or stage in ROOT.parents):
        raise PipelineError("Evans/Cheevers acceptance stage must be a fresh directory")
    freeze, index = _pinned_inputs()
    original = ROOT / WORK
    staged_work = stage / WORK
    _io_path(staged_work).parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_io_path(original), _io_path(staged_work))
    _put(stage, SOURCE, _read(ROOT / SOURCE, SOURCE_SHA))
    _put(stage, SOURCE_RECEIPT, _read(ROOT / SOURCE_RECEIPT))
    selected = BOUNDARY / WORK_ID
    for source_name, destination in (
        ("work.json", WORK / "work.json"),
        ("acquisition.json", ACQUISITION),
        ("SOURCE_CREDIT.md", WORK / "SOURCE_CREDIT.md"),
        ("README.source.md", EDITION / "README.source.md"),
        ("candidate.tei.xml", CANDIDATE),
    ):
        _put(stage, destination, _read(selected / source_name, freeze["files"][f"{WORK_ID}/{source_name}"]))
    candidate = stage / CANDIDATE
    if errors := validate_file(_io_path(candidate)):
        raise PipelineError(f"Evans/Cheevers candidate TEI P5 errors: {errors[:3]}")
    work = _json(stage / WORK / "work.json")
    acquisition = _json(stage / ACQUISITION)
    if (work["work_id"] != WORK_ID or acquisition["source_sha256"] != SOURCE_SHA
            or acquisition["source_bytes"] != len(_read(ROOT / SOURCE))
            or acquisition["source_path"] != SOURCE.as_posix()):
        raise PipelineError("Evans/Cheevers selected work/acquisition differs")
    validate_identity_update(_json(ROOT / WORK / "work.json"), work)
    projected = _candidate_projection(candidate, work)
    source_binding = dict(source_path=SOURCE.as_posix(), source_bytes=acquisition["source_bytes"],
                          source_sha256=SOURCE_SHA, source_scope=acquisition["source_scope"])
    scope_text = "Exact selected constituent of the complete retained A63318 XML: /tei:TEI/tei:text/tei:front; /tei:TEI/tei:text/tei:body/tei:div[1]; /tei:TEI/tei:text/tei:body/tei:div[2] except its final tei:div[@type='account']. The containing book and original acquisition are shared; the other constituent is excluded."
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=acquisition["source_bytes"],
                     sha256=SOURCE_SHA, scope=acquisition["source_scope"])]
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    scope = dict(kind="edition", declared=scope_text, expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=source_binding,
                  candidate=make_file_binding(stage, candidate),
                  accepted_scope=dict(kind="edition", declared=scope_text),
                  expected_members=expected, included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    for name in ("freeze.json", "stage-index.json", "validation.json", "build_stage.py", "verify_stage.py"):
        _put(stage, EVIDENCE / "inputs" / name, _read(BOUNDARY / name))
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", {
        **common, "scope": acquisition["source_scope"], "source_sha256": SOURCE_SHA,
        "source_bytes": acquisition["source_bytes"], "selected_scope": scope_text,
        "other_constituent": "George Robinson account remains in the source container but is not part of this accepted edition.",
        "source_partition_validation_sha256": _sha(BOUNDARY / "validation.json"),
    })
    technical = dict(
        producer={"id": "ocd-a63318-boundary-build-stage"},
        checker={"id": "ocd-a63318-boundary-verify-stage"},
        shared_assumptions=["Producer and source checker both parse the retained XML; their exact subtree comparison is corroborated by candidate hash reproduction and a separate native-content row observer."],
        independent_corroboration="Frozen source/candidate hashes, independent canonical XML partition comparison, P5, mutation challenge, and four-row independent native projection correspondence.",
    )
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, EVIDENCE / f"{name}.json", {
            **common, "scope": scope_text, "status": "pass", "claim": name,
            "command": COMMAND, "exit_code": 0,
            "source_sha256": SOURCE_SHA, "candidate_sha256": CANDIDATE_SHA,
            "source_partition_validation_sha256": _sha(BOUNDARY / "validation.json"),
            "projection_row_count": len(projected["rows"]),
        })
        technical[name] = dict(path=path, status="pass", command=COMMAND, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = dict(
        reviewer="agent:a63318-evans-electronic", reviewed_at=now,
        coverage=dict(status="partial", declared=scope_text,
                      reached=[SOURCE.as_posix()], inspected=[SOURCE.as_posix()],
                      unreviewed=["print-image-collation", "human-visual-review"]),
        source_quality_uncertainty=["The retained TCP electronic witness was not collated against printed page images."],
        discrepancies=[], unreviewed_residuals=["Human visual review, print collation, and release rights remain unrecorded."],
    )
    review_path = _put_json(stage, EVIDENCE / "review.json", {**common, "scope": scope_text, **review})
    decision = dict(
        source_local_disposition="Agent technical acceptance of Evans and Cheevers' exact selected constituent in the retained A63318 electronic witness only.",
        blockers=[], human_decision={"status": "not-recorded"},
        agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                              supported_scope=scope_text, unresolved_claims=[],
                              unassessed_stronger_claims=["print collation", "human review", "rights clearance", "publication"]),
    )
    record = build_acceptance_record(
        stage, identity=IDENTITY, candidate_path=candidate, source_accounting_path=accounting,
        scope=scope, technical=technical, review={**review, "report_path": review_path},
        representation_revision=REVISION, decision=decision,
    )
    acceptance = stage / ACCEPTANCE
    write_acceptance(_io_path(acceptance), record)
    master = _put(stage, MASTER, _read(candidate, CANDIDATE_SHA))
    record["promotion"].update(status="promoted", promoted_at=now,
                               master=make_file_binding(stage, master))
    write_acceptance(_io_path(acceptance), record)
    state = _json(ROOT / WORK / "state.json")
    edition_target = next(item for item in state["targets"] if item["target_id"] == EDITION_ID)
    if edition_target["stage"] != "acquired":
        raise PipelineError("Evans/Cheevers edition preimage is not acquired")
    edition_target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    edition_target["evidence"].extend([MASTER.as_posix(), ACCEPTANCE.as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projection = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance),
                                   rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 4:
        raise PipelineError(f"Evans/Cheevers staged actual-master projection differs: {errors[:3]}")
    receipt = dict(contract="ocd-a63318-evans-promoted-stage-v1", status="staged-only",
                   work_id=WORK_ID, source_sha256=SOURCE_SHA, candidate_sha256=CANDIDATE_SHA,
                   original_freeze_sha256=_sha(BOUNDARY / "freeze.json"),
                   before=_files(ROOT / WORK), after=_files(stage / WORK),
                   master_sha256=_sha(master), acceptance_sha256=_sha(acceptance),
                   projection_rows=len(projection["rows"]), installation="not-performed")
    _put_json(stage, Path("evans-a63318-promoted-stage-receipt.json"), receipt)
    return receipt


def preflight(stage: Path) -> tuple[dict, Path]:
    stage = stage.resolve(strict=True)
    _pinned_inputs()
    receipt = _json(stage / "evans-a63318-promoted-stage-receipt.json")
    if (receipt.get("contract") != "ocd-a63318-evans-promoted-stage-v1"
            or receipt.get("work_id") != WORK_ID or receipt.get("source_sha256") != SOURCE_SHA
            or receipt.get("candidate_sha256") != CANDIDATE_SHA
            or receipt.get("original_freeze_sha256") != _sha(BOUNDARY / "freeze.json")
            or receipt.get("before") != _files(ROOT / WORK)
            or receipt.get("after") != _files(stage / WORK)):
        raise PipelineError("Evans/Cheevers stage receipt or preimage differs")
    if (receipt["after"].get(MASTER.relative_to(WORK).as_posix()) != CANDIDATE_SHA
            or receipt["after"].get(ACCEPTANCE.relative_to(WORK).as_posix()) != receipt["acceptance_sha256"]):
        raise PipelineError("Evans/Cheevers staged master or acceptance differs")
    for relative, expected in ((SOURCE, SOURCE_SHA), (SOURCE_RECEIPT, _sha(ROOT / SOURCE_RECEIPT))):
        _read(stage / relative, expected)
    old_work = _json(ROOT / WORK / "work.json")
    new_work = _json(stage / WORK / "work.json")
    validate_identity_update(old_work, new_work)
    if _sha(stage / WORK / "work.json") != _sha(BOUNDARY / WORK_ID / "work.json"):
        raise PipelineError("Evans/Cheevers staged work differs from frozen boundary")
    if _sha(stage / ACQUISITION) != _sha(BOUNDARY / WORK_ID / "acquisition.json"):
        raise PipelineError("Evans/Cheevers staged acquisition differs from frozen boundary")
    accepted = validate_acceptance(_io_path(stage / ACCEPTANCE), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if (accepted["identity"] != IDENTITY or accepted["promotion"]["status"] != "promoted"
            or accepted["decision"]["human_decision"]["status"] != "not-recorded"):
        raise PipelineError("Evans/Cheevers technical decision is overstated")
    _validate_state_transition(ROOT / WORK, stage / WORK, existed=True, replacement=False,
                               accepted_evidence_by_edition={EDITION_ID: (MASTER.as_posix(), ACCEPTANCE.as_posix())})
    projection = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(stage / ACCEPTANCE))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(stage / ACCEPTANCE),
                                   rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 4:
        raise PipelineError(f"Evans/Cheevers actual-master preflight projection differs: {errors[:3]}")
    return receipt, stage


def install(stage: Path) -> dict:
    receipt, stage = preflight(stage)
    target, source = ROOT / WORK, stage / WORK
    with ExitStack() as locks:
        for item in sorted((target, source), key=lambda path: path.as_posix()):
            locks.enter_context(acquire_jsonl_lock(item, acquire_timeout=30.0))
        if _files(target) != receipt["before"] or _files(source) != receipt["after"]:
            raise PipelineError("Evans/Cheevers changed while acquiring install locks")
        result = _commit_generation(
            ROOT.resolve(strict=True), target.resolve(strict=True), source.resolve(strict=True),
            work_id=WORK_ID, before=receipt["before"], after=receipt["after"],
            existed=True, replacement=False, operation_kind="initial-install",
            result_status="installed-and-validated", accepted_editions=1, fail_at=None,
        )
    projection = project_accepted_prose(ROOT, acceptance_path=ROOT / ACCEPTANCE)
    errors = verify_accepted_prose(ROOT, acceptance_path=ROOT / ACCEPTANCE,
                                   rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 4:
        raise PipelineError(f"Evans/Cheevers installed actual-master projection differs: {errors[:3]}")
    return {"status": result["status"], "operation": result["operation"],
            "master_sha256": _sha(ROOT / MASTER), "acceptance_sha256": _sha(ROOT / ACCEPTANCE),
            "projection_rows": len(projection["rows"]),
            "row_json_sha256": sha256(json.dumps(projection["rows"], ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest(),
            "receipt_json_sha256": sha256(json.dumps(projection["receipt"], ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":")).encode()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--prepare", action="store_true")
    operation.add_argument("--preflight", action="store_true")
    operation.add_argument("--apply", action="store_true")
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    if args.prepare:
        result = prepare(args.stage)
    elif args.preflight:
        result = {"status": "ready-for-install", "stage": str(preflight(args.stage)[1])}
    else:
        result = install(args.stage)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
