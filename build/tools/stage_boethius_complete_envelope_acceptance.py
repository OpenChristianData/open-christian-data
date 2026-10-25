"""Stage an exact Boethius electronic-witness acceptance outside the library."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file

from build.tei.boethius_complete_envelope_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "boethius-theological-tractates"
FORM_ID = WORK_ID + "-english"
EDITION_ID = WORK_ID + "-retained-electronic-witness"
ACQUISITION_ID = WORK_ID + "-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/ccel/boethius/tracts.xml")
MANIFEST = Path("sources/structured-text/boethius-theological-tractates/complete-envelope-v4/source-manifest.json")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/boethius-complete-envelope-cvw-20260927-v5")
CVW_SESSION = Path("D:/Library/Open Christian Data/candidate-reviews/boethius-complete-envelope-cvw-session-20260927-v4/dc0ca7618204417a99b507a719f42e3d.receipt.json")
CVW_FRAMES = {
    "opening": Path("D:/Library/Open Christian Data/candidate-reviews/boethius-complete-envelope-cvw-opening-20260927-v4"),
    "tract": Path("D:/Library/Open Christian Data/candidate-reviews/boethius-complete-envelope-cvw-tract-20260927-v4"),
    "index": Path("D:/Library/Open Christian Data/candidate-reviews/boethius-complete-envelope-cvw-index-20260927-v4"),
}
EVIDENCE = WORK / "integration/boethius-complete-electronic-v1"
SOURCE_SHA = "406487abffb39f63934771ce3b4d23b69ce4488d6bc1ccc6a6cad5b4b1e01de8"
MANIFEST_SHA = "04bcf3352cd2c0ec418b4f024cbf6b4b7ae4a90c64119244a5f9262f3e957b51"
PACKAGE_SHA = "dd3c37d7ae6721ec2793271849ecb8013b104334d5026473cb1ee4dc526589d9"
VALIDATION_SHA = "f02bd85eb5cb547780d42454c44688e68f15b21e8e63d6402907f8c56e14d5c8"
TEI_SHA = "5ce8a7a581ca690c9961aef2bd8f84bf149ec7880b9a6352a3fffc3989f7f417"
CONTRACT = "ocd-boethius-complete-electronic-stage-v1"
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Boethius staged input changed: {path}")
    return content


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    path = stage / relative
    _io_path(path).parent.mkdir(parents=True, exist_ok=True)
    _io_path(path).write_bytes(content)
    return path


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, (json.dumps(value, sort_keys=True, ensure_ascii=False,
                                              separators=(",", ":")) + "\n").encode("utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or ROOT.resolve() in stage.resolve().parents
            or stage.resolve() in ROOT.resolve().parents):
        raise ValueError("Boethius stage must be a fresh external directory")
    raw = _read(ROOT / SOURCE, SOURCE_SHA)
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(CANDIDATE / "package")
    validation = _json(CANDIDATE / "validation.json")
    report = validate(manifest, package, _oracle)
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA
            or _sha(CANDIDATE / "validation.json") != VALIDATION_SHA
            or _sha(CANDIDATE / "package/content.tei.xml") != TEI_SHA
            or validation.get("report_sha256") != report.sha256
            or validation.get("status") != "pass"
            or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("source_manifest_sha256") != MANIFEST_SHA):
        raise ValueError("Boethius source, candidate, or validation pin differs")
    old_work = _json(ROOT / WORK / "work.json")
    old_state = _json(ROOT / WORK / "state.json")
    acquisition = _json(ROOT / ACQUISITION)
    retained = acquisition.get("retained_files", [])
    if (old_work.get("work_id") != WORK_ID or len(retained) != 1
            or retained[0].get("path") != SOURCE.as_posix()
            or retained[0].get("bytes") != len(raw)
            or retained[0].get("sha256") != SOURCE_SHA):
        raise ValueError("Boethius canonical work or retained-source preimage differs")
    edition_targets = [item for item in old_state["targets"]
                       if item["target_type"] == "edition" and item["target_id"] == EDITION_ID]
    if len(edition_targets) != 1 or edition_targets[0]["stage"] != "acquired":
        raise ValueError("Boethius edition is not uniquely acquired")
    if _io_path(ROOT / EDITION / "acceptance.json").exists() or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("Boethius work is already accepted")
    before = _files(ROOT / WORK)
    if len(before) != 3:
        raise ValueError("Boethius canonical preimage is not the three-file acquired work")
    for relative in before:
        _put(stage, WORK / relative, _read(ROOT / WORK / relative))
    dependencies = {SOURCE, MANIFEST, Path("docs/sources/ccel-permission.md")}
    dependencies.update(Path(authority["path"]) for authority in manifest.record["authorities"])
    for reference in set(old_work.get("evidence", [])) | {
        item for target in old_state["targets"] for item in target.get("evidence", [])
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited Boethius evidence path: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            _put(stage, relative, _read(ROOT / relative))
    for name in package.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _put(stage, EVIDENCE / "inputs/validation.json", _read(CANDIDATE / "validation.json", VALIDATION_SHA))
    session = _json(CVW_SESSION)
    if (session.get("session", {}).get("session_id") != "dc0ca7618204417a99b507a719f42e3d"
            or PACKAGE_SHA not in session.get("session", {}).get("candidate_sha256", [])):
        raise ValueError("Boethius final CVW session identity differs")
    _put(stage, EVIDENCE / "visual/session-receipt.json", _read(CVW_SESSION))
    for name, directory in CVW_FRAMES.items():
        capture = _json(directory / "capture.json")
        if (PACKAGE_SHA not in capture.get("session", {}).get("candidate_sha256", [])
                or capture.get("session", {}).get("session_id") != "dc0ca7618204417a99b507a719f42e3d"
                or capture.get("page_errors") or capture.get("visual_inspection") != "unknown"):
            raise ValueError(f"Boethius {name} CVW frame binding differs")
        for member in ("capture.json", "frame.png", "compare.json", "session.json"):
            _put(stage, EVIDENCE / "visual" / name / member, _read(directory / member))
    work = _json(stage / WORK / "work.json")
    edition = work["textual_forms"][0]["editions"][0]
    if edition.get("category") is not None or edition.get("language") != "en":
        raise ValueError("Boethius prose category or language preimage differs")
    edition["category"] = "prose"
    validate_identity_update(old_work, work)
    _put_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    original = package.member_bytes("content.tei.xml")
    revision = dict(id="boethius-complete-ccel-electronic-v1",
                    date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept all five source divisions of the retained CCEL electronic witness of The Theological Tractates.")
    binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                   source_bytes=len(raw), source_scope=retained[0]["scope"])
    declared = binding["source_scope"]
    derived = bind_reviewed_header(original, expected_sha256=TEI_SHA,
                                   identity=IDENTITY, source=binding,
                                   source_url=acquisition["url"], declared_scope=declared,
                                   revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Boethius accepted header changed the source-derived text")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Boethius accepted TEI P5 validation failed: {errors[:3]}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(raw),
                     sha256=SOURCE_SHA, scope=declared)]
    scope = dict(kind="edition", declared=declared, expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=binding, candidate=make_file_binding(stage, candidate),
                  scope=declared, accepted_scope=dict(kind="edition", declared=declared),
                  expected_members=expected, included_members=included, excluded_members=[],
                  missing_members=[], unknown_members=[])
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=len(raw), source_manifest_sha256=MANIFEST_SHA,
        candidate_package_sha256=PACKAGE_SHA,
        source_feature_counts=dict(elements=1119, comments=10, local_links=136),
        source_roots=["i", "ii", "iii", "iv", "v"], unsupported_elements=0,
        basis="Independent current-source oracle compared all retained body features and the complete five-root envelope."))
    command = "py -3 -m build.tools.stage_boethius_complete_envelope_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["The producer and oracle read the same retained ThML member and use the repository XML parser."],
                     independent_corroboration="Current-source independent oracle, TEI P5 validation, and exact-pair CVW sampled comparison.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            candidate_package_sha256=PACKAGE_SHA, source_manifest_sha256=MANIFEST_SHA,
            validation_sha256=VALIDATION_SHA, accepted_header_body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    reviewed_at = _now()
    review = dict(reviewer="agent:boethius-complete-electronic-stage", reviewed_at=reviewed_at,
                  coverage=dict(status="partial", declared=declared,
                                reached=[f"{SOURCE.as_posix()}#{root}" for root in ("i", "ii", "iii", "iv", "v")],
                                inspected=[f"{SOURCE.as_posix()}#{root}" for root in ("i", "iv", "v")],
                                unreviewed=[f"{SOURCE.as_posix()}#whole-work-visual-proofreading"]),
                  source_quality_uncertainty=["No print collation or complete proofreading of the CCEL transcription was performed."],
                  discrepancies=[], unreviewed_residuals=["CVW comparison covers named title, first tract, and index loci only."])
    review_file = _put_json(stage, EVIDENCE / "review.json", common | review | dict(
        current_cvw_session="dc0ca7618204417a99b507a719f42e3d",
        current_cvw_frames={name: _sha(directory / "frame.png") for name, directory in CVW_FRAMES.items()}))
    decision = dict(source_local_disposition="Agent acceptance of the complete retained CCEL electronic witness only.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"],
                                          assessed_at=reviewed_at, supported_scope=declared,
                                          unresolved_claims=[], unassessed_stronger_claims=[
                                              "print edition identity", "full visual proofreading",
                                              "human review", "rights clearance", "publication"]))
    acceptance = build_acceptance_record(stage, identity=IDENTITY, candidate_path=candidate,
                                         source_accounting_path=accounting, scope=scope,
                                         technical=technical, review=review | dict(report_path=review_file),
                                         representation_revision=revision, decision=decision)
    acceptance_path = stage / EDITION / "acceptance.json"
    write_acceptance(_io_path(acceptance_path), acceptance)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    master_path = _put(stage, EDITION / "master.tei.xml", derived)
    _put(stage, EDITION / "README.source.md", package.member_bytes("README.source.md"))
    acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                   master=make_file_binding(stage, master_path))
    write_acceptance(_io_path(acceptance_path), acceptance)
    state = _json(stage / WORK / "state.json")
    target = next(item for item in state["targets"] if item["target_type"] == "edition" and item["target_id"] == EDITION_ID)
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    target["evidence"].extend([EDITION.joinpath("master.tei.xml").as_posix(),
                               EDITION.joinpath("acceptance.json").as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 5:
        raise ValueError(f"Boethius actual-master native projection failed: {errors[:3]} / {len(projected['rows'])} rows")
    receipt = dict(contract=CONTRACT, status="staged-only", canonical_root=ROOT.as_posix(),
                   stage_root=stage.as_posix(), work_id=WORK_ID, source_path=SOURCE.as_posix(),
                   source_sha256=SOURCE_SHA, source_manifest_sha256=MANIFEST_SHA,
                   candidate_package_sha256=PACKAGE_SHA, original_tei_sha256=TEI_SHA,
                   validation_sha256=VALIDATION_SHA, before=before, after=_files(stage / WORK),
                   accepted_master_sha256=_sha(master_path), acceptance_sha256=_sha(acceptance_path),
                   projection_rows=len(projected["rows"]), rights="not-assessed", installation="not-performed")
    _put_json(stage, Path("boethius-complete-stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"status": result["status"], "stage_root": result["stage_root"],
                      "master_sha256": result["accepted_master_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
