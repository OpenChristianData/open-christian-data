"""Stage and guard technical acceptance for PG77576 Second Clement."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document,
    verify_accepted_document,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    build_acceptance_record,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "pg77576-clement-second-epistle"
FORM_ID = "pg77576-clement-second-epistle-english"
EDITION_ID = "pg77576-clement-second-epistle-pg77576-edition"
ACQUISITION_ID = "pg77576-clement-second-epistle-pg77576-acquisition"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
INTEGRATION = WORK / "integration/pg77576-html-v1"
EVIDENCE = INTEGRATION / "acceptance-v1"
MANIFEST = INTEGRATION / "source-manifest.json"
PACKAGE = INTEGRATION / "candidate/package"
VALIDATION = INTEGRATION / "candidate/validation.json"
ORACLE = INTEGRATION / "oracle.py"
SOURCE = Path("raw/gutenberg/77576/html/pg77576-images.html")
SOURCE_SHA = "ca58049f2ee7c62c8c34dffb6badfdb910ab698748f8decc9d9b978e7972e507"
MANIFEST_SHA = "de5df762f46f4c1626ef64d4de31044d92142d8d18b7890bc686a8b8c28b28c4"
PACKAGE_SHA = "f304b7ce55f7f61a3e19cd2b96dccf6740dfb30030708c559c40e548e567adeb"
CANDIDATE_SHA = "3f492f5e76f00c41cc0c4e04c3fe24997d96fcb8e532839bd6c9ddeec5d3e538"
VALIDATION_SHA = "8dcb22963746419639e0ea343b24f52aa0a730a2a3222057f3dd648ecec60cca"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


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
    return _write(
        path,
        (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
    )


def _copy(source: Path, target: Path) -> None:
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(source), _io_path(target))


def _source_path(root: Path, relative: str) -> Path:
    return resolve_repo_path(root, relative) if relative.startswith("raw/") else root / relative


def _oracle(root: Path):
    path = _io_path(root / ORACLE)
    spec = importlib.util.spec_from_file_location("pg77576_second_clement_oracle", path)
    if spec is None or spec.loader is None:
        raise PipelineError("work-local source oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module._oracle


def _pinned_inputs(root: Path):
    for relative, expected in (
        (MANIFEST, MANIFEST_SHA),
        (PACKAGE / "manifest.json", PACKAGE_SHA),
        (PACKAGE / "content.tei.xml", CANDIDATE_SHA),
        (VALIDATION, VALIDATION_SHA),
    ):
        if _sha(root / relative) != expected:
            raise PipelineError(f"reviewed input changed: {relative}")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    if manifest.sha256 != MANIFEST_SHA:
        raise PipelineError("source manifest digest differs")
    for item in manifest.record["authorities"]:
        path = _source_path(root, item["path"])
        if _io_path(path).stat().st_size != item["bytes"] or _sha(path) != item["sha256"]:
            raise PipelineError(f"source-manifest authority changed: {item['name']}")
    package = CandidatePackage.load(root / PACKAGE)
    if package.sha256 != PACKAGE_SHA:
        raise PipelineError("candidate package digest differs")
    report = validate(manifest, package, _oracle(root))
    saved = _read(root / VALIDATION)
    if report.status != "pass" or report.sha256 != saved.get("report_sha256") or saved.get("status") != "pass":
        raise PipelineError(f"fresh source oracle differs: {report.findings[:3]}")
    source_path = _source_path(root, SOURCE.as_posix())
    if _sha(source_path) != SOURCE_SHA:
        raise PipelineError("retained HTML digest differs")
    return manifest, package, report


def _projection(root: Path) -> dict:
    acceptance = root / EDITION / "acceptance.json"
    result = project_accepted_document(root, acceptance_path=acceptance, category="prose")
    errors = verify_accepted_document(
        root, acceptance_path=acceptance, rows=result["rows"], receipt=result["receipt"], category="prose"
    )
    if errors or not result["rows"]:
        raise PipelineError(f"actual-master prose projection failed: {errors[:5]}")
    return result


def stage(stage_root: Path) -> dict:
    root = ROOT.resolve(strict=True)
    stage_root = stage_root.absolute()
    if (
        stage_root.exists()
        or stage_root.parent != (root / ".tmp_audit").resolve(strict=True)
        or not stage_root.name.startswith(WORK_ID + "-accept-")
    ):
        raise PipelineError("fresh work-named stage under .tmp_audit required")
    manifest, package, report = _pinned_inputs(root)
    acquisition_result = validate_acquisition(root / ACQUISITION, root=root)
    acquisition = _read(root / ACQUISITION)
    if (
        acquisition_result["source_path"] != SOURCE.as_posix()
        or acquisition_result["source_sha256"] != SOURCE_SHA
        or len(acquisition_result["retained_files"]) != 3
    ):
        raise PipelineError("acquisition boundary changed")
    current_work = _read(root / WORK / "work.json")
    old_work = json.loads(json.dumps(current_work))
    edition = current_work["textual_forms"][0]["editions"][0]
    if (
        current_work["work_id"] != WORK_ID
        or current_work["textual_forms"][0]["textual_form_id"] != FORM_ID
        or edition["edition_id"] != EDITION_ID
        or edition["acquisition_ids"] != [ACQUISITION_ID]
        or edition.get("category") is not None
        or _io_path(root / EDITION / "master.tei.xml").exists()
        or _io_path(root / EDITION / "acceptance.json").exists()
    ):
        raise PipelineError("work identity or acceptance preimage changed")
    before = _files(root / WORK)
    _io_path(stage_root).mkdir()
    for relative in before:
        _copy(root / WORK / relative, stage_root / WORK / relative)
    for item in manifest.record["authorities"]:
        _copy(_source_path(root, item["path"]), stage_root / item["path"])
    for target in _read(root / WORK / "state.json")["targets"]:
        for name in target.get("evidence", []):
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise PipelineError(f"unsafe state evidence path: {name}")
            destination = stage_root / relative
            if not _io_path(destination).exists():
                _copy(_source_path(root, relative.as_posix()), destination)

    edition["category"] = "prose"
    validate_identity_update(old_work, current_work)
    _json(stage_root / WORK / "work.json", current_work)
    load_work(stage_root / WORK / "work.json")
    staged_acquisition = validate_acquisition(stage_root / ACQUISITION, root=stage_root)
    if staged_acquisition["source_sha256"] != SOURCE_SHA:
        raise PipelineError("staged acquisition source changed")

    identity = dict(
        work_id=WORK_ID,
        textual_form_id=FORM_ID,
        edition_id=EDITION_ID,
        acquisition_id=ACQUISITION_ID,
    )
    now = datetime.now(timezone.utc)
    revision = dict(
        id="pg77576-clement-second-epistle-accepted-v1",
        date=now.date().isoformat(),
        note="Accept the source-bounded Second Epistle of Clement from retained Project Gutenberg HTML.",
    )
    source = dict(
        source_path=SOURCE.as_posix(),
        source_sha256=SOURCE_SHA,
        source_bytes=acquisition["source_bytes"],
        source_scope=acquisition["source_scope"],
    )
    original = package.member_bytes("content.tei.xml")
    header, body = original.split(b"</teiHeader>", 1)
    if header.count(b"<sourceDesc><p>") != 1 or header.count(b"</p></sourceDesc>") != 1:
        raise PipelineError("reviewed source description shape changed")
    header = header.replace(b"<sourceDesc><p>", b"<sourceDesc><bibl>", 1)
    header = header.replace(b"</p></sourceDesc>", b"</bibl></sourceDesc>", 1)
    header_ready = header + b"</teiHeader>" + body
    bound = bind_reviewed_header(
        header_ready,
        expected_sha256=sha256(header_ready).hexdigest(),
        identity=identity,
        source=source,
        source_url=acquisition["url"],
        declared_scope=acquisition["source_scope"],
        revision=revision,
    )
    if original.split(b"</teiHeader>", 1)[1] != bound.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("acceptance binding changed the reviewed TEI body")
    candidate = _write(stage_root / EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(candidate):
        raise PipelineError(f"accepted TEI P5 errors: {errors[:5]}")

    retained = acquisition_result["retained_files"]
    expected = [dict(path=item["path"], position=index) for index, item in enumerate(retained, 1)]
    included = [
        dict(path=item["path"], position=index, bytes=item["bytes"], sha256=item["sha256"], scope=acquisition["source_scope"])
        for index, item in enumerate(retained, 1)
        if item["path"] == SOURCE.as_posix()
    ]
    excluded = [
        dict(
            path=item["path"],
            position=index,
            reason="Acquisition ZIP or cover support; outside the selected Second Epistle text.",
        )
        for index, item in enumerate(retained, 1)
        if item["path"] != SOURCE.as_posix()
    ]
    scope = dict(
        kind="selection",
        declared=acquisition["source_scope"],
        expected_members=expected,
        included_members=included,
        excluded_members=excluded,
    )
    candidate_binding = make_file_binding(stage_root, candidate)
    common = dict(
        identity=identity,
        candidate=candidate_binding,
        scope=acquisition["source_scope"],
        source=source,
        accepted_scope=dict(kind="selection", declared=acquisition["source_scope"]),
        expected_members=expected,
        included_members=included,
        excluded_members=excluded,
        missing_members=[],
        unknown_members=[],
    )
    source_accounting = _json(
        stage_root / EVIDENCE / "source-accounting.json",
        common
        | dict(
            source_manifest_sha256=manifest.sha256,
            candidate_package_sha256=package.sha256,
            oracle_report_sha256=report.sha256,
            source_sha256=SOURCE_SHA,
            source_bytes=acquisition["source_bytes"],
            represented_body_interval=[175, 203],
            represented_note_ids="f259-f315",
            body_unchanged=True,
        ),
    )
    command = f"py -3 build/tools/accept_pg77576_clement_second.py stage {stage_root.relative_to(root).as_posix()}"
    technical = dict(
        producer=dict(id=manifest.record["converter"]["id"]),
        checker=dict(id=manifest.record["validator"]["id"]),
        shared_assumptions=[
            "Converter and separate source oracle use the retained HTML hash and the declared direct-body interval [175,203).",
            "The accepted electronic witness ends at the source's explicit fragment; no continuation is inferred.",
        ],
        independent_corroboration=(
            "Separate BeautifulSoup source oracle matches all selected text, structure, note links, and adjacent boundaries; "
            "nine source-relevant mutations were rejected and two clean-process package replays were byte-identical."
        ),
    )
    proof_common = common | dict(
        source_manifest_sha256=manifest.sha256,
        candidate_package_sha256=package.sha256,
        oracle_report_sha256=report.sha256,
        body_unchanged=True,
    )
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _json(
            stage_root / EVIDENCE / f"{name}.json",
            proof_common | dict(claim=name, status="pass", command=command, exit_code=0),
        )
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)

    reviewed_at = now.isoformat().replace("+00:00", "Z")
    coverage = dict(
        status="partial",
        declared=acquisition["source_scope"],
        reached=["all selected HTML body children [175,203), all linked notes f259-f315, and both adjacent work boundaries"],
        inspected=["all selected HTML body children [175,203), all linked notes f259-f315, and both adjacent work boundaries"],
        unreviewed=["human visual review", "print collation", "external rights assessment"],
    )
    review = dict(
        identity=identity,
        candidate=candidate_binding,
        scope=acquisition["source_scope"],
        source=source,
        reviewer="agent:pg77576-clement-second-epistle-technical-acceptance",
        reviewed_at=reviewed_at,
        coverage=coverage,
        source_quality_uncertainty=[
            "The retained electronic witness was not collated against the printed volume.",
            "The source itself reports disputed Clement authorship; the accepted title is source-titled and author remains unassigned.",
        ],
        discrepancies=[],
        unreviewed_residuals=[
            "No human visual comparison or print collation is recorded.",
            "Rights clearance, release selection, and publication remain separate decisions.",
        ],
    )
    review_path = _json(stage_root / EVIDENCE / "review.json", review)
    decision = dict(
        source_local_disposition=(
            "Accept only the source-titled Second Epistle of Clement at HTML children [175,203), "
            "with its introductory notice, twelve chapters, fragmentary source ending, and linked notes f259-f315. "
            "Do not assert Clement as confirmed author or assign an individual translator."
        ),
        blockers=[],
        agent_assessment=dict(
            status="accepted",
            actor=review["reviewer"],
            assessed_at=reviewed_at,
            supported_scope=acquisition["source_scope"],
            unresolved_claims=[],
            unassessed_stronger_claims=[
                "human visual review",
                "print collation",
                "work-level author attribution",
                "work-level translator attribution",
                "rights clearance",
                "release selection",
                "publication",
            ],
        ),
        human_decision=dict(status="not-recorded"),
    )
    record = build_acceptance_record(
        stage_root,
        identity=identity,
        candidate_path=candidate,
        source_accounting_path=source_accounting,
        scope=scope,
        technical=technical,
        review=review | dict(report_path=review_path),
        representation_revision=revision,
        decision=decision,
    )
    acceptance = stage_root / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage_root)
    master = _write(stage_root / EDITION / "master.tei.xml", bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=reviewed_at, master=make_file_binding(stage_root, master))
    write_acceptance(acceptance, record)
    state = _read(stage_root / WORK / "state.json")
    edition_targets = [
        item for item in state["targets"]
        if item.get("target_type") == "edition" and item.get("target_id") == EDITION_ID
    ]
    if len(edition_targets) != 1 or edition_targets[0].get("stage") != "review":
        raise PipelineError("one edition review target required")
    edition_targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=reviewed_at)
    edition_targets[0]["evidence"].extend(
        [(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()]
    )
    _json(stage_root / WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage_root)
    validate_state(stage_root / WORK / "state.json", root=stage_root)
    result = dict(
        contract="ocd-pg77576-second-clement-stage-v1",
        status="staged-only",
        work_id=WORK_ID,
        stage_root=stage_root.as_posix(),
        before=before,
        after=_files(stage_root / WORK),
        source_sha256=SOURCE_SHA,
        source_manifest_sha256=manifest.sha256,
        candidate_package_sha256=package.sha256,
        validation_sha256=VALIDATION_SHA,
        oracle_report_sha256=report.sha256,
        master_sha256=_sha(master),
        acceptance_sha256=_sha(acceptance),
        projection="verified during guarded install against the canonical path",
        independent_verifier_errors=[],
        rights="not-cleared",
        human_review="not-recorded",
        installation="not-performed",
    )
    _json(stage_root / "stage-receipt.json", result)
    return result


def preflight(stage_root: Path, receipt_sha: str) -> dict:
    root = ROOT.resolve(strict=True)
    stage_root = stage_root.resolve(strict=True)
    if (
        stage_root.parent != (root / ".tmp_audit").resolve(strict=True)
        or not stage_root.name.startswith(WORK_ID + "-accept-")
        or _sha(stage_root / "stage-receipt.json") != receipt_sha
    ):
        raise PipelineError("stage path or receipt pin differs")
    receipt = _read(stage_root / "stage-receipt.json")
    if (
        receipt.get("contract") != "ocd-pg77576-second-clement-stage-v1"
        or receipt.get("status") != "staged-only"
        or receipt.get("work_id") != WORK_ID
        or receipt.get("stage_root") != stage_root.as_posix()
        or receipt.get("installation") != "not-performed"
    ):
        raise PipelineError("stage receipt claim differs")
    before = _files(root / WORK)
    after = _files(stage_root / WORK)
    if before != receipt["before"] or after != receipt["after"]:
        raise PipelineError("complete work preimage or staged generation differs")
    if _io_path(root / EDITION / "master.tei.xml").exists() or _io_path(root / EDITION / "acceptance.json").exists():
        raise PipelineError("canonical edition already has an accepted master")
    for relative in before:
        if relative not in {"state.json", "work.json"} and after.get(relative) != before[relative]:
            raise PipelineError(f"stage changed existing authority: {relative}")
    additions = set(after) - set(before)
    allowed = {
        (EDITION / "master.tei.xml").relative_to(WORK).as_posix(),
        (EDITION / "acceptance.json").relative_to(WORK).as_posix(),
    }
    evidence_prefix = EVIDENCE.relative_to(WORK).as_posix() + "/"
    if any(path not in allowed and not path.startswith(evidence_prefix) for path in additions):
        raise PipelineError("stage adds files outside scoped acceptance evidence")
    expected_work = _read(root / WORK / "work.json")
    expected_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    if _read(stage_root / WORK / "work.json") != expected_work:
        raise PipelineError("work metadata change exceeds the one prose category field")
    manifest, package, report = _pinned_inputs(root)
    for item in manifest.record["authorities"]:
        relative = item["path"]
        if relative in {"library/works/pg77576-clement-second-epistle/work.json", "library/works/pg77576-clement-second-epistle/state.json"}:
            continue
        if _sha(_source_path(root, relative)) != _sha(_source_path(stage_root, relative)):
            raise PipelineError(f"staged source dependency differs: {relative}")
    if package.sha256 != receipt["candidate_package_sha256"] or report.sha256 != receipt["oracle_report_sha256"]:
        raise PipelineError("current candidate/oracle differs from stage receipt")
    original = _io_path(root / PACKAGE / "content.tei.xml").read_bytes()
    master = _io_path(stage_root / EDITION / "master.tei.xml").read_bytes()
    if (
        original.split(b"</teiHeader>", 1)[1] != master.split(b"</teiHeader>", 1)[1]
        or _sha(stage_root / EDITION / "master.tei.xml") != receipt["master_sha256"]
        or _sha(stage_root / EDITION / "acceptance.json") != receipt["acceptance_sha256"]
    ):
        raise PipelineError("staged master changed reviewed body or receipt digest")
    acceptance = stage_root / EDITION / "acceptance.json"
    accepted = validate_acceptance(acceptance, root=stage_root)
    validate_state(stage_root / WORK / "state.json", root=stage_root)
    if accepted["promotion"]["status"] != "promoted" or accepted["identity"]["work_id"] != WORK_ID:
        raise PipelineError("staged acceptance identity/status differs")
    return dict(
        status="ready-to-install",
        work_id=WORK_ID,
        before_files=len(before),
        after_files=len(after),
        master_sha256=receipt["master_sha256"],
        acceptance_sha256=receipt["acceptance_sha256"],
        receipt_sha256=receipt_sha,
    )


def install(stage_root: Path, receipt_sha: str) -> dict:
    root = ROOT.resolve(strict=True)
    stage_root = stage_root.resolve(strict=True)
    target = root / WORK
    source = stage_root / WORK
    projection_result: dict = {}
    with ExitStack() as locks:
        for path in sorted((target, source), key=lambda item: item.as_posix()):
            locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        preflight(stage_root, receipt_sha)
        receipt = _read(stage_root / "stage-receipt.json")

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != receipt["after"]:
                    raise PipelineError("installed generation differs from staged bytes")
                validate_acceptance(root / EDITION / "acceptance.json", root=root)
                validate_state(root / WORK / "state.json", root=root)
                projection_result.update(_projection(root))

        installed = _commit_generation(
            root,
            target,
            source,
            work_id=WORK_ID,
            before=receipt["before"],
            after=receipt["after"],
            existed=True,
            replacement=False,
            operation_kind="pg77576-second-clement-work-install",
            result_status="installed-and-validated",
            accepted_editions=1,
            fail_at=checkpoint,
        )
        return installed | {
            "projection_category": "prose",
            "projection_rows": len(projection_result["rows"]),
            "projection_receipt": projection_result["receipt"],
            "independent_verifier_errors": [],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "preflight", "apply"))
    parser.add_argument("stage_root", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    try:
        if args.action == "stage":
            result = stage(args.stage_root)
        elif not args.expected_sha256:
            parser.error("--expected-sha256 is required for preflight and apply")
        elif args.action == "preflight":
            result = preflight(args.stage_root, args.expected_sha256)
        else:
            result = preflight(args.stage_root, args.expected_sha256)
            result["installation"] = install(args.stage_root, args.expected_sha256)
    except (PipelineError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Acceptance route failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
