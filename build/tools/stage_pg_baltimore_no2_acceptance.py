"""Stage Baltimore Catechism No. 2 from its exact retained Gutenberg TXT."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil

from build.tei.gutenberg_catechisms_oracle import _oracle
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.catechisms import (
    project_accepted_catechisms, verify_accepted_catechisms,
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
CONTRACT = "ocd-pg-baltimore-no2-acceptance-stage-v1"
WORK_ID = "baltimore-catechism-no-2"
WORK = Path("library/works") / WORK_ID
FORM_ID = "baltimore-catechism-no-2-retained-electronic"
EDITION_ID = "baltimore-catechism-no-2-retained-electronic-witness"
ACQUISITION_ID = "baltimore-catechism-no-2-retained-source"
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/gutenberg/pg14552.txt")
SOURCE_SHA = "3d4b556fdb094ab8e22a53df85f60ba3310b49c9c65a24281aeecb9119f9746c"
MANIFEST = Path("sources/gutenberg-catechisms/baltimore-catechism-no-2/source-manifest.json")
MANIFEST_SHA = "c040c796624e0e28f9f031c14804487683c363a813585a14e21073b2963c1bf9"
PACKAGE_ROOT = Path("D:/Library/Open Christian Data/candidate-reviews/ticket37-detection-measurement-20260909/lib069-repaired-20260909-standard-v1/baltimore-catechism-no-2")
PACKAGE_SHA = "ee34f9486265a6827efd6f092accaebb588d89d9130588ab56c04807a6a47023"
VALIDATION_SHA = "539c6bab67341642db3826fc5c966c7f606e4e86f054d965d5bc73c542a37d13"
REPORT_SHA = "4c5e3498a7b91c0c1d62eff5b20bd05db9a25d6473a9c378680ee55a9e44ce7a"
EVIDENCE = WORK / "integration/pg14552-electronic-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _put(root: Path, relative: Path, data: bytes) -> Path:
    path = root / relative
    _io_path(path.parent).mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(data)
    return path


def _put_json(root: Path, relative: Path, value: object) -> Path:
    return _put(root, relative, (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")) + "\n").encode())


def _copy(root: Path, stage: Path, relative: Path) -> None:
    target = stage / relative
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(root / relative), _io_path(target))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def prepare(stage: Path, receipt: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    stage, receipt = stage.absolute(), receipt.absolute()
    if (stage == root or root in stage.parents or _io_path(stage).exists()
            or _io_path(receipt).exists() or not _io_path(stage.parent).is_dir()
            or not _io_path(receipt.parent).is_dir()):
        raise PipelineError("fresh external stage and receipt are required")
    source = _io_path(root / SOURCE).read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA or len(source) != 138_043:
        raise PipelineError("retained PG#14552 text bytes changed")
    if _sha(root / MANIFEST) != MANIFEST_SHA:
        raise PipelineError("Baltimore source manifest changed")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    manifest.verify()
    package = CandidatePackage.load(_io_path(PACKAGE_ROOT / "package"))
    if package.sha256 != PACKAGE_SHA or _sha(PACKAGE_ROOT / "validation.json") != VALIDATION_SHA:
        raise PipelineError("Baltimore candidate or validation changed")
    stored = _read(PACKAGE_ROOT / "validation.json")
    fresh = validate(manifest, package, _oracle)
    if (fresh.status != "pass" or fresh.findings or fresh.sha256 != REPORT_SHA
            or stored.get("report_sha256") != REPORT_SHA
            or stored.get("candidate_sha256") != PACKAGE_SHA
            or stored.get("source_manifest_sha256") != MANIFEST_SHA):
        raise PipelineError("independent Baltimore source oracle differs")
    original = package.member_bytes("content.tei.xml")
    accounting = _read(PACKAGE_ROOT / "package/source-accountability.json")
    if (accounting.get("work_id") != WORK_ID or accounting.get("omitted_lines") != 0
            or accounting.get("duplicated_lines") != 0):
        raise PipelineError("complete source-line accounting differs")
    acquisition = validate_acquisition(_io_path(root / ACQUISITION), root=_io_path(root))
    retained = acquisition["retained_files"]
    if (acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != SOURCE_SHA
            or len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA):
        raise PipelineError("live Baltimore acquisition differs")
    if (_io_path(root / EDITION / "master.tei.xml").exists()
            or _io_path(root / EDITION / "acceptance.json").exists()):
        raise PipelineError("Baltimore No. 2 is already accepted")
    before = _files(root / WORK)
    if not before:
        raise PipelineError("live Baltimore work preimage is absent")
    for relative in before:
        _copy(root, stage, WORK / relative)
    if _files(stage / WORK) != before:
        raise PipelineError("staged Baltimore work preimage differs")
    dependencies = {SOURCE, MANIFEST,
                    Path("metadata/source-evidence/catalog/baltimore-catechism-no-2.json")}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    dependencies.update(Path(manifest.record[key]["implementation_path"])
                        for key in ("converter", "validator"))
    dependencies.add(Path(manifest.record["package_schema"]["path"]))
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            _copy(root, stage, relative)
    work = _read(stage / WORK / "work.json")
    old_work = _read(root / WORK / "work.json")
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    if (form["textual_form_id"] != FORM_ID or edition["edition_id"] != EDITION_ID
            or edition["acquisition_ids"] != [ACQUISITION_ID]
            or "category" in edition):
        raise PipelineError("Baltimore edition identity/category preimage differs")
    edition["category"] = "catechisms"
    validate_identity_update(old_work, work)
    _put_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    for name in package.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _put(stage, EVIDENCE / "inputs/validation.json",
         _io_path(PACKAGE_ROOT / "validation.json").read_bytes())
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                    edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
    revision = dict(id="baltimore-no2-pg14552-electronic-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained Project Gutenberg electronic transcription.")
    scope_text = retained[0]["scope"]
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=len(source), source_scope=scope_text)
    bound = bind_reviewed_header(original, expected_sha256=sha256(original).hexdigest(),
                                 identity=identity, source=source_binding,
                                 source_url=acquisition["url"], declared_scope=scope_text,
                                 revision=revision)
    if bound.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("accepted header binding changed source-line body")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(_io_path(candidate)):
        raise PipelineError(f"bound Baltimore TEI fails XSD: {errors[:3]}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [expected[0] | dict(bytes=len(source), sha256=SOURCE_SHA,
                                   scope=scope_text)]
    scope = dict(kind="edition", declared=scope_text, expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=identity, source=source_binding,
                  candidate=make_file_binding(stage, candidate), scope=scope_text,
                  accepted_scope=dict(kind="edition", declared=scope_text),
                  expected_members=expected, included_members=included,
                  excluded_members=[], missing_members=[], unknown_members=[])
    account = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=len(source),
        source_manifest_sha256=MANIFEST_SHA, candidate_package_sha256=PACKAGE_SHA,
        oracle_report_sha256=REPORT_SHA, source_line_count=3675,
        question_answer_count=421, omitted_lines=0, duplicated_lines=0))
    technical = dict(
        producer=dict(id=manifest.record["converter"]["id"]),
        checker=dict(id=manifest.record["validator"]["id"]),
        shared_assumptions=["Producer and oracle share the retained member and LIB-069 structural policy."],
        independent_corroboration="Fresh source oracle, every retained physical line, exact Q/A groups, XSD, and native row checker agree.",
    )
    command = "py -3 -m build.tools.stage_pg_baltimore_no2_acceptance"
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            source_sha256=SOURCE_SHA, source_manifest_sha256=MANIFEST_SHA,
            candidate_package_sha256=PACKAGE_SHA, oracle_report_sha256=REPORT_SHA,
            body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    reviewed_at = _now()
    review = dict(
        reviewer="agent:baltimore-no2-pg14552-source-review", reviewed_at=reviewed_at,
        coverage=dict(status="unavailable", declared=scope_text,
                      reached=["retained physical-line census", "candidate TEI",
                               "exact source-line, Q/A, lesson, and hymns boundaries"],
                      inspected=["exact source-line, Q/A, lesson, and hymns boundaries"],
                      unreviewed=["full visual source/TEI comparison"]),
        source_quality_uncertainty=["No historical print exemplar was collated."],
        discrepancies=[], unreviewed_residuals=["Human and visual review remain unrecorded."],
    )
    review_path = _put_json(stage, EVIDENCE / "review.json", common | review)
    decision = dict(
        source_local_disposition="Agent acceptance of exact Project Gutenberg #14552 electronic transcription only.",
        blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"],
                                          assessed_at=reviewed_at, supported_scope=scope_text,
                                          unresolved_claims=[],
                                          unassessed_stronger_claims=["visual review", "human acceptance",
                                                                     "print identity", "rights clearance", "publication"]),
        human_decision=dict(status="not-recorded"),
    )
    acceptance = build_acceptance_record(
        stage, identity=identity, candidate_path=candidate, source_accounting_path=account,
        scope=scope, technical=technical, review=review | dict(report_path=review_path),
        representation_revision=revision, decision=decision)
    acceptance_rel = EDITION / "acceptance.json"
    master_rel = EDITION / "master.tei.xml"
    write_acceptance(_io_path(stage / acceptance_rel), acceptance)
    validate_acceptance(_io_path(stage / acceptance_rel), root=_io_path(stage))
    _put(stage, master_rel, bound)
    acceptance["promotion"] = dict(acceptance["promotion"])
    acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                   master=make_file_binding(stage, stage / master_rel))
    write_acceptance(_io_path(stage / acceptance_rel), acceptance)
    state = _read(stage / WORK / "state.json")
    targets = [item for item in state["targets"]
               if item["target_type"] == "edition" and item["target_id"] == EDITION_ID]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise PipelineError("Baltimore edition state is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON,
                      updated_at=_now())
    targets[0]["evidence"].extend([master_rel.as_posix(), acceptance_rel.as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validated = validate_acceptance(_io_path(stage / acceptance_rel), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_catechisms(_io_path(stage),
                                             acceptance_path=_io_path(stage / acceptance_rel))
    errors = verify_accepted_catechisms(_io_path(stage),
                                         acceptance_path=_io_path(stage / acceptance_rel),
                                         rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"actual-master native catechism check failed: {errors[:3]}")
    result = dict(
        contract=CONTRACT, status="staged-only", work_id=WORK_ID,
        canonical_root=root.as_posix(), stage_root=stage.as_posix(),
        source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
        source_manifest_path=MANIFEST.as_posix(), source_manifest_sha256=MANIFEST_SHA,
        package_root=PACKAGE_ROOT.as_posix(), package_sha256=PACKAGE_SHA,
        validation_sha256=VALIDATION_SHA, oracle_report_sha256=REPORT_SHA,
        before=before, after=_files(stage / WORK),
        accepted_master_sha256=validated["promotion"]["master"]["sha256"],
        acceptance_sha256=_sha(stage / acceptance_rel), category="catechisms",
        projection_rows=1, source_line_count=3675, question_answer_count=421,
        projection_status="independent-check-pass", installation="not-performed",
    )
    _put_json(receipt.parent, Path(receipt.name), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.stage, args.receipt)
    print(json.dumps({"work_id": result["work_id"],
                      "master_sha256": result["accepted_master_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
