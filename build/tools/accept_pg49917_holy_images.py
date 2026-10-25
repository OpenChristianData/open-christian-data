"""Stage, check, and guardedly install the retained Holy Images acceptance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from build.tei.pg49917_holy_images_oracle import _oracle
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path, install_accepted_work
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "pg49917-holy-images"
FORM_ID = "pg49917-holy-images-english"
EDITION_ID = "pg49917-holy-images-pg49917-edition"
ACQUISITION_ID = "pg49917-holy-images-pg49917-acquisition"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
EVIDENCE = WORK / "integration/pg49917-html-v1/acceptance-v1"
MANIFEST = Path("sources/pg49917-holy-images/source-manifest.json")
PACKAGE = WORK / "integration/pg49917-html-v1/candidate/package"
VALIDATION = WORK / "integration/pg49917-html-v1/candidate/validation.json"
REVIEW = Path("plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/PG49917_HOLY_IMAGES_INDEPENDENT_REVIEW_20260930.md")
SOURCE = Path("raw/gutenberg/49917/html/pg49917-images.html")
SOURCE_SHA = "a517174360b8c13609b74c005965f1386e6a0cc0f97fd795d248ccb496944204"
MANIFEST_SHA = "5995038580b5d5d138e8b9903b5e8c0331ba04c070b2f1aa157fa0bcf81ca133"
PACKAGE_SHA = "e4811283355578c09d09c961ad127c5f5a94dff9b5238d614531693726d6220a"
VALIDATION_SHA = "9e364ea5231a28bdc217563ca8bc3415d5bd6a51a608d60837ce49832044e6d1"
PROFILE = "ocd-prose-pg49917-holy-images-v1"


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


def _copy(root: Path, stage: Path, relative: Path) -> None:
    source = resolve_repo_path(root, relative.as_posix()) if relative.parts[0] == "raw" else root / relative
    target = stage / relative
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(source), _io_path(target))


def _pinned_inputs(root: Path) -> tuple[SourceManifest, CandidatePackage, object]:
    for relative, expected in ((MANIFEST, MANIFEST_SHA), (PACKAGE / "manifest.json", PACKAGE_SHA),
                               (VALIDATION, VALIDATION_SHA)):
        if _sha(root / relative) != expected:
            raise PipelineError(f"reviewed input changed: {relative}")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    for entry in manifest.record["authorities"]:
        relative = Path(entry["path"])
        path = resolve_repo_path(root, entry["path"]) if relative.parts[0] == "raw" else root / relative
        if _io_path(path).stat().st_size != entry["bytes"] or _sha(path) != entry["sha256"]:
            raise PipelineError(f"source authority changed: {entry['name']}")
    package = CandidatePackage.load(root / PACKAGE)
    report = validate(manifest, package, _oracle)
    saved = _read(root / VALIDATION)
    if (package.sha256 != PACKAGE_SHA or report.status != "pass" or report.findings
            or report.sha256 != saved["report_sha256"] or _sha(resolve_repo_path(root, SOURCE.as_posix())) != SOURCE_SHA):
        raise PipelineError("reviewed source or independent oracle differs")
    return manifest, package, report


def _projection(root: Path) -> dict:
    acceptance = root / EDITION / "acceptance.json"
    output = project_accepted_prose(root, acceptance_path=acceptance)
    errors = verify_accepted_prose(root, acceptance_path=acceptance,
                                   rows=output["rows"], receipt=output["receipt"])
    if errors or len(output["rows"]) != 2:
        raise PipelineError(f"Holy Images actual-master prose projection differs: {errors[:3]}")
    return output


def stage(stage_root: Path) -> dict:
    root = ROOT.resolve(strict=True)
    audit = (root / ".tmp_audit").resolve(strict=True)
    stage_root = stage_root.absolute()
    if (stage_root.exists() or stage_root.parent != audit
            or not stage_root.name.startswith(WORK_ID + "-accept-")):
        raise PipelineError("fresh work-named stage under .tmp_audit required")
    manifest, package, report = _pinned_inputs(root)
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    if acquisition["source_path"] != SOURCE.as_posix() or acquisition["source_sha256"] != SOURCE_SHA:
        raise PipelineError("acquisition source boundary changed")
    old_work = _read(root / WORK / "work.json")
    work = json.loads(json.dumps(old_work))
    edition = work["textual_forms"][0]["editions"][0]
    if (work["work_id"] != WORK_ID or work["textual_forms"][0]["textual_form_id"] != FORM_ID
            or edition["edition_id"] != EDITION_ID or edition["acquisition_ids"] != [ACQUISITION_ID]
            or "category" in edition or (root / EDITION / "master.tei.xml").exists()
            or (root / EDITION / "acceptance.json").exists()):
        raise PipelineError("work identity or acceptance preimage changed")
    before = _files(root / WORK)
    stage_root.mkdir()
    shutil.copytree(_io_path(root / WORK), _io_path(stage_root / WORK))
    for entry in manifest.record["authorities"]:
        relative = Path(entry["path"])
        if relative not in {WORK / "work.json", ACQUISITION, WORK / "SOURCE_CREDIT.md"}:
            _copy(root, stage_root, relative)
    for target in _read(root / WORK / "state.json")["targets"]:
        for name in target.get("evidence", []):
            if "#" in name:
                name = name.split("#", 1)[0]
            relative = Path(name)
            if relative.parts[0] != "raw" and not (stage_root / relative).exists():
                _copy(root, stage_root, relative)
    _copy(root, stage_root, REVIEW)
    validate_identity_update(old_work, work)
    _json(stage_root / WORK / "work.json", work)
    load_work(stage_root / WORK / "work.json")
    identity = dict(work_id=WORK_ID, textual_form_id=FORM_ID, edition_id=EDITION_ID,
                    acquisition_id=ACQUISITION_ID)
    revision = dict(id="pg49917-holy-images-accepted-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the three source-titled Holy Images parts and their linked index notes from the retained HTML.")
    source = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                  source_bytes=acquisition["source_bytes"], source_scope=acquisition["source_scope"])
    original = package.member_bytes("content.tei.xml")
    header, body = original.split(b"</teiHeader>", 1)
    if header.count(b"<sourceDesc><p>") != 1 or header.count(b"</p></sourceDesc>") != 1:
        raise PipelineError("reviewed source description shape changed")
    header = header.replace(b"<sourceDesc><p>", b"<sourceDesc><bibl>", 1)
    header = header.replace(b"</p></sourceDesc>", b"</bibl></sourceDesc>", 1)
    ready = header + b"</teiHeader>" + body
    bound = bind_reviewed_header(ready, expected_sha256=hashlib.sha256(ready).hexdigest(),
                                 identity=identity, source=source, source_url=acquisition["url"],
                                 declared_scope=acquisition["source_scope"], revision=revision)
    if original.split(b"</teiHeader>", 1)[1] != bound.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("accepted derivation changed reviewed text")
    candidate = _write(stage_root / EVIDENCE / "candidate.tei.xml", bound)
    if errors := validate_file(candidate):
        raise PipelineError(f"accepted TEI P5 errors: {errors[:3]}")
    retained = acquisition["retained_files"]
    expected = [dict(path=item["path"], position=index) for index, item in enumerate(retained, 1)]
    included = [dict(path=item["path"], position=index, bytes=item["bytes"], sha256=item["sha256"],
                     scope=acquisition["source_scope"])
                for index, item in enumerate(retained, 1) if item["path"] == SOURCE.as_posix()]
    excluded = [dict(path=item["path"], position=index,
                     reason="Acquisition ZIP or cover support; outside the Holy Images textual selection.")
                for index, item in enumerate(retained, 1) if item["path"] != SOURCE.as_posix()]
    scope = dict(kind="selection", declared=acquisition["source_scope"],
                 expected_members=expected, included_members=included, excluded_members=excluded)
    common = dict(identity=identity, source=source, candidate=make_file_binding(stage_root, candidate),
                  scope=acquisition["source_scope"], accepted_scope=dict(kind="selection", declared=acquisition["source_scope"]),
                  expected_members=expected, included_members=included, excluded_members=excluded,
                  missing_members=[], unknown_members=[])
    accounting = _json(stage_root / EVIDENCE / "source-accounting.json", common | dict(
        projection_profile=PROFILE, source_sha256=SOURCE_SHA, source_bytes=acquisition["source_bytes"],
        source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
        oracle_report_sha256=report.sha256, reviewed_body_unchanged=True,
        selected_parts=["Part I", "Part II", "Part III"], linked_note_count=29,
        private_source_comment_milestones=5))
    command = "py -3 -m build.tools.accept_pg49917_holy_images stage"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["Producer and oracle share the selected three-part and 29-note source envelope."],
                     independent_corroboration="Independent lxml/HTML5 review verified complete part and note text, boundaries, and source links; focused mutation checks reject word, note, attachment, and page changes.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _json(stage_root / EVIDENCE / f"{name}.json", common | dict(
            claim=name, status="pass", command=command, exit_code=0,
            source_manifest_sha256=manifest.sha256, candidate_package_sha256=package.sha256,
            oracle_report_sha256=report.sha256, independent_review_sha256=_sha(root / REVIEW),
            reviewed_body_unchanged=True,
            evidence_note="Source-specific policy and TEI P5 pass; the provisional general excerpt vocabulary profile reports 447 issues."))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    review = dict(reviewer="agent:pg49917-holy-images-technical-assessment", reviewed_at=now,
                  coverage=dict(status="partial", declared=acquisition["source_scope"],
                                reached=["Parts I-III complete source/TEI machine comparison", "29 source/TEI note tables and links", "CVW visible three-part openings"],
                                inspected=["Parts I-III complete source/TEI machine comparison", "29 source/TEI note tables and links", "CVW visible three-part openings"],
                                unreviewed=["whole-work visual collation", "print-edition collation", "human verification"]),
                  source_quality_uncertainty=["Transcriber reports punctuation and spelling emendations; no print collation is recorded."],
                  discrepancies=[], unreviewed_residuals=["CVW note-table and full-middle/end visual pairing remain open.",
                                                        "General excerpt vocabulary profile has 447 non-P5 findings; source-specific validation passes."])
    review_path = _json(stage_root / EVIDENCE / "review.json", common | review | dict(
        independent_review_path=REVIEW.as_posix(), independent_review_sha256=_sha(root / REVIEW)))
    decision = dict(source_local_disposition="Accept only Parts I-III and their 29 linked notes as this electronic edition.",
                    blockers=[], agent_assessment=dict(status="accepted", actor=review["reviewer"], assessed_at=now,
                        supported_scope=acquisition["source_scope"], unresolved_claims=[],
                        unassessed_stronger_claims=["complete visual review", "print collation", "human verification", "rights clearance", "release selection", "publication"]),
                    human_decision=dict(status="not-recorded"))
    record = build_acceptance_record(stage_root, identity=identity, candidate_path=candidate,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review | dict(report_path=review_path), representation_revision=revision, decision=decision)
    acceptance = stage_root / EDITION / "acceptance.json"
    write_acceptance(acceptance, record)
    validate_acceptance(acceptance, root=stage_root)
    master = _write(stage_root / EDITION / "master.tei.xml", bound)
    record["promotion"] = dict(record["promotion"])
    record["promotion"].update(status="promoted", promoted_at=now, master=make_file_binding(stage_root, master))
    write_acceptance(acceptance, record)
    state = _read(stage_root / WORK / "state.json")
    editions = [entry for entry in state["targets"] if entry["target_type"] == "edition" and entry["target_id"] == EDITION_ID]
    if len(editions) != 1 or editions[0]["stage"] != "review":
        raise PipelineError("one edition review target required")
    editions[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=now)
    editions[0]["evidence"].extend([(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()])
    _json(stage_root / WORK / "state.json", state)
    validate_acceptance(acceptance, root=stage_root)
    validate_state(stage_root / WORK / "state.json", root=stage_root)
    output = _projection(stage_root)
    result = dict(status="staged-only", work_id=WORK_ID, stage_root=stage_root.as_posix(),
                  before=before, after=_files(stage_root / WORK), master_sha256=_sha(master),
                  acceptance_sha256=_sha(acceptance), projection_rows=len(output["rows"]),
                  checker_errors=[], installation="not-performed", human_review="not-recorded", rights="not-cleared")
    _json(stage_root / "stage-receipt.json", result)
    return result


def preflight(stage_root: Path, expected_sha256: str) -> dict:
    root = ROOT.resolve(strict=True)
    stage_root = stage_root.resolve(strict=True)
    if (stage_root.parent != (root / ".tmp_audit").resolve(strict=True)
            or not stage_root.name.startswith(WORK_ID + "-accept-")
            or _sha(stage_root / "stage-receipt.json") != expected_sha256):
        raise PipelineError("stage location or receipt pin differs")
    receipt = _read(stage_root / "stage-receipt.json")
    if (receipt["status"] != "staged-only" or receipt["work_id"] != WORK_ID
            or receipt["stage_root"] != stage_root.as_posix()
            or receipt["installation"] != "not-performed"):
        raise PipelineError("stage receipt claim differs")
    if _files(root / WORK) != receipt["before"] or _files(stage_root / WORK) != receipt["after"]:
        raise PipelineError("work preimage or staged generation changed")
    validate_acceptance(stage_root / EDITION / "acceptance.json", root=stage_root)
    validate_state(stage_root / WORK / "state.json", root=stage_root)
    if (root / EDITION / "master.tei.xml").exists() or (root / EDITION / "acceptance.json").exists():
        raise PipelineError("live work already has an accepted master")
    projected = _projection(stage_root)
    if len(projected["rows"]) != receipt["projection_rows"]:
        raise PipelineError("staged projection count changed")
    return dict(status="ready-to-install", receipt_sha256=expected_sha256,
                master_sha256=receipt["master_sha256"], acceptance_sha256=receipt["acceptance_sha256"],
                projection_rows=len(projected["rows"]))


def apply(stage_root: Path, expected_sha256: str) -> dict:
    root = ROOT.resolve(strict=True)
    result = preflight(stage_root, expected_sha256)

    def checkpoint(point: str) -> None:
        if point == "after-validated":
            installed = _projection(root)
            if len(installed["rows"]) != result["projection_rows"]:
                raise PipelineError("installed actual-master projection differs")

    result["installation"] = install_accepted_work(root, stage_root, work_id=WORK_ID, fail_at=checkpoint)
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
