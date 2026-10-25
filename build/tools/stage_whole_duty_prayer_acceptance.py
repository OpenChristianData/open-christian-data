"""Stage the complete retained A23804 witness after its reversible shell adaptation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from build.tei.whole_duty_prayer_a23804_oracle import _oracle
from build.tei.whole_duty_prayer_native_adapter import adapt_whole_duty_prayer, SOURCE_SHA256
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prayers import project_accepted_prayers, verify_accepted_prayers
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding, validate_acceptance, write_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "whole-duty-of-prayer"
WORK = Path("library/works") / WORK_ID
FORM_ID, EDITION_ID, ACQUISITION_ID = (WORK_ID + suffix for suffix in ("-tcp-retained", "-tcp-electronic", "-tcp-acquired"))
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / (ACQUISITION_ID + ".json")
SOURCE = Path("raw/tcp/high-range/A23804/A23804.xml")
MANIFEST = Path("sources/structured-text/whole-duty-of-prayer/whole-duty-of-prayer.source-manifest.current-20261003.json")
BASE = Path("D:/Library/Open Christian Data/candidate-reviews/whole-duty-of-prayer-a23804-current-20261003-v2")
REPLAY = Path("D:/Library/Open Christian Data/candidate-reviews/whole-duty-of-prayer-a23804-current-20261003-replay")
EVIDENCE = WORK / "integration/tcp-a23804-native-current-20261003-v1"
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
MANIFEST_SHA = "016e0bbfd06901fdd7c07455f0390b0973de7adba86d4238981c888037addf42"
PACKAGE_SHA = "c6c302ad422f5bdf882d2db7a1a0815e073741709372fa1b23a82f626657829a"
REPORT_SHA = "e87654be14984cd538aa19aa93a8057ab2adee7a0c89880e8fb316ed49988f36"


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or stage.resolve() == ROOT.resolve() or ROOT.resolve() in stage.resolve().parents):
        raise ValueError("A23804 stage must be a fresh external directory")
    before = _files(ROOT / WORK)
    if any(name.endswith(("/master.tei.xml", "/acceptance.json")) for name in before):
        raise ValueError("A23804 already has an installed acceptance")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(_io_path(BASE / "package"))
    replay = CandidatePackage.load(_io_path(REPLAY / "package"))
    report = validate(manifest, package, _oracle)
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA or report.sha256 != REPORT_SHA
            or report.status != "pass" or report.findings or package.sha256 != replay.sha256
            or _files(BASE) != _files(REPLAY)):
        raise ValueError("A23804 current source/candidate/replay binding differs")
    original = _io_path(ROOT / SOURCE).read_bytes()
    if package.member_bytes("content.tei.xml") != original:
        raise ValueError("A23804 retained source and package differ")
    acquisition = json.loads(_io_path(ROOT / ACQUISITION).read_text(encoding="utf-8"))
    if (acquisition["source_path"] != SOURCE.as_posix() or acquisition["source_sha256"] != SOURCE_SHA256
            or acquisition["source_bytes"] != len(original) or len(acquisition["retained_files"]) != 1):
        raise ValueError("A23804 acquisition envelope differs")

    def put(relative: Path, content: bytes) -> Path:
        destination = stage / relative
        _io_path(destination.parent).mkdir(parents=True, exist_ok=True)
        _io_path(destination).write_bytes(content)
        return destination

    def put_json(relative: Path, value: object) -> Path:
        return put(relative, (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))

    for relative, digest in before.items():
        content = _io_path(ROOT / WORK / relative).read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError(f"A23804 work changed during staging: {relative}")
        put(WORK / relative, content)
    old_work = load_work(ROOT / WORK / "work.json")
    state = json.loads((ROOT / WORK / "state.json").read_text(encoding="utf-8"))
    targets = [t for t in state["targets"] if t["target_type"] == "edition" and t["target_id"] == EDITION_ID]
    if len(targets) != 1 or targets[0]["stage"] != "review":
        raise ValueError("A23804 current edition target differs")
    dependencies = {SOURCE, MANIFEST, Path("build/tei/whole_duty_prayer_native_adapter.py")}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    dependencies.update(Path(manifest.record[key]["implementation_path"]) for key in ("converter", "validator"))
    for reference in set(old_work.get("evidence", [])) | {e for t in state["targets"] for e in t.get("evidence", [])}:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe A23804 evidence path: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            put(relative, _io_path(ROOT / relative).read_bytes())
    for name in package.member_names:
        put(EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    put(EVIDENCE / "inputs/validation.json", _io_path(BASE / "validation.json").read_bytes())
    work = json.loads(json.dumps(old_work))
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if (len(work["textual_forms"]) != 1 or len(form["editions"]) != 1 or edition["edition_id"] != EDITION_ID
            or any(item.get("language") is not None for item in (form, edition)) or edition.get("category") is not None):
        raise ValueError("A23804 form/edition metadata preimage differs")
    form["language"] = edition["language"] = "en"
    edition["category"] = "prayers"
    validate_identity_update(old_work, work)
    put_json(WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    adapted, adaptation = adapt_whole_duty_prayer(original)
    revision = dict(id="whole-duty-prayer-a23804-electronic-agent-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Bind the complete retained TCP witness; explicitly account for anonymous unary electronic container shell.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_bytes=len(original), source_sha256=SOURCE_SHA256, source_scope=acquisition["source_scope"])
    derived = bind_reviewed_header(adapted, expected_sha256=sha256(adapted).hexdigest(), identity=IDENTITY,
                                  source=source_binding, source_url=acquisition["url"], declared_scope=acquisition["source_scope"], revision=revision)
    candidate = put(EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"A23804 bound P5 errors: {errors[:3]}")
    put_json(EVIDENCE / "shell-adaptation.json", adaptation)
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(original), sha256=SOURCE_SHA256, scope=acquisition["source_scope"])]
    scope = dict(kind="edition", declared=acquisition["source_scope"], expected_members=expected, included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=source_binding, candidate=make_file_binding(stage, candidate),
                  scope=acquisition["source_scope"], accepted_scope=dict(kind="edition", declared=acquisition["source_scope"]),
                  expected_members=expected, included_members=included, excluded_members=[], missing_members=[], unknown_members=[])
    accounting = put_json(EVIDENCE / "source-accounting.json", common | dict(source_sha256=SOURCE_SHA256, source_bytes=len(original),
                          source_manifest_sha256=MANIFEST_SHA, candidate_package_sha256=PACKAGE_SHA,
                          basis="Complete exact-byte electronic source; reversible anonymous container-shell adaptation; original header and complete inner work subtree retained.", shell_adaptation=adaptation))
    command = "py -3 -m build.tools.stage_whole_duty_prayer_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]), checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Adapter tree comparison and P5 both use lxml; exact byte inverse separately conserves all original bytes."],
                     independent_corroboration="Exact source/package byte equality, current independent source oracle, seven-file fresh-process replay, reversible shell bytes and complete work-subtree C14N.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = put_json(EVIDENCE / (name + ".json"), common | dict(status="pass", command=command, exit_code=0, claim=name,
                         source_manifest_sha256=MANIFEST_SHA, candidate_package_sha256=PACKAGE_SHA, oracle_report_sha256=REPORT_SHA,
                         oracle=dict(report.attestation), shell_adaptation=adaptation, clean_process_replay=dict(first=str(BASE), second=str(REPLAY), hashes=_files(BASE))))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = dict(reviewer="agent:a23804-electronic-stage", reviewed_at=now,
                  coverage=dict(status="partial", declared=acquisition["source_scope"], reached=[SOURCE.as_posix()+"#complete-electronic-witness"],
                                inspected=[SOURCE.as_posix()+"#complete-electronic-witness"], unreviewed=[SOURCE.as_posix()+"#print-image-collation"]),
                  source_quality_uncertainty=["All 27 TCP illegible gaps remain explicit; no page-image collation."], discrepancies=[],
                  unreviewed_residuals=["Print collation, human review and rights decisions remain unassessed."])
    review_file = put_json(EVIDENCE / "review.json", common | review)
    decision = dict(source_local_disposition="Agent acceptance of the complete retained TCP A23804 electronic witness only.", blockers=[],
                    human_decision=dict(status="not-recorded"), agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                    supported_scope=acquisition["source_scope"], unresolved_claims=[], unassessed_stronger_claims=["print collation", "human review", "rights clearance", "public publication"]))
    acceptance = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate, source_accounting_path=accounting,
                                         scope=scope, technical=technical, review=review | dict(report_path=review_file), representation_revision=revision, decision=decision)
    acceptance_path = stage / EDITION / "acceptance.json"
    write_acceptance(_io_path(acceptance_path), acceptance)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    master = put(EDITION / "master.tei.xml", derived)
    acceptance["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage, master))
    write_acceptance(_io_path(acceptance_path), acceptance)
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()])
    put_json(WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_prayers(stage, acceptance_path=acceptance_path)
    errors = verify_accepted_prayers(stage, acceptance_path=acceptance_path, rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 6:
        raise ValueError(f"A23804 actual master projection failed: {errors[:3]}")
    put_json(EVIDENCE / "actual-master-projection.json", projected)
    if before != _files(ROOT / WORK):
        raise ValueError("A23804 canonical work changed during staging")
    receipt = dict(contract="ocd-a23804-electronic-stage-v1", status="staged-only", stage_root=str(stage), work_id=WORK_ID,
                   before=before, after=_files(stage / WORK), master_sha256=sha256(derived).hexdigest(),
                   acceptance_sha256=sha256(_io_path(acceptance_path).read_bytes()).hexdigest(), projection_rows=6,
                   rights="not-assessed", installation="not-performed")
    put_json(Path("a23804-stage-receipt.json"), receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    result = prepare(parser.parse_args().stage)
    print(json.dumps(result, sort_keys=True))
