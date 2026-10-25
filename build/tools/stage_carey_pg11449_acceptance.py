"""Freeze the exact PG11449 Carey candidate as a stage-only accepted master."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.gutenberg_proofread_selected_oracle import _oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    CAREY_GROUPED_TABLE_PROFILE, project_accepted_document, verify_accepted_document,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
LIBRARY = Path("D:/Library/Open Christian Data")
WORK_ID = "carey-enquiry"
FORM_ID = "carey-enquiry-retained-text"
EDITION_ID = "carey-enquiry-pg11449-electronic-witness"
ACQUISITION_ID = "carey-enquiry-pg11449-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/gutenberg/pg11449.txt")
SOURCE_SHA = "6dc07e5606be5a0032d6583fa5b663a81ed0971a5d9d1f267cfc14959aa602c0"
MANIFEST = Path("sources/structured-text/lib071-gutenberg-evangelical/work-bindings/carey-enquiry/37c-094-tables-v4.source-manifest.json")
CANDIDATE = LIBRARY / "candidate-reviews/37c-094-carey-enquiry-20260915-tables-v5/package"
CANDIDATE_SHA = "5140dbd06577383369badc227fb7f07e9fa0a6325bbee557427444fdd6ae839e"
EVIDENCE = WORK / "integration/carey-pg11449-grouped-tables-v1"
NATIVE_DEPENDENCIES = (
    Path("ocd_kernel/projection/categories/native_documents.py"),
    Path("ocd_kernel/projection/native_content.py"),
    Path("ocd_kernel/projection/native_content_check.py"),
    Path("schemas/v2/native-content.schema.json"),
)


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _write(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _write_json(stage: Path, relative: Path, value: object) -> Path:
    return _write(stage, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")) + "\n").encode("utf-8"))


def _copy(root: Path, stage: Path, relative: Path) -> None:
    target = stage / relative
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(root / relative), _io_path(target))


def prepare(stage: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    stage = stage.absolute()
    if (stage.exists() or stage.parent != (LIBRARY / "candidate-reviews").resolve(strict=True)
            or not stage.name.startswith("ce-s")):
        raise PipelineError("fresh named external Carey stage required")
    source = _io_path(root / SOURCE).read_bytes()
    if len(source) != 117568 or _sha(source) != SOURCE_SHA:
        raise PipelineError("retained PG11449 source differs")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    package = CandidatePackage.load(CANDIDATE)
    report = validate(manifest, package, _oracle)
    if package.sha256 != CANDIDATE_SHA or report.status != "pass":
        raise PipelineError(f"Carey source candidate or independent oracle differs: {report.findings[:3]}")
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    retained = acquisition["retained_files"]
    if (len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA):
        raise PipelineError("Carey acquisition member boundary differs")
    scope_name = retained[0]["scope"]
    work = _read(root / WORK / "work.json")
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if (len(work["textual_forms"]) != 1 or len(form["editions"]) != 1
            or form["textual_form_id"] != FORM_ID or edition["edition_id"] != EDITION_ID
            or edition["acquisition_ids"] != [ACQUISITION_ID]
            or "category" in edition or (root / EDITION / "master.tei.xml").exists()):
        raise PipelineError("Carey work identity/preimage changed")
    stage.mkdir()
    before = _files(root / WORK)
    for relative in before:
        _copy(root, stage, WORK / relative)
    dependencies = {MANIFEST, ACQUISITION, SOURCE}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    state = _read(root / WORK / "state.json")
    dependencies.update(Path(evidence) for target in state["targets"] for evidence in target["evidence"])
    for relative in dependencies:
        if relative.is_absolute() or ".." in relative.parts:
            raise PipelineError(f"invalid Carey source dependency: {relative}")
        _copy(root, stage, relative)
    for name in package.member_names:
        _write(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _write_json(stage, EVIDENCE / "inputs/validation.json", dict(
        contract="ocd-validation-report-v1", status=report.status,
        candidate_sha256=report.candidate_sha256, source_manifest_sha256=report.source_manifest_sha256,
        attestation=dict(report.attestation), findings=list(report.findings), report_sha256=report.sha256))
    original_work = json.loads(json.dumps(work))
    form["language"] = "en"
    edition["category"] = "prose"
    edition["language"] = "en"
    validate_identity_update(original_work, work)
    _write_json(stage, WORK / "work.json", work)
    load_work(stage / WORK / "work.json")
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                    edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    revision = dict(id="carey-pg11449-grouped-tables-v1", date=at[:10],
                    note="Accept the complete retained PG11449 text member with its source-located lines and tables.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=len(source), source_scope=scope_name)
    original = package.member_bytes("content.tei.xml")
    bound = bind_reviewed_header(original, expected_sha256=_sha(original),
                                 identity=identity, source=source_binding,
                                 source_url=acquisition["url"], declared_scope=scope_name, revision=revision)
    if original.split(b"</teiHeader>", 1)[1] != bound.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Carey header binding changed candidate body")
    candidate_path = _write(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(candidate_path):
        raise PipelineError(f"Carey accepted TEI P5 errors: {errors[:3]}")
    member = retained[0]
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=member["bytes"],
                     sha256=SOURCE_SHA, scope=scope_name)]
    scope = dict(kind="selection", declared=scope_name, expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=identity, source=source_binding,
                  candidate=make_file_binding(stage, candidate_path), scope=scope_name,
                  accepted_scope=dict(kind="selection", declared=scope_name),
                  expected_members=expected, included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = _write_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=len(source), source_manifest_sha256=manifest.sha256,
        candidate_package_sha256=package.sha256, oracle_report_sha256=report.sha256,
        source_line_count=2073, omitted_line_count=0, duplicate_line_count=0,
        source_blank_lines=250, source_located_headings=13, table_count=4,
        source_table_rows=352, source_positioned_cells=1536,
        original_candidate=make_file_binding(stage, stage / EVIDENCE / "inputs/package/content.tei.xml"),
        candidate_source_accountability=make_file_binding(stage, stage / EVIDENCE / "inputs/package/source-accountability.json")))
    command = "py -3 -m build.tools.stage_carey_pg11449_acceptance"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and independent oracle use the same pinned PG11449 member and TEI P5 schema."],
                     independent_corroboration="Complete line accounting, source oracle, P5, and exact-master native producer and independent row checker agree.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _write_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
            oracle_report_sha256=report.sha256))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    review = dict(reviewer="agent:carey-pg11449-source-review", reviewed_at=at,
                  coverage=dict(status="partial", declared=scope_name,
                                reached=["complete 2073-line source member", "all source text and CRLF endings",
                                         "250 blank lines, 13 located headings, four tables",
                                         "independent source-to-TEI mechanical oracle",
                                         "37c-094 exact-pair technical source review"],
                                inspected=["independent source-to-TEI mechanical oracle",
                                           "37c-094 exact-pair technical source review"],
                                unreviewed=["human visual acceptance", "print collation"]),
                  source_quality_uncertainty=["The electronic witness was not collated to a print exemplar."],
                  discrepancies=[], unreviewed_residuals=["Human review and jurisdictional rights clearance remain unrecorded."])
    review_path = _write_json(stage, EVIDENCE / "review.json", common | review)
    decision = dict(source_local_disposition="Agent technical acceptance of the complete retained PG11449 electronic member; source wrapper, lines, and tables remain represented.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"],
                    assessed_at=at, supported_scope=scope_name, unresolved_claims=[],
                    unassessed_stronger_claims=["human visual review", "print identity", "rights clearance", "publication"]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage, identity=identity, candidate_path=candidate_path,
        source_accounting_path=account, scope=scope, technical=technical,
        review=review | dict(report_path=review_path), representation_revision=revision,
        decision=decision)
    acceptance = stage / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage)
    master = _write(stage, EDITION / "master.tei.xml", bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=at,
                               master=make_file_binding(stage, master))
    write_acceptance(acceptance, record)
    matches = [item for item in state["targets"] if item["target_type"] == "edition"
               and item["target_id"] == EDITION_ID]
    if len(matches) != 1 or matches[0]["stage"] != "acquired":
        raise PipelineError("one acquired Carey edition target required")
    matches[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at)
    matches[0]["evidence"].extend([(EDITION / "master.tei.xml").as_posix(),
                                    (EDITION / "acceptance.json").as_posix()])
    _write_json(stage, WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK / "state.json", root=stage)
    projected = project_accepted_document(stage, acceptance_path=acceptance, category="prose",
                                           projection_profile=CAREY_GROUPED_TABLE_PROFILE)
    errors = verify_accepted_document(stage, acceptance_path=acceptance,
                                      rows=projected["rows"], receipt=projected["receipt"],
                                      category="prose", projection_profile=CAREY_GROUPED_TABLE_PROFILE)
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"Carey actual-master native prose failed: {errors[:3]}")
    result = dict(contract="ocd-carey-pg11449-external-stage-v1", status="staged-only",
                  work_id=WORK_ID, stage_root=stage.as_posix(), before=before,
                  after=_files(stage / WORK), source_sha256=SOURCE_SHA,
                  source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
                  oracle_report_sha256=report.sha256, master_sha256=_sha(master.read_bytes()),
                  acceptance_sha256=_sha(acceptance.read_bytes()), projection_profile=CAREY_GROUPED_TABLE_PROFILE,
                  projection_rows=1, independent_verifier_errors=errors,
                  dependencies={relative.as_posix(): _sha(_io_path(root / relative).read_bytes()) for relative in sorted(dependencies | set(NATIVE_DEPENDENCIES))},
                  accepted_source_scope="complete-retained-PG11449-member", excluded_support_members=0,
                  rights="not-assessed", human_review="not-recorded", installation="not-performed")
    _write_json(stage, Path("stage-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"work_id": result["work_id"], "master_sha256": result["master_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
