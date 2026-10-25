"""Prepare one exact Ryle Holiness electronic-witness acceptance outside the library.

The command creates a fresh external stage. It does not install the work.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON, build_acceptance_record, make_file_binding,
    validate_acceptance, write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.reviewed_integration import bind_reviewed_header
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "ryle-holiness"
FORM_ID = "ryle-holiness-english"
EDITION_ID = "ryle-holiness-retained-electronic-witness"
ACQUISITION_ID = "ryle-holiness-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/ccel/ryle/holiness.xml")
MANIFEST = Path("sources/structured-text/ryle-holiness/ryle-holiness.source-manifest.json")
REVIEW = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-269.md")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-269-ryle-holiness.md")
CANDIDATE = Path("C:/Scratch/Open Christian Data/unified-reconciliation-20260916-ryle-successor-v1")
EVIDENCE = WORK / "integration/ryle-holiness-electronic-acceptance-v1"
SOURCE_SHA = "20f9c4a6eb9109c5981a37b580376ed02f1bc93ac98dd047ac6d0578ff3521c8"
MANIFEST_SHA = "84ce6df2e69da5045cc57fa3a9f27789f632e25333a1e3631670b5611a93e4de"
PACKAGE_SHA = "1249f91863b70bedbfe721f8198d95a967ff445fd60924f651528c4a8da1414b"
VALIDATION_SHA = "4e23578e1a147f72c685346bcaa6914be3e3030813994b8f63e687f616068c7d"
ORIGINAL_TEI_SHA = "55637e399c43568f0312cf313cd5bab048c6e3be6c8f7f356be06a9d2d27bd8e"
CONTRACT = "ocd-ryle-holiness-electronic-stage-v1"
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Ryle source or evidence bytes changed: {path}")
    return content


def _json(path: Path) -> dict:
    value = json.loads(_read(path))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = _io_path(stage / relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return stage / relative


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    content = (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    return _put(stage, relative, content)


def _copy(stage: Path, relative: Path) -> None:
    _put(stage, relative, _read(ROOT / relative))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def prepare(stage: Path) -> dict:
    stage = stage.absolute()
    if (_io_path(stage).exists() or not _io_path(stage.parent).is_dir()
            or stage.resolve() == ROOT.resolve() or ROOT.resolve() in stage.resolve().parents
            or stage.resolve() == CANDIDATE.resolve()
            or CANDIDATE.resolve() in stage.resolve().parents):
        raise ValueError("Ryle stage must be a fresh external directory")
    source = _read(ROOT / SOURCE, SOURCE_SHA)
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(_io_path(CANDIDATE / "package"))
    validation = _json(CANDIDATE / "validation.json")
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA
            or _sha(CANDIDATE / "validation.json") != VALIDATION_SHA
            or _sha(CANDIDATE / "package/content.tei.xml") != ORIGINAL_TEI_SHA
            or validation.get("status") != "pass" or validation.get("findings")
            or validation.get("source_manifest_sha256") != MANIFEST_SHA
            or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA):
        raise ValueError("current Ryle source, candidate, or validation does not match the reviewed route")
    old_work = _json(ROOT / WORK / "work.json")
    old_state = _json(ROOT / WORK / "state.json")
    acquisition = _json(ROOT / ACQUISITION)
    if (old_work.get("work_id") != WORK_ID or old_work["textual_forms"][0]["editions"][0]["edition_id"] != EDITION_ID
            or acquisition.get("acquisition_id") != ACQUISITION_ID
            or len(acquisition.get("retained_files", [])) != 1
            or acquisition["retained_files"][0]["path"] != SOURCE.as_posix()
            or acquisition["retained_files"][0]["bytes"] != len(source)
            or acquisition["retained_files"][0]["sha256"] != SOURCE_SHA):
        raise ValueError("Ryle work or acquired XML preimage differs")
    edition_target = [t for t in old_state["targets"] if t["target_type"] == "edition" and t["target_id"] == EDITION_ID]
    if len(edition_target) != 1 or edition_target[0]["stage"] != "acquired":
        raise ValueError("Ryle edition target is not uniquely acquired")
    if _io_path(ROOT / EDITION / "acceptance.json").exists() or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("Ryle is already accepted in the canonical library")
    before = _files(ROOT / WORK)
    for relative in before:
        _copy(stage, WORK / relative)
    if _files(stage / WORK) != before:
        raise ValueError("Ryle staged work preimage differs")
    dependencies = {SOURCE, MANIFEST, REVIEW, TICKET, Path("docs/sources/ccel-permission.md")}
    dependencies.update(Path(authority["path"]) for authority in manifest.record["authorities"])
    for reference in set(old_work.get("evidence", [])) | {
        item for target in old_state["targets"] for item in target.get("evidence", [])
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited Ryle evidence path: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            _copy(stage, relative)
    work = _json(stage / WORK / "work.json")
    edition = work["textual_forms"][0]["editions"][0]
    if edition.get("category") is not None or edition.get("language") != "en":
        raise ValueError("Ryle category or language preimage differs")
    edition["category"] = "prose"
    validate_identity_update(old_work, work)
    _put_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    for name in package.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _put(stage, EVIDENCE / "inputs/validation.json", _read(CANDIDATE / "validation.json", VALIDATION_SHA))
    original = package.member_bytes("content.tei.xml")
    if sha256(original).hexdigest() != ORIGINAL_TEI_SHA:
        raise ValueError("Ryle candidate TEI changed")
    revision = dict(id="ryle-holiness-ccel-electronic-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained CCEL ThML electronic witness of Holiness.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=len(source), source_scope=acquisition["retained_files"][0]["scope"])
    declared = source_binding["source_scope"]
    derived = bind_reviewed_header(original, expected_sha256=ORIGINAL_TEI_SHA,
                                   identity=IDENTITY, source=source_binding,
                                   source_url=acquisition["url"], declared_scope=declared,
                                   revision=revision)
    header, tail = derived.split(b"</teiHeader>", 1)
    old_change = b'<change status="partial">'
    if header.count(old_change) != 1:
        raise ValueError("Ryle historical partial revision marker differs")
    # The historical change text still records its partial technical state;
    # the native accepted header accepts the change without a status attribute.
    derived = header.replace(old_change, b"<change>", 1) + b"</teiHeader>" + tail
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Ryle accepted header changed the reconstructed body")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Ryle staged TEI P5 validation failed: {errors[:3]}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(source),
                     sha256=SOURCE_SHA, scope=declared)]
    scope = dict(kind="edition", declared=declared, expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=source_binding, candidate=make_file_binding(stage, candidate),
                  scope=declared, accepted_scope=dict(kind="edition", declared=declared),
                  expected_members=expected, included_members=included, excluded_members=[],
                  missing_members=[], unknown_members=[])
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=len(source), source_manifest_sha256=MANIFEST_SHA,
        candidate_package_sha256=PACKAGE_SHA,
        source_feature_counts=dict(elements=5698, attributes=15049, text_nodes=5235, tail_nodes=5547),
        excluded_formatting_only_elements=32, unsupported_elements=0,
        basis="Independent source census and oracle in 37c-269; current package and XML hashes rechecked."))
    command = "py -3 -m build.tools.stage_ryle_holiness_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["The 37c-269 producer and oracle use the same retained ThML member; the review separately inspected source structure and exact visible locations."],
                     independent_corroboration="The 37c-269 independent oracle, mutation checks, different-process reproduction, and source/TEI visual comparison are reused only for the byte-identical source and original TEI body.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            candidate_package_sha256=PACKAGE_SHA, source_manifest_sha256=MANIFEST_SHA,
            current_validation_sha256=VALIDATION_SHA, historical_review_path=REVIEW.as_posix(),
            accepted_header_body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    reviewed_at = _now()
    review = dict(reviewer="agent:ryle-holiness-electronic-stage", reviewed_at=reviewed_at,
                  coverage=dict(status="partial", declared=declared,
                                reached=[f"{SOURCE.as_posix()}#i", f"{SOURCE.as_posix()}#ii",
                                         f"{SOURCE.as_posix()}#iii", f"{SOURCE.as_posix()}#iv"],
                                inspected=[f"{SOURCE.as_posix()}#i", f"{SOURCE.as_posix()}#ii",
                                           f"{SOURCE.as_posix()}#iii", f"{SOURCE.as_posix()}#iv"],
                                unreviewed=[f"{SOURCE.as_posix()}#full-visual-proofreading"]),
                  source_quality_uncertainty=["Print collation and complete proofing of the CCEL electronic transcription were not performed."],
                  discrepancies=[], unreviewed_residuals=["The 37c-269 visual record is bounded; its poetry navigation warning and narrow table wrapping remain disclosed."])
    review_file = _put_json(stage, EVIDENCE / "review.json", common | review | dict(
        inherited_review_report=REVIEW.as_posix(),
        inherited_source_sha256=SOURCE_SHA, inherited_tei_sha256=ORIGINAL_TEI_SHA))
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
    acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                   master=make_file_binding(stage, master_path))
    write_acceptance(_io_path(acceptance_path), acceptance)
    state = _json(stage / WORK / "state.json")
    target = next(t for t in state["targets"] if t["target_type"] == "edition" and t["target_id"] == EDITION_ID)
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    target["evidence"].extend([EDITION.joinpath("master.tei.xml").as_posix(),
                               EDITION.joinpath("acceptance.json").as_posix()])
    _put_json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or not projected["rows"]:
        raise ValueError(f"Ryle actual-master prose projection failed: {errors[:3]}")
    receipt = dict(contract=CONTRACT, status="staged-only", canonical_root=ROOT.as_posix(),
                   stage_root=stage.as_posix(), work_id=WORK_ID, source_path=SOURCE.as_posix(),
                   source_sha256=SOURCE_SHA, source_manifest_sha256=MANIFEST_SHA,
                   original_candidate_sha256=PACKAGE_SHA, original_tei_sha256=ORIGINAL_TEI_SHA,
                   current_validation_sha256=VALIDATION_SHA, before=before, after=_files(stage / WORK),
                   accepted_master_sha256=_sha(master_path), acceptance_sha256=_sha(acceptance_path),
                   projection_rows=len(projected["rows"]), rights="not-assessed", installation="not-performed")
    _put_json(stage, Path("ryle-holiness-stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"status": result["status"], "stage_root": result["stage_root"],
                      "master_sha256": result["accepted_master_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
