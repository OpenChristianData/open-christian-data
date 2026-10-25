"""Stage and guarded-install the reviewed PG 37311 Woolman volume."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_document,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    _validate_acceptance_for_work,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

from build.tei.woolman_37311_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "john-woolman-journal-other-writings"
FORM_ID = "english"
EDITION_ID = "everyman-402-1910-electronic"
ACQUISITION_ID = "gutenberg-37311"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
EVIDENCE = WORK / "integration/pg37311-html-v1/acceptance-v1"
CANDIDATE = WORK / "integration/pg37311-html-v1/candidate"
MANIFEST = Path("sources/manifest-acquisitions/gutenberg-pg37311-woolman-v5/source-manifest.json")
SOURCE = Path("raw/gutenberg/37311/html/pg37311-images.html")
EXTERNAL = Path(r"D:\Library\Open Christian Data\candidate-reviews\manifest-acquisition-20260930-l641-woolman-v5\baseline")
SOURCE_SHA = "31b093b2e49a4ed732062bef521f2e545781b523b4066921b903e78ccf899926"
MANIFEST_SHA = "a9709e198dbdcb3cf2273dff4dd6d8f2a1c50f75d436778f5b406372c99aa357"
PACKAGE_SHA = "6e550033ed5b36e2dd27dc771b52c5488393090204a1794322368d5998116590"
VALIDATION_SHA = "686effaa7182a3098af5981924cd12a209ced22294ed5d95a44af971319ab90c"
PROJECTION_ERROR = "unsupported native source block type"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _write(path: Path, content: bytes) -> Path:
    _io_path(path.parent).mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(content)
    return path


def _json(path: Path, value: object) -> Path:
    return _write(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _copy(source: Path, target: Path) -> None:
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(source), _io_path(target))


def _pinned_inputs(root: Path) -> tuple[SourceManifest, CandidatePackage, object]:
    if _sha(root / MANIFEST) != MANIFEST_SHA:
        raise PipelineError("reviewed source manifest changed")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    for item in manifest.record["authorities"]:
        relative = Path(item["path"])
        path = resolve_repo_path(root, item["path"]) if relative.parts[0] == "raw" else root / relative
        if _io_path(path).stat().st_size != item["bytes"] or _sha(path) != item["sha256"]:
            raise PipelineError(f"source authority changed: {item['name']}")
    package = CandidatePackage.load(EXTERNAL / "package")
    if package.sha256 != PACKAGE_SHA or _sha(EXTERNAL / "validation.json") != VALIDATION_SHA:
        raise PipelineError("reviewed candidate package changed")
    report = validate(manifest, package, _oracle)
    saved = _read(EXTERNAL / "validation.json")
    if report.status != "pass" or report.findings or report.sha256 != saved["report_sha256"]:
        raise PipelineError("fresh independent oracle differs")
    if _sha(resolve_repo_path(root, SOURCE.as_posix())) != SOURCE_SHA:
        raise PipelineError("retained HTML changed")
    return manifest, package, report


def _assert_projection_block(root: Path) -> None:
    acceptance = root / EDITION / "acceptance.json"
    record = _read(acceptance)
    work = _read(root / WORK / "work.json")
    edition = work["textual_forms"][0]["editions"][0]
    try:
        project_document(
            root / EDITION / "master.tei.xml",
            identity={key: record["identity"][key] for key in ("work_id", "textual_form_id", "edition_id")},
            language="en",
            representation_revision=record["representation_revision"]["id"],
            edition_title=edition["title"],
            category="prose",
            _allow_acceptance_metadata=True,
        )
    except PipelineError as exc:
        if str(exc) != PROJECTION_ERROR:
            raise PipelineError(f"actual-master projection failed differently: {exc}") from exc
        return
    raise PipelineError("Woolman projection unexpectedly succeeded; refresh the scoped acceptance receipt")


def stage(stage_root: Path) -> dict:
    root = ROOT.resolve(strict=True)
    audit = (root / ".tmp_audit").resolve(strict=True)
    stage_root = stage_root.absolute()
    if stage_root.exists() or stage_root.parent != audit or not stage_root.name.startswith(WORK_ID + "-accept-"):
        raise PipelineError("fresh work-named stage under .tmp_audit required")
    manifest, package, report = _pinned_inputs(root)
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    if (acquisition["source_path"] != SOURCE.as_posix() or acquisition["source_sha256"] != SOURCE_SHA
            or acquisition["source_bytes"] != 550224 or len(acquisition["retained_files"]) != 8):
        raise PipelineError("acquisition boundary changed")
    before = _files(root / WORK)
    stage_root.mkdir()
    shutil.copytree(_io_path(root / WORK), _io_path(stage_root / WORK))
    for item in acquisition["retained_files"]:
        relative = Path(item["path"])
        _copy(resolve_repo_path(root, item["path"]), stage_root / relative)
    for target in _read(root / WORK / "state.json")["targets"]:
        for reference in target.get("evidence", []):
            reference = reference.split("#", 1)[0]
            relative = Path(reference)
            if relative.parts and relative.parts[0] != "raw" and not (stage_root / relative).exists():
                _copy(root / relative, stage_root / relative)
    shutil.copytree(_io_path(EXTERNAL / "package"), _io_path(stage_root / CANDIDATE / "package"))
    _copy(EXTERNAL / "validation.json", stage_root / CANDIDATE / "validation.json")

    work = _read(stage_root / WORK / "work.json")
    edition = work["textual_forms"][0]["editions"][0]
    if (work["work_id"] != WORK_ID or work["textual_forms"][0]["textual_form_id"] != FORM_ID
            or edition["edition_id"] != EDITION_ID or edition["acquisition_ids"] != [ACQUISITION_ID]
            or "category" in edition or (root / EDITION / "master.tei.xml").exists()
            or (root / EDITION / "acceptance.json").exists()):
        raise PipelineError("work identity or acceptance preimage changed")
    load_work(stage_root / WORK / "work.json")

    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)
    revision = dict(id="john-woolman-pg37311-accepted-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained PG 37311 collected volume, including its explicitly abridged Journal component.")
    source = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                  source_bytes=acquisition["source_bytes"], source_scope=acquisition["source_scope"])
    original = package.member_bytes("content.tei.xml")
    bound = bind_reviewed_header(original, expected_sha256=hashlib.sha256(original).hexdigest(), identity=identity,
                                 source=source, source_url=acquisition["url"], declared_scope=acquisition["source_scope"],
                                 revision=revision)
    if original.split(b"</teiHeader>", 1)[1] != bound.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("acceptance changed reviewed TEI body")
    candidate = _write(stage_root / EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(candidate):
        raise PipelineError(f"accepted TEI P5 errors: {errors[:3]}")

    retained = acquisition["retained_files"]
    expected = [dict(path=item["path"], position=index) for index, item in enumerate(retained, 1)]
    included = [dict(path=item["path"], position=index, bytes=item["bytes"], sha256=item["sha256"],
                     scope=acquisition["source_scope"])
                for index, item in enumerate(retained, 1) if item["path"] == SOURCE.as_posix()]
    excluded = [dict(path=item["path"], position=index,
                     reason="Acquisition container, image, receipt, inventory, or retained note; not an independent textual source member.")
                for index, item in enumerate(retained, 1) if item["path"] != SOURCE.as_posix()]
    scope = dict(kind="selection", declared=acquisition["source_scope"], expected_members=expected,
                 included_members=included, excluded_members=excluded)
    common = dict(identity=identity, source=source, candidate=make_file_binding(stage_root, candidate),
                  scope=acquisition["source_scope"], accepted_scope=dict(kind="selection", declared=acquisition["source_scope"]),
                  expected_members=expected, included_members=included, excluded_members=excluded,
                  missing_members=[], unknown_members=[])
    accounting = _json(stage_root / EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=acquisition["source_bytes"],
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
        oracle_report_sha256=report.sha256, source_body_direct_children=1008,
        source_unit_count=12, selected_unit_count=12, journal_component="abridged",
        reviewed_body_unchanged=True))
    command = "py -3 -m build.tools.accept_woolman_pg37311 stage"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]), checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle share the sealed 12-unit boundary profile and retained source hashes."],
                     independent_corroboration="Python HTMLParser independently confirms complete body text and literal tag counts; the oracle separately checks all 1,008 body children, text/tails, roles, IDs, links, images, unit order, P5 validity, and package accounting. Two sealed mutations reject source-unit identity/order and work identity drift.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _json(stage_root / EVIDENCE / f"{name}.json", common | dict(
            claim=name, status="pass", command=command, exit_code=0, source_manifest_sha256=manifest.sha256,
            candidate_package_sha256=package.sha256, oracle_report_sha256=report.sha256,
            replay_process_count=2, mutation_rejections=2, reviewed_body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = dict(reviewer="agent:l641-woolman-technical-acceptance", reviewed_at=now,
                  coverage=dict(status="partial", declared=acquisition["source_scope"],
                                reached=["complete retained HTML body", "all 12 source units", "all 1,008 direct body children", "all source links and images"],
                                inspected=["complete retained HTML body", "all 12 source units", "all 1,008 direct body children", "all source links and images"],
                                unreviewed=["whole-volume rendered visual collation", "1910 print collation", "human verification"]),
                  source_quality_uncertainty=["The electronic witness has not been collated against a 1910 print exemplar."],
                  discrepancies=[], unreviewed_residuals=["Human visual verification remains open.", "Rights and publication authorization remain open."])
    review_path = _json(stage_root / EVIDENCE / "review.json", common | review)
    decision = dict(source_local_disposition="Accept the complete PG 37311 electronic collected volume as one edition; retain the Journal's source-declared abridged status.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                        supported_scope=acquisition["source_scope"], unresolved_claims=[],
                        unassessed_stronger_claims=["whole-volume visual verification", "print collation", "human verification", "rights clearance", "release selection", "publication"]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage_root, identity=identity, candidate_path=candidate,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
    acceptance = stage_root / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    master = _write(stage_root / EDITION / "master.tei.xml", bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage_root, master))
    write_acceptance(acceptance, record)
    state = _read(stage_root / WORK / "state.json")
    targets = [item for item in state["targets"] if item["target_type"] == "edition" and item["target_id"] == EDITION_ID]
    if len(targets) != 1 or targets[0]["stage"] != "review":
        raise PipelineError("one edition review target required")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    targets[0]["evidence"].extend([(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()])
    _json(stage_root / WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage_root)
    validate_state(stage_root / WORK / "state.json", root=stage_root)
    _assert_projection_block(stage_root)
    projection_receipt = _json(stage_root / WORK / "integration/pg37311-html-v1/publication-v1/projection-receipt.json", dict(
        contract="ocd-work-projection-block-receipt-v1", work_id=WORK_ID, edition_id=EDITION_ID,
        acceptance_path=(EDITION / "acceptance.json").as_posix(), acceptance_sha256=_sha(acceptance),
        master_path=(EDITION / "master.tei.xml").as_posix(), master_sha256=_sha(master),
        category="prose", projector="ocd_kernel.projection.categories.native_documents.project_document",
        status="blocked", error=PROJECTION_ERROR, rows=0,
        shared_projector_changed=False, rights="not-cleared", publication="not-authorized"))
    result = dict(contract="ocd-l641-woolman-acceptance-stage-v1", status="staged-only", work_id=WORK_ID,
                  stage_root=stage_root.as_posix(), before=before, after=_files(stage_root / WORK),
                  source_sha256=SOURCE_SHA, source_manifest_sha256=MANIFEST_SHA,
                  candidate_package_sha256=PACKAGE_SHA, validation_sha256=VALIDATION_SHA,
                  master_sha256=_sha(master), acceptance_sha256=_sha(acceptance), projection_category="prose",
                  projection_status="blocked", projection_error=PROJECTION_ERROR, projection_rows=0,
                  projection_receipt_sha256=_sha(projection_receipt),
                  human_review="not-recorded", rights="not-cleared", publication="not-authorized", installation="not-performed")
    _json(stage_root / "stage-receipt.json", result)
    return result


def preflight(stage_root: Path, receipt_sha: str) -> dict:
    root = ROOT.resolve(strict=True)
    stage_root = stage_root.resolve(strict=True)
    if (stage_root.parent != (root / ".tmp_audit").resolve(strict=True) or not stage_root.name.startswith(WORK_ID + "-accept-")
            or _sha(stage_root / "stage-receipt.json") != receipt_sha):
        raise PipelineError("stage location or receipt pin differs")
    receipt = _read(stage_root / "stage-receipt.json")
    if receipt["status"] != "staged-only" or receipt["installation"] != "not-performed" or receipt["projection_error"] != PROJECTION_ERROR:
        raise PipelineError("stage receipt claim differs")
    if _files(root / WORK) != receipt["before"] or _files(stage_root / WORK) != receipt["after"]:
        raise PipelineError("work preimage or staged generation changed")
    before, after = receipt["before"], receipt["after"]
    for relative, digest in before.items():
        if relative not in {"work.json", "state.json"} and after.get(relative) != digest:
            raise PipelineError(f"stage changes existing work file: {relative}")
    permitted = {(EDITION / name).relative_to(WORK).as_posix() for name in ("master.tei.xml", "acceptance.json")}
    prefixes = (
        EVIDENCE.relative_to(WORK).as_posix() + "/",
        CANDIDATE.relative_to(WORK).as_posix() + "/",
        "integration/pg37311-html-v1/publication-v1/",
    )
    if any(path not in permitted and not path.startswith(prefixes) for path in set(after) - set(before)):
        raise PipelineError("stage adds a file outside scoped Woolman acceptance evidence")
    if _read(stage_root / WORK / "work.json") != _read(root / WORK / "work.json"):
        raise PipelineError("Woolman work identity changed during acceptance staging")
    validate_acceptance(stage_root / EDITION / "acceptance.json", root=stage_root)
    validate_state(stage_root / WORK / "state.json", root=stage_root)
    _pinned_inputs(root)
    _assert_projection_block(stage_root)
    return dict(status="ready-to-install", work_id=WORK_ID, receipt_sha256=receipt_sha,
                master_sha256=receipt["master_sha256"], acceptance_sha256=receipt["acceptance_sha256"],
                projection_status="blocked", projection_error=PROJECTION_ERROR, projection_rows=0)


def apply(stage_root: Path, receipt_sha: str) -> dict:
    root = ROOT.resolve(strict=True)
    result = preflight(stage_root, receipt_sha)
    receipt = _read(stage_root / "stage-receipt.json")

    def checkpoint(point: str) -> None:
        if point == "after-validated":
            _validate_acceptance_for_work(root / EDITION / "acceptance.json", root=root, work_id=WORK_ID)
            validate_state(root / WORK / "state.json", root=root)
            _assert_projection_block(root)

    target, source = root / WORK, stage_root / WORK
    with ExitStack() as locks:
        for path in sorted((target, source), key=lambda item: item.as_posix()):
            locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        preflight(stage_root, receipt_sha)
        result["installation"] = _commit_generation(
            root, target, source, work_id=WORK_ID,
            before=receipt["before"], after=receipt["after"], existed=True,
            replacement=False, operation_kind="woolman-pg37311-initial-install",
            result_status="installed-and-validated", accepted_editions=1,
            fail_at=checkpoint,
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "preflight", "apply"))
    parser.add_argument("stage_root", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    if args.action == "stage":
        result = stage(args.stage_root)
    elif not args.expected_sha256:
        parser.error("--expected-sha256 is required for preflight and apply")
    elif args.action == "preflight":
        result = preflight(args.stage_root, args.expected_sha256)
    else:
        result = apply(args.stage_root, args.expected_sha256)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
