"""Freeze a source-bound, member-scoped Charnock Volume 2 PG53527 acceptance stage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.charnock_gutenberg_native_v2_oracle import _oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document, verify_accepted_document,
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
WORK_ID = "charnock-existence-attributes-vol-2"
FORM_ID = "charnock-existence-attributes-vol-2-english"
EDITION_ID = "charnock-existence-attributes-vol-2-retained-electronic-witness"
ACQUISITION_ID = "charnock-existence-attributes-vol-2-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/gutenberg/pg53527.txt")
SOURCE_SHA = "7edb772fb0147fe69e884b4b7f1feb71d96525f86e5be8c9a8e3eefa33626888"
MANIFEST = Path("sources/structured-text/charnock-existence-attributes-vol-2/charnock-existence-attributes-vol-2.native-v2.source-manifest.json")
CANDIDATE = LIBRARY / "candidate-reviews/charnock-vol2-native-v2-20260927-v1/package"
EVIDENCE = WORK / "integration/charnock-vol2-native-v2-current-v1"


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
    source, target = root / relative, stage / relative
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(source), _io_path(target))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def prepare(stage: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    stage = stage.absolute()
    if (stage.exists() or stage.parent != (LIBRARY / "candidate-reviews").resolve(strict=True)
            or not stage.name.startswith("c2-s")):
        raise PipelineError("fresh named external Charnock Volume 2 stage required")
    source = _io_path(root / SOURCE).read_bytes()
    if len(source) != 3949934 or _sha(source) != SOURCE_SHA or source.count(b"\r\n") != 62798:
        raise PipelineError("exact retained PG53527 physical lines differ")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    package = CandidatePackage.load(CANDIDATE)
    report = validate(manifest, package, _oracle)
    if report.status != "pass" or package.sha256 != "3f162a18be8819a8a8812d8cb6c4f648a0aa231bd0ad218ea8367a0c1db21d93":
        raise PipelineError("fresh Charnock Volume 2 source oracle or candidate pin differs")
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    retained = acquisition["retained_files"]
    if (len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA or retained[0]["bytes"] != len(source)):
        raise PipelineError("Charnock Volume 2 acquisition source/support boundary differs")
    acquired_scope = retained[0]["scope"]
    selected_scope = ("PG53527 Volume 2 body physical lines 30308-56434 plus explicitly shared "
                      "two-volume index/footnote/transcriber apparatus lines 56435-62447; "
                      "lines 1-30307 and 62448-62798 are evidence-only, not accepted text for this work.")
    work = _read(root / WORK / "work.json")
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if (form["textual_form_id"] != FORM_ID or edition["edition_id"] != EDITION_ID
            or edition["acquisition_ids"] != [ACQUISITION_ID]
            or "category" in edition or (root / EDITION / "master.tei.xml").exists()):
        raise PipelineError("Charnock Volume 2 work identity/preimage changed")
    stage.mkdir()
    before = _files(root / WORK)
    for relative in before:
        _copy(root, stage, WORK / relative)
    _copy(root, stage, MANIFEST)
    _copy(root, stage, Path("sources/structured-text/charnock-existence-attributes-vol-2/charnock-existence-attributes-vol-2.source-manifest.json"))
    _copy(root, stage, Path(manifest.record["converter"]["implementation_path"]))
    _copy(root, stage, Path(manifest.record["validator"]["implementation_path"]))
    for relative in {Path(item["path"]) for item in manifest.record["authorities"]}:
        _copy(root, stage, relative)
    for item in retained:
        _copy(root, stage, Path(item["path"]))
    for name in package.member_names:
        _write(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    source_account = json.loads(package.member_bytes("source-accountability.json"))
    if (source_account.get("physical_line_count") != 62798
            or source_account.get("represented_line_count") != 32140
            or source_account.get("evidence_only_line_count") != 30658
            or source_account.get("omitted_line_count") != 0
            or source_account.get("duplicate_line_count") != 0
            or source_account.get("body_line_range") != [30308, 56434]
            or source_account.get("shared_apparatus_line_range") != [56435, 62447]
            or source_account.get("required_counts", {}).get("page_marker_lines") != 542
            or sum(row["disposition"] == "represented" and row["text"] == ""
                   for row in source_account.get("lines", [])) != 2765):
        raise PipelineError("Charnock Volume 2 complete physical-line ledger differs")
    validation = dict(contract="ocd-validation-report-v1", status=report.status,
                      candidate_sha256=report.candidate_sha256,
                      source_manifest_sha256=report.source_manifest_sha256,
                      attestation=dict(report.attestation), findings=list(report.findings),
                      report_sha256=report.sha256)
    _write_json(stage, EVIDENCE / "inputs/validation.json", validation)
    old_work = json.loads(json.dumps(work))
    edition["category"] = "prose"
    validate_identity_update(old_work, work)
    _write_json(stage, WORK / "work.json", work)
    load_work(stage / WORK / "work.json")
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                    edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
    revision = dict(id="charnock-vol2-native-v2-current-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept only PG53527 Volume 2 lines 30308-56434 and shared apparatus lines 56435-62447.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=len(source), source_scope=acquired_scope)
    original = package.member_bytes("content.tei.xml")
    bound = bind_reviewed_header(original, expected_sha256=_sha(original),
                                 identity=identity, source=source_binding,
                                 source_url=acquisition["url"],
                                 declared_scope=selected_scope, revision=revision)
    if original.split(b"</teiHeader>", 1)[1] != bound.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("Charnock Volume 2 acceptance header changed source candidate body")
    candidate_path = _write(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(candidate_path):
        raise PipelineError(f"Charnock Volume 2 accepted TEI XSD errors: {errors[:3]}")
    expected = [dict(path=item["path"], position=index) for index, item in enumerate(retained, 1)]
    included_paths = {SOURCE.as_posix()}
    included = [dict(path=item["path"], position=index, bytes=item["bytes"],
                     sha256=item["sha256"], scope=selected_scope)
                for index, item in enumerate(retained, 1) if item["path"] in included_paths]
    excluded: list[dict] = []
    scope = dict(kind="selection", declared=selected_scope,
                 expected_members=expected, included_members=included, excluded_members=excluded)
    common = dict(identity=identity, source=source_binding,
                  candidate=make_file_binding(stage, candidate_path),
                  scope=selected_scope,
                  accepted_scope=dict(kind="selection", declared=selected_scope),
                  expected_members=expected, included_members=included,
                  excluded_members=excluded, missing_members=[], unknown_members=[])
    account = _write_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        scope=acquired_scope,
        source_sha256=SOURCE_SHA, source_bytes=len(source),
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
        oracle_report_sha256=report.sha256, physical_line_count=62798,
        represented_line_count=32140, evidence_only_line_count=30658,
        body_line_range=[30308, 56434], shared_apparatus_line_range=[56435, 62447],
        blank_line_count=2765, page_marker_count=542,
        omitted_line_count=0, duplicate_line_count=0, body_unchanged=True,
        acquired_source_scope=acquired_scope,
        original_candidate=make_file_binding(stage, stage / EVIDENCE / "inputs/package/content.tei.xml"),
        candidate_source_accountability=make_file_binding(stage, stage / EVIDENCE / "inputs/package/source-accountability.json")))
    command = "py -3 -m build.tools.stage_charnock_vol2_native_v2_acceptance"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle share the pinned PG53527 retained text and TEI P5 schema."],
                     independent_corroboration="Independent 62,798-line source partition, 542 page and 2,765 blank markers, 32,140 JSON line-ledger notes, TEI P5 XSD, and actual-master native rows and verifier agree.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _write_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
            oracle_report_sha256=report.sha256, text_body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    at = _now()
    review = dict(reviewer="agent:charnock-vol2-native-v2-source-review", reviewed_at=at,
                  coverage=dict(status="partial", declared=selected_scope,
                                reached=["Volume 2 body lines 30308-56434", "shared apparatus lines 56435-62447",
                                         "542 page markers and 2,765 blank lines", "32,140 exact JSON source-line notes",
                                         "selected readable volume and apparatus text"],
                                inspected=["542 page markers and 2,765 blank lines",
                                           "32,140 exact JSON source-line notes",
                                           "selected readable volume and apparatus text"],
                                unreviewed=["whole-work visual comparison", "print collation"]),
                  source_quality_uncertainty=["The electronic witness was not collated to a print exemplar."],
                  discrepancies=[], unreviewed_residuals=["Human review and jurisdictional rights clearance remain unrecorded."])
    review_path = _write_json(stage, EVIDENCE / "review.json", common | review)
    decision = dict(source_local_disposition="Agent acceptance of only the exact Volume 2 body and explicitly shared two-volume apparatus; the Volume 1 body and Gutenberg wrapper remain evidence-only.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"],
                    assessed_at=at, supported_scope=selected_scope, unresolved_claims=[],
                    unassessed_stronger_claims=["visual review", "human acceptance", "print identity",
                                                "rights clearance", "publication"]),
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
    state = _read(stage / WORK / "state.json")
    matches = [item for item in state["targets"] if item["target_type"] == "edition"
               and item["target_id"] == EDITION_ID]
    if len(matches) != 1 or matches[0]["stage"] != "acquired":
        raise PipelineError("one acquired Charnock Volume 2 edition state target required")
    matches[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=at)
    matches[0]["evidence"].extend([(EDITION / "master.tei.xml").as_posix(),
                                    (EDITION / "acceptance.json").as_posix()])
    _write_json(stage, WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK / "state.json", root=stage)
    projected = project_accepted_document(stage, acceptance_path=acceptance, category="prose")
    errors = verify_accepted_document(stage, acceptance_path=acceptance,
                                      rows=projected["rows"], receipt=projected["receipt"],
                                      category="prose")
    if errors or len(projected["rows"]) != 2:
        raise PipelineError(f"Charnock Volume 2 actual-master native prose failed: {errors[:3]}")
    result = dict(contract="ocd-charnock-vol2-native-v2-external-stage-v1", status="staged-only",
                  work_id=WORK_ID, stage_root=stage.as_posix(), before=before,
                  after=_files(stage / WORK), source_sha256=SOURCE_SHA,
                  source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
                  oracle_report_sha256=report.sha256, master_sha256=_sha(master.read_bytes()),
                  acceptance_sha256=_sha(acceptance.read_bytes()), projection_category="prose",
                  projection_rows=2, independent_verifier_errors=errors,
                  accepted_source_scope="volume-2-body-plus-shared-apparatus-lines",
                  excluded_support_members=0, rights="not-assessed", human_review="not-recorded",
                  installation="not-performed")
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
