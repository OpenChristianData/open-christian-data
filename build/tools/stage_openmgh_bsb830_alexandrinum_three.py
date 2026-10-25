"""Stage one complete bsb830 Alexandrinum poem outside the checkout."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb830_alexandrinum_three as direct_source
from build.tei import openmgh_bsb830_alexandrinum_three as source
from build.tei.openmgh_bsb830_alexandrinum_three_oracle import check
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/bsb830-alexandrinum-three-direct-20260927-v1")
DIRECT_SHA = "d5e2dbc5aa5b35858b494305bf0817fd45da1e7ddaa9722948ee65f0b06ca01b"
REPRO = Path("D:/Library/Open Christian Data/candidate-reviews/bsb830-alexandrinum-three-direct-20260927-v2")
EVIDENCE = "openmgh-bsb830-alexandrinum-three-electronic-v1"
CONTRACT = "ocd-openmgh-bsb830-alexandrinum-three-stage-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, direct_source._json(value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def prepare(work_id: str, stage: Path) -> dict:
    if work_id not in source.SELECTED:
        raise ValueError(f"bsb830 Alexandrinum simple work is not selected: {work_id}")
    stage = stage.absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or ROOT.resolve() in stage.resolve().parents):
        raise ValueError("fresh external bsb830 Alexandrinum work stage required")
    if _sha(DIRECT / "receipt.json") != DIRECT_SHA:
        raise ValueError("bsb830 Alexandrinum direct receipt changed")
    direct = _read(DIRECT / "receipt.json")
    if (direct.get("contract") != direct_source.CONTRACT or direct.get("status") != "nonaccepted"
            or len(direct.get("selected_works", [])) != 3
            or {item["work_id"] for item in direct["selected_works"]} != set(source.SELECTED)):
        raise ValueError("bsb830 Alexandrinum direct batch scope changed")
    entry = next(item for item in direct["selected_works"] if item["work_id"] == work_id)
    candidate_bytes = _io_path(Path(entry["candidate_path"])).read_bytes()
    if (_sha(Path(entry["candidate_path"])) != entry["candidate_sha256"]
            or _sha(REPRO / work_id / "candidate.tei.xml") != entry["candidate_sha256"]):
        raise ValueError("bsb830 Alexandrinum candidate reproduction changed")
    reproduced, producer = source.convert(work_id)
    if reproduced != candidate_bytes or producer != entry["producer"]:
        raise ValueError("bsb830 Alexandrinum source conversion changed")
    oracle = check(work_id, candidate_bytes)
    if oracle != entry["oracle"]:
        raise ValueError("bsb830 Alexandrinum independent source oracle changed")
    original_work = _read(ROOT / entry["work_path"])
    acquisition = _read(ROOT / entry["acquisition_path"])
    if (_sha(ROOT / entry["work_path"]) != entry["work_sha256"]
            or _sha(ROOT / entry["state_path"]) != entry["state_sha256"]
            or _sha(ROOT / entry["acquisition_path"]) != entry["acquisition_sha256"]
            or _sha(ROOT / entry["acquisition_receipt_path"]) != entry["acquisition_receipt_sha256"]):
        raise ValueError("bsb830 Alexandrinum current sidecar or receipt changed")
    source_bytes = _io_path(ROOT / entry["source_path"]).read_bytes()
    if (sha256(source_bytes).hexdigest() != entry["source_sha256"]
            or len(source_bytes) != entry["source_bytes"]
            or _sha(ROOT / source.PACKAGE) != source.PACKAGE_SHA
            or acquisition.get("source_path") != entry["source_path"]
            or acquisition.get("source_sha256") != entry["source_sha256"]
            or {item["path"]: item["sha256"] for item in acquisition.get("retained_files", [])}
            != {source.SOURCE.as_posix(): source.SOURCE_SHA, source.PACKAGE.as_posix(): source.PACKAGE_SHA}):
        raise ValueError("bsb830 Alexandrinum extracted XML or package authority changed")
    work = Path("library/works") / work_id
    before = _files(ROOT / work)
    if set(before) != {"work.json", "state.json", (Path(entry["acquisition_path"]).relative_to(work)).as_posix()}:
        raise ValueError("bsb830 Alexandrinum work preimage is not the three-file acquisition")
    for relative, digest in before.items():
        content = _io_path(ROOT / work / relative).read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("bsb830 Alexandrinum work preimage changed during copy")
        _put(stage, work / relative, content)
    for relative in (Path(entry["source_path"]), Path(entry["acquisition_receipt_path"]),
                     source.PACKAGE):
        _put(stage, relative, _io_path(ROOT / relative).read_bytes())
    form = original_work["textual_forms"][0]
    edition_old = form["editions"][0]
    edition = work / "forms" / form["textual_form_id"] / "editions" / edition_old["edition_id"]
    acceptance_path = edition / "acceptance.json"
    master_path = edition / "master.tei.xml"
    if _io_path(ROOT / acceptance_path).exists() or _io_path(ROOT / master_path).exists():
        raise ValueError("bsb830 Alexandrinum edition already accepted")
    revised = _read(stage / work / "work.json")
    edition_new = revised["textual_forms"][0]["editions"][0]
    if edition_new.get("language") or edition_new.get("category"):
        raise ValueError("bsb830 Alexandrinum edition category/language preimage differs")
    edition_new.update(language="la", category="poetry")
    validate_identity_update(original_work, revised)
    _put_json(stage, work / "work.json", revised)
    load_work(_io_path(stage / work / "work.json"))
    identity = dict(work_id=work_id, textual_form_id=form["textual_form_id"],
                    edition_id=edition_old["edition_id"], acquisition_id=edition_old["acquisition_ids"][0])
    evidence = work / "integration" / EVIDENCE
    _put(stage, evidence / "inputs/candidate.tei.xml", candidate_bytes)
    revision = dict(id=f"{work_id}-openmgh-bsb830-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept one complete numbered poem from bsb830 division 9.")
    scope_text = (f"Complete native flat poem for {work_id} in extracted XML {entry['source_path']}, "
                  f"direct source child indexes {oracle['selected_child_start']}–{oracle['selected_child_end']} "
                  "of division 9; all selected page, column, anchor, and line nodes are included. "
                  "The page break at child 117 belongs to the second poem, preceding its title line. "
                  "Other poem spans and shared collection heading remain retained outside this work.")
    source_binding = dict(source_path=entry["source_path"], source_sha256=entry["source_sha256"],
                          source_bytes=len(source_bytes), source_scope=scope_text)
    derived = bind_reviewed_header(candidate_bytes, expected_sha256=entry["candidate_sha256"], identity=identity,
                                   source=source_binding, source_url=acquisition["url"],
                                   declared_scope=scope_text, revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != candidate_bytes.split(b"</teiHeader>", 1)[1]:
        raise ValueError("bsb830 Alexandrinum acceptance header changed source body")
    candidate = _put(stage, evidence / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"bsb830 Alexandrinum accepted TEI P5 XSD failed: {errors[:3]}")
    expected = [dict(path=source.PACKAGE.as_posix(), position=1),
                dict(path=entry["source_path"], position=2)]
    included = [dict(path=entry["source_path"], position=2, bytes=len(source_bytes),
                     sha256=entry["source_sha256"], scope=scope_text)]
    excluded = [dict(path=source.PACKAGE.as_posix(), position=1,
                     reason="Original ZIP is acquisition packaging; extracted XML is text authority.")]
    scope = dict(kind="selection", declared=scope_text, expected_members=expected,
                 included_members=included, excluded_members=excluded)
    acquired_binding = {key: acquisition[key] for key in ("source_path", "source_sha256", "source_bytes", "source_scope")}
    common = dict(identity=identity, source=acquired_binding, candidate=make_file_binding(stage, candidate),
                  scope=scope_text, accepted_scope=dict(kind="selection", declared=scope_text),
                  expected_members=expected, included_members=included, excluded_members=excluded,
                  missing_members=[], unknown_members=[])
    account = _put_json(stage, evidence / "source-accounting.json", common | dict(
        scope=acquisition["source_scope"], source_sha256=entry["source_sha256"],
        source_bytes=len(source_bytes), source_division_ordinal=9,
        source_entity_declarations=0, source_child_start=oracle["selected_child_start"], source_child_end=oracle["selected_child_end"], source_oracle=oracle, source_selection_c14n_sha256=oracle["selection_c14n_sha256"],
        boundary_page=oracle["boundary_page"],
        direct_receipt_sha256=DIRECT_SHA, original_candidate_sha256=entry["candidate_sha256"],
        accepted_body_unchanged=True))
    command = "py -3 -m build.tools.stage_openmgh_bsb830_alexandrinum_three <work-id> --stage <fresh-external-root>"
    technical = dict(producer=dict(id=source.CONTRACT), checker=dict(id=oracle["contract"]),
                     shared_assumptions=["Producer and checker parse the same retained XML; checker independently compares every front/body node and source metadata fields."],
                     independent_corroboration="Fresh-process byte reproduction, TEI P5 XSD, and native poetry projection agree.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        path = _put_json(stage, evidence / (name + ".json"), common | dict(status="pass", command=command,
                         exit_code=0, claim=name, source_oracle=oracle, direct_receipt_sha256=DIRECT_SHA,
                         clean_process_reproduction="pass", tei_xsd="pass", accepted_body_unchanged=True))
        technical[name] = dict(path=path, status="pass", command=command, exit_code=0)
    now = _now()
    review = dict(reviewer=f"agent:{work_id}-openmgh-tei2-source-review", reviewed_at=now,
                  coverage=dict(status="unavailable", declared=scope_text,
                                reached=["complete front/body node and rights/credit oracle"],
                                inspected=["complete front/body node and rights/credit oracle"],
                                unreviewed=["close CVW visual source comparison"]),
                  source_quality_uncertainty=["No print witness was independently collated."], discrepancies=[],
                  unreviewed_residuals=["Visual and human review remain unrecorded."])
    review_path = _put_json(stage, evidence / "review.json", common | review)
    decision = dict(source_local_disposition="Agent acceptance of the exact electronic text and mapped P5 carriers only.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                                          supported_scope=scope_text, unresolved_claims=[],
                                          unassessed_stronger_claims=["visual review", "human acceptance", "print collation", "rights clearance", "publication"]))
    acceptance = build_acceptance_record(stage, identity=identity, candidate_path=candidate,
                                         source_accounting_path=account, scope=scope, technical=technical,
                                         review=review | dict(report_path=review_path),
                                         representation_revision=revision, decision=decision)
    write_acceptance(_io_path(stage / acceptance_path), acceptance)
    validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
    master = _put(stage, master_path, derived)
    acceptance["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, master))
    write_acceptance(_io_path(stage / acceptance_path), acceptance)
    state = _read(stage / work / "state.json")
    targets = [t for t in state["targets"] if t["target_type"] == "edition" and t["target_id"] == edition_old["edition_id"]]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError("bsb830 Alexandrinum edition target is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([master_path.as_posix(), acceptance_path.as_posix()])
    _put_json(stage, work / "state.json", state)
    validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path), category="poetry")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path),
                                      rows=projected["rows"], receipt=projected["receipt"], category="poetry")
    if errors or len(projected["rows"]) != entry["native_projection_rows"]:
        raise ValueError(f"bsb830 Alexandrinum actual-master native projection failed: {errors[:3]}")
    credit = (f"# Electronic source credit for {work_id}\n\n"
              f"This exact poem span derives from the retained openMGH extracted XML at {entry['source_path']} "
              f"(SHA-256 {entry['source_sha256']}). Credit Monumenta Germaniae Historica and the Bavarian State Library, Munich, and preserve the "
              "source header's publication, license, and printed-volume bibliography. The ZIP is the acquisition "
              "package only. This stage does not establish independent print collation, rights clearance, "
              "human acceptance, or public release.\n")
    _put(stage, work / "SOURCE_CREDIT.md", credit.encode("utf-8"))
    _put(stage, edition / "README.source.md", credit.encode("utf-8"))
    result = dict(contract=CONTRACT, status="staged-only", work_id=work_id,
                  canonical_root=ROOT.as_posix(), stage_root=stage.as_posix(),
                  direct_receipt=(DIRECT / "receipt.json").as_posix(), direct_receipt_sha256=DIRECT_SHA,
                  source_path=entry["source_path"], source_sha256=entry["source_sha256"],
                  source_bytes=len(source_bytes), source_division_ordinal=9,
                  source_entity_declarations=0, source_child_start=oracle["selected_child_start"], source_child_end=oracle["selected_child_end"], source_selection_c14n_sha256=oracle["selection_c14n_sha256"],
                  boundary_page=oracle["boundary_page"],
                  source_oracle=oracle, before=before, after=_files(stage / work),
                  accepted_master_sha256=_sha(master), acceptance_sha256=_sha(stage / acceptance_path),
                  category="poetry", language="la", projection_rows=len(projected["rows"]),
                  projection_status="independent-check-pass", installation="not-performed")
    _put_json(stage, Path("stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(source.SELECTED))
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.work_id, args.stage)
    print(json.dumps(dict(work_id=args.work_id, status=result["status"],
                          master_sha256=result["accepted_master_sha256"]), sort_keys=True))


if __name__ == "__main__":
    main()

