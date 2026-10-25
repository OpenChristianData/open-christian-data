"""Stage and guard the exact PG77576 Ignatius to the Virgin Mary acceptance."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "pg77576-ignatius-virgin-mary"
FORM_ID = "pg77576-ignatius-virgin-mary-english"
EDITION_ID = "pg77576-ignatius-virgin-mary-pg77576-edition"
ACQUISITION_ID = "pg77576-ignatius-virgin-mary-pg77576-acquisition"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
EVIDENCE = WORK / "integration/pg77576-html-v1/acceptance-v1"
MANIFEST = WORK / "integration/pg77576-html-v1/source-manifest.json"
PACKAGE = WORK / "integration/pg77576-html-v1/candidate/package"
VALIDATION = WORK / "integration/pg77576-html-v1/candidate/validation.json"
TECHNICAL = WORK / "integration/pg77576-html-v1/technical-evidence.json"
SOURCE = Path("raw/gutenberg/77576/html/pg77576-images.html")
SOURCE_SHA = "ca58049f2ee7c62c8c34dffb6badfdb910ab698748f8decc9d9b978e7972e507"
MANIFEST_SHA = "fbfdda7f234c3bde2f7abb2a4ea32abccaaa75b92c5571d8d48ffaba7e081399"
PACKAGE_SHA = "63737ad948ff583c391628903a2082d11c68f53f99dba2f17b82bf3ee7943dd3"
VALIDATION_SHA = "b13091fd4bde6b52dcd105bc9a5cd4505fe9ab21087a6270ddc9e403a2e68d09"
TECHNICAL_SHA = "5f990dd21461a4ce9cd74a08797aafe7b4ad1e7a059b27e15ec7fbd096616877"
REVIEW = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/PG77576_IGNATIUS_VIRGIN_MARY_INDEPENDENT_REVIEW_20260930.md")
CVW_REVIEW = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/PG77576_IGNATIUS_VIRGIN_MARY_CVW_VISUAL_REVIEW_20260930.md")


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
    return _write(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _copy(source: Path, target: Path) -> None:
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(source), _io_path(target))


def _oracle():
    path = ROOT / WORK / "integration/pg77576-html-v1/oracle.py"
    spec = importlib.util.spec_from_file_location("pg77576_virgin_mary_oracle", path)
    if spec is None or spec.loader is None:
        raise PipelineError("work-local oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._oracle


def _pinned_inputs(root: Path) -> tuple[SourceManifest, CandidatePackage, object]:
    for relative, expected in ((MANIFEST, MANIFEST_SHA), (PACKAGE / "manifest.json", PACKAGE_SHA),
                               (VALIDATION, VALIDATION_SHA), (TECHNICAL, TECHNICAL_SHA)):
        if _sha(root / relative) != expected:
            raise PipelineError(f"reviewed input changed: {relative}")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    for item in manifest.record["authorities"]:
        path = resolve_repo_path(root, item["path"]) if item["path"].startswith("raw/") else root / item["path"]
        if _io_path(path).stat().st_size != item["bytes"] or _sha(path) != item["sha256"]:
            raise PipelineError(f"source-manifest authority changed: {item['name']}")
    package = CandidatePackage.load(root / PACKAGE)
    if package.sha256 != PACKAGE_SHA:
        raise PipelineError("candidate package changed")
    report = validate(manifest, package, _oracle())
    saved = _read(root / VALIDATION)
    if report.status != "pass" or report.sha256 != saved["report_sha256"] or saved["status"] != "pass":
        raise PipelineError(f"fresh source oracle differs: {report.findings[:3]}")
    if _sha(resolve_repo_path(root, SOURCE.as_posix())) != SOURCE_SHA:
        raise PipelineError("retained HTML changed")
    return manifest, package, report


def _projection(root: Path) -> dict:
    acceptance = root / EDITION / "acceptance.json"
    projected = project_accepted_document(root, acceptance_path=acceptance, category="prose")
    errors = verify_accepted_document(root, acceptance_path=acceptance, rows=projected["rows"],
                                      receipt=projected["receipt"], category="prose")
    if errors or not projected["rows"]:
        raise PipelineError(f"actual-master prose correspondence failed: {errors[:3]}")
    return projected


def stage(stage_root: Path) -> dict:
    root = ROOT.resolve(strict=True)
    stage_root = stage_root.absolute()
    if (stage_root.exists() or stage_root.parent != (root / ".tmp_audit").resolve(strict=True)
            or not stage_root.name.startswith(WORK_ID + "-accept-")):
        raise PipelineError("fresh work-named stage under .tmp_audit required")
    manifest, package, report = _pinned_inputs(root)
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    if (acquisition["source_path"] != SOURCE.as_posix() or acquisition["source_sha256"] != SOURCE_SHA
            or len(acquisition["retained_files"]) != 3):
        raise PipelineError("acquisition boundary changed")
    work = _read(root / WORK / "work.json")
    old_work = json.loads(json.dumps(work))
    edition = work["textual_forms"][0]["editions"][0]
    if (work["work_id"] != WORK_ID or work["textual_forms"][0]["textual_form_id"] != FORM_ID
            or edition["edition_id"] != EDITION_ID or edition["acquisition_ids"] != [ACQUISITION_ID]
            or "category" in edition or (root / EDITION / "master.tei.xml").exists()
            or (root / EDITION / "acceptance.json").exists()):
        raise PipelineError("work identity or acceptance preimage changed")
    before = _files(root / WORK)
    stage_root.mkdir()
    for relative in before:
        _copy(root / WORK / relative, stage_root / WORK / relative)
    for item in manifest.record["authorities"]:
        relative = Path(item["path"])
        source = resolve_repo_path(root, item["path"]) if item["path"].startswith("raw/") else root / relative
        _copy(source, stage_root / relative)
    for target in _read(root / WORK / "state.json")["targets"]:
        for name in target.get("evidence", []):
            relative = Path(name)
            if not name.startswith("raw/") and not (stage_root / relative).exists():
                _copy(root / relative, stage_root / relative)
    for relative in (REVIEW, CVW_REVIEW):
        _copy(root / relative, stage_root / relative)
    edition["category"] = "prose"
    validate_identity_update(old_work, work)
    _json(stage_root / WORK / "work.json", work)
    load_work(stage_root / WORK / "work.json")
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                    acquisition_id=ACQUISITION_ID)
    revision = dict(id="pg77576-ignatius-virgin-mary-accepted-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the source-bounded appendix epistle from retained Project Gutenberg HTML.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=acquisition["source_bytes"], source_scope=acquisition["source_scope"])
    original = package.member_bytes("content.tei.xml")
    # The reviewed excerpt has a prose-only sourceDesc. The integration binder
    # appends a bibl, so convert that existing source prose to a bibl first.
    header, body = original.split(b"</teiHeader>", 1)
    if header.count(b"<sourceDesc><p>") != 1 or header.count(b"</p></sourceDesc>") != 1:
        raise PipelineError("reviewed source description shape changed")
    header = header.replace(b"<sourceDesc><p>", b"<sourceDesc><bibl>", 1)
    header = header.replace(b"</p></sourceDesc>", b"</bibl></sourceDesc>", 1)
    header_ready = header + b"</teiHeader>" + body
    bound = bind_reviewed_header(header_ready, expected_sha256=sha256(header_ready).hexdigest(), identity=identity,
                                 source=source_binding, source_url=acquisition["url"],
                                 declared_scope=acquisition["source_scope"], revision=revision)
    if original.split(b"</teiHeader>", 1)[1] != bound.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("acceptance changed reviewed TEI content")
    candidate = _write(stage_root / EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(candidate):
        raise PipelineError(f"accepted TEI P5 errors: {errors[:3]}")
    retained = acquisition["retained_files"]
    expected = [dict(path=item["path"], position=index) for index, item in enumerate(retained, 1)]
    included = [dict(path=item["path"], position=index, bytes=item["bytes"], sha256=item["sha256"],
                     scope=acquisition["source_scope"])
                for index, item in enumerate(retained, 1) if item["path"] == SOURCE.as_posix()]
    excluded = [dict(path=item["path"], position=index,
                     reason="Acquisition container or cover support; outside this one-work text selection.")
                for index, item in enumerate(retained, 1) if item["path"] != SOURCE.as_posix()]
    scope = dict(kind="selection", declared=acquisition["source_scope"], expected_members=expected,
                 included_members=included, excluded_members=excluded)
    common = dict(identity=identity, source=source_binding, candidate=make_file_binding(stage_root, candidate),
                  scope=acquisition["source_scope"], accepted_scope=dict(kind="selection", declared=acquisition["source_scope"]),
                  expected_members=expected, included_members=included, excluded_members=excluded,
                  missing_members=[], unknown_members=[])
    account = _json(stage_root / EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=acquisition["source_bytes"],
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
        oracle_report_sha256=report.sha256, original_candidate_sha256=sha256(original).hexdigest(),
        selected_body_interval=[1394, 1397], represented_body_children=3, represented_note_ids=["f2025"],
        neighboring_work_boundaries="children 1393 and 1397 are separate titled epistles",
        body_unchanged=True))
    command = "py -3 -m build.tools.accept_pg77576_ignatius_virgin_mary stage"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle share the declared [1394,1397) interval and retained HTML hash."],
                     independent_corroboration="Independent review checked adjacent titles, appendix context, source text, note, and package hashes; CVW spot check reached page 493 and both visible boundaries.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _json(stage_root / EVIDENCE / f"{name}.json", common | dict(
            claim=name, status="pass", command=command, exit_code=0,
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
            oracle_report_sha256=report.sha256, technical_evidence_sha256=TECHNICAL_SHA,
            independent_review_sha256=_sha(root / REVIEW), cvw_review_sha256=_sha(root / CVW_REVIEW),
            original_candidate_body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = dict(reviewer="agent:pg77576-ignatius-virgin-mary-technical-acceptance", reviewed_at=now,
                  coverage=dict(status="partial", declared=acquisition["source_scope"],
                                reached=["page 493", "title, salutation, complete letter", "note f2025",
                                         "preceding and following work boundaries",
                                         "independent source/TEI text and structure",
                                         "agent CVW visible page 493 and boundaries"],
                                inspected=["independent source/TEI text and structure", "agent CVW visible page 493 and boundaries"],
                                unreviewed=["source footnote at distant end-of-volume visual location", "print collation", "human verification"]),
                  source_quality_uncertainty=["The electronic witness was not collated to print."],
                  discrepancies=[], unreviewed_residuals=["CVW linked=false; governed correspondence not yet supplied.",
                                                        "Human verification and rights clearance remain open."])
    review_path = _json(stage_root / EVIDENCE / "review.json", common | review | dict(
        independent_review_path=REVIEW.as_posix(), independent_review_sha256=_sha(root / REVIEW),
        cvw_review_path=CVW_REVIEW.as_posix(), cvw_review_sha256=_sha(root / CVW_REVIEW), cvw_linked=False))
    decision = dict(source_local_disposition="Accept only the source-titled Virgin Mary epistle at HTML children [1394,1397) with linked note f2025.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                        supported_scope=acquisition["source_scope"], unresolved_claims=[],
                        unassessed_stronger_claims=["human verification", "print collation", "rights clearance", "publication"]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage_root, identity=identity, candidate_path=candidate,
        source_accounting_path=account, scope=scope, technical=technical,
        review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
    acceptance = stage_root / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage_root)
    master = _write(stage_root / EDITION / "master.tei.xml", bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage_root, master))
    write_acceptance(acceptance, record)
    state = _read(stage_root / WORK / "state.json")
    editions = [item for item in state["targets"] if item["target_type"] == "edition" and item["target_id"] == EDITION_ID]
    if len(editions) != 1 or editions[0]["stage"] != "review":
        raise PipelineError("one edition review target required")
    editions[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    editions[0]["evidence"].extend([(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()])
    _json(stage_root / WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage_root)
    validate_state(stage_root / WORK / "state.json", root=stage_root)
    projected = _projection(stage_root)
    result = dict(contract="ocd-pg77576-virgin-mary-stage-v1", status="staged-only", work_id=WORK_ID,
                  stage_root=stage_root.as_posix(), before=before, after=_files(stage_root / WORK),
                  source_sha256=SOURCE_SHA, source_manifest_sha256=MANIFEST_SHA,
                  candidate_package_sha256=PACKAGE_SHA, validation_sha256=VALIDATION_SHA,
                  technical_evidence_sha256=TECHNICAL_SHA, master_sha256=_sha(master),
                  acceptance_sha256=_sha(acceptance), projection_category="prose",
                  projection_rows=len(projected["rows"]), independent_verifier_errors=[],
                  cvw_linked=False, human_review="not-recorded", rights="not-cleared", installation="not-performed")
    _json(stage_root / "stage-receipt.json", result)
    return result


def preflight(stage_root: Path, receipt_sha: str) -> dict:
    root = ROOT.resolve(strict=True)
    stage_root = stage_root.resolve(strict=True)
    if (stage_root.parent != (root / ".tmp_audit").resolve(strict=True)
            or not stage_root.name.startswith(WORK_ID + "-accept-") or root == stage_root
            or len(receipt_sha) != 64 or any(ch not in "0123456789abcdef" for ch in receipt_sha)
            or _sha(stage_root / "stage-receipt.json") != receipt_sha):
        raise PipelineError("work-local stage or receipt pin differs")
    receipt = _read(stage_root / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-pg77576-virgin-mary-stage-v1" or receipt.get("status") != "staged-only"
            or receipt.get("work_id") != WORK_ID or receipt.get("stage_root") != stage_root.as_posix()
            or receipt.get("installation") != "not-performed" or receipt.get("cvw_linked") is not False
            or receipt.get("human_review") != "not-recorded" or receipt.get("rights") != "not-cleared"):
        raise PipelineError("stage receipt claim differs")
    before, after = _files(root / WORK), _files(stage_root / WORK)
    if before != receipt["before"] or after != receipt["after"]:
        raise PipelineError("complete work preimage or staged generation differs")
    if (root / EDITION / "master.tei.xml").exists() or (root / EDITION / "acceptance.json").exists():
        raise PipelineError("edition already has an accepted master")
    for relative in before:
        if relative not in {"state.json", "work.json"} and after.get(relative) != before[relative]:
            raise PipelineError(f"stage changes existing work file: {relative}")
    additions = set(after) - set(before)
    permitted = {(EDITION / name).relative_to(WORK).as_posix() for name in ("master.tei.xml", "acceptance.json")}
    evidence_prefix = EVIDENCE.relative_to(WORK).as_posix() + "/"
    if any(path not in permitted and not path.startswith(evidence_prefix) for path in additions):
        raise PipelineError("stage adds a file outside the scoped acceptance evidence")
    current_work = _read(root / WORK / "work.json")
    expected_work = json.loads(json.dumps(current_work))
    if expected_work["textual_forms"][0]["editions"][0].get("category") is not None:
        raise PipelineError("category preimage differs")
    expected_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    if _read(stage_root / WORK / "work.json") != expected_work:
        raise PipelineError("metadata change exceeds one category field")
    manifest, package, report = _pinned_inputs(root)
    if report.sha256 != _read(root / VALIDATION)["report_sha256"]:
        raise PipelineError("source oracle report changed")
    dependencies = {MANIFEST, REVIEW, CVW_REVIEW, VALIDATION, TECHNICAL, ACQUISITION}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    for relative in dependencies:
        if relative in {WORK / "work.json", WORK / "state.json"}:
            continue  # Both are intentionally changed only in the staged generation.
        source = resolve_repo_path(root, relative.as_posix()) if relative.as_posix().startswith("raw/") else root / relative
        if _sha(source) != _sha(stage_root / relative):
            raise PipelineError(f"stage source dependency differs: {relative}")
    if package.sha256 != receipt["candidate_package_sha256"]:
        raise PipelineError("current candidate differs")
    original = (root / PACKAGE / "content.tei.xml").read_bytes()
    master = (stage_root / EDITION / "master.tei.xml").read_bytes()
    if (original.split(b"</teiHeader>", 1)[1] != master.split(b"</teiHeader>", 1)[1]
            or _sha(stage_root / EDITION / "master.tei.xml") != receipt["master_sha256"]
            or _sha(stage_root / EDITION / "acceptance.json") != receipt["acceptance_sha256"]):
        raise PipelineError("staged accepted master changed reviewed body")
    accepted = validate_acceptance(stage_root / EDITION / "acceptance.json", root=stage_root)
    validate_state(stage_root / WORK / "state.json", root=stage_root)
    if accepted["promotion"]["status"] != "promoted" or accepted["identity"]["work_id"] != WORK_ID:
        raise PipelineError("staged acceptance authority differs")
    projected = _projection(stage_root)
    if len(projected["rows"]) != receipt["projection_rows"]:
        raise PipelineError("staged actual-master row count differs")
    return dict(status="ready-to-install", work_id=WORK_ID, before_files=len(before), after_files=len(after),
                master_sha256=receipt["master_sha256"], acceptance_sha256=receipt["acceptance_sha256"],
                projection_rows=len(projected["rows"]), receipt_sha256=receipt_sha)


def install(stage_root: Path, receipt_sha: str) -> dict:
    root = ROOT.resolve(strict=True)
    stage_root = stage_root.resolve(strict=True)
    target, source = root / WORK, stage_root / WORK
    with ExitStack() as locks:
        for path in sorted((target, source), key=lambda item: item.as_posix()):
            locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        preflight(stage_root, receipt_sha)
        receipt = _read(stage_root / "stage-receipt.json")

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != receipt["after"]:
                    raise PipelineError("installed work generation differs")
                validate_acceptance(root / EDITION / "acceptance.json", root=root)
                validate_state(root / WORK / "state.json", root=root)
                if len(_projection(root)["rows"]) != receipt["projection_rows"]:
                    raise PipelineError("installed actual-master projection differs")

        return _commit_generation(root, target, source, work_id=WORK_ID,
                                  before=receipt["before"], after=receipt["after"], existed=True,
                                  replacement=False, operation_kind="pg77576-virgin-mary-work-install",
                                  result_status="installed-and-validated", accepted_editions=1,
                                  fail_at=checkpoint)


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
        result = preflight(args.stage_root, args.expected_sha256)
        result["installation"] = install(args.stage_root, args.expected_sha256)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
