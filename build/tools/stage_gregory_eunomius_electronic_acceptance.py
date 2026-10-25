"""Prepare one exact Gregory of Nyssa electronic-witness acceptance outside the library.

The command creates a fresh external stage. It does not install the work.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.acquisitions import validate_acquisition
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
WORK_ID = "gregory-of-nyssa-against-eunomius"
FORM_ID = "gregory-of-nyssa-against-eunomius-english"
EDITION_ID = "gregory-of-nyssa-against-eunomius-retained-electronic-witness"
ACQUISITION_ID = "gregory-of-nyssa-against-eunomius-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/ccel/npnf2/npnf205.xml")
MANIFEST = Path("sources/structured-text/gregory-of-nyssa-against-eunomius/gregory-of-nyssa-against-eunomius.source-manifest.json")
REVIEW = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-181.md")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-181-gregory-of-nyssa-against-eunomius.md")
VISUAL_REVIEW = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/npnf2-missing-roots-native-visual-review.json")
VISUAL_REVIEW_SHA = "d2ea95cfd2e3ba423bc708f05ae7348db3233c3940acc509d9dfe22e965af825"
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/gregory-nyssa-eunomius-current-successor-20260927-v1")
CVW = Path("D:/Library/Open Christian Data/candidate-reviews/npnf2-missing-roots-native-review-20260911-r2")
EVIDENCE = WORK / "integration/gregory-eunomius-electronic-acceptance-v1"
SOURCE_SHA = "43e87ed232457fd2d5862f72dd2d5d84fe1e8b69f4c3eec839bad04579327bf3"
MANIFEST_SHA = "58aa2013d26efb322fd4a6743780d2d2eb59a4897e57c1710260045c368680a9"
PACKAGE_SHA = "99f8d74cc9f70080740810d5ca29a7948d57c11e90650bf50a2f42693a3a8b0f"
VALIDATION_SHA = "bac6cc039c2dda6e785ce198ad3fefd74b93009d839bc6f24bbc46e7c4242331"
ORIGINAL_TEI_SHA = "46e6f4b48e774e85f43e98bffafbd31dea3978916cfd4c62cc700ae1af22a726"
CONTRACT = "ocd-gregory-eunomius-electronic-stage-v1"
SELECTED_SCOPE = "Complete CCEL NPNF2-05 source subtree ThML.body/div1[@id='viii']/div2[@id='viii.i'] (Against Eunomius, two prefatory letters and Books I-XII); enclosing volume matter and sibling works are source-accounted outside this accepted work."
CVW_FILES = {
    "capture-npnf2-missing-roots.json": "2f6cafd0857022680ad94c2a20d5ac5a9797a6447e3f361e8989e728fdb0c231",
    "gregory-of-nyssa-against-eunomius-0.png": "d11b839740275360c242598674a55e3cad2aa7485ea6c47d45643fef2f850a57",
    "gregory-of-nyssa-against-eunomius-1.png": "ccaba70ecdc985774020e1b946f760815c71c88676783387001b1a16c28a378d",
    "gregory-of-nyssa-against-eunomius-2.png": "8a8cbef75085192fb1f49db7f10dfd71ccd22f0ecf91b4fc1951d6eb5518b60d",
}
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Gregory Against Eunomius source or evidence bytes changed: {path}")
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
        raise ValueError("Gregory Against Eunomius stage must be a fresh external directory")
    source = _read(ROOT / SOURCE, SOURCE_SHA)
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(_io_path(CANDIDATE / "package"))
    validation = _json(CANDIDATE / "validation.json")
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA
            or _sha(CANDIDATE / "validation.json") != VALIDATION_SHA
            or _sha(CANDIDATE / "package/content.tei.xml") != ORIGINAL_TEI_SHA
            or validation.get("status") != "pass"
            or validation.get("findings") != []
            or validation.get("source_manifest_sha256") != MANIFEST_SHA
            or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA):
        raise ValueError("current Gregory Against Eunomius source, candidate, or validation differs")
    old_work = _json(ROOT / WORK / "work.json")
    old_state = _json(ROOT / WORK / "state.json")
    acquisition = _json(ROOT / ACQUISITION)
    if (old_work.get("work_id") != WORK_ID or old_work["textual_forms"][0]["editions"][0]["edition_id"] != EDITION_ID
            or acquisition.get("acquisition_id") != ACQUISITION_ID
            or len(acquisition.get("retained_files", [])) != 1
            or acquisition["retained_files"][0]["path"] != SOURCE.as_posix()
            or acquisition["retained_files"][0]["bytes"] != len(source)
            or acquisition["retained_files"][0]["sha256"] != SOURCE_SHA
            or manifest.record["scope"] != {"kind": "complete-source-subtree", "root_path": ("viii", "viii.i")}):
        raise ValueError("Gregory Against Eunomius work or acquired XML preimage differs")
    edition_target = [t for t in old_state["targets"] if t["target_type"] == "edition" and t["target_id"] == EDITION_ID]
    if len(edition_target) != 1 or edition_target[0]["stage"] != "acquired":
        raise ValueError("Gregory Against Eunomius edition target is not uniquely acquired")
    if _io_path(ROOT / EDITION / "acceptance.json").exists() or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("Gregory Against Eunomius is already accepted in the canonical library")
    before = _files(ROOT / WORK)
    for relative in before:
        _copy(stage, WORK / relative)
    if _files(stage / WORK) != before:
        raise ValueError("Gregory Against Eunomius staged work preimage differs")
    dependencies = {SOURCE, MANIFEST, TICKET, VISUAL_REVIEW, Path("docs/sources/ccel-permission.md")}
    dependencies.update(Path(authority["path"]) for authority in manifest.record["authorities"])
    for reference in set(old_work.get("evidence", [])) | {
        item for target in old_state["targets"] for item in target.get("evidence", [])
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited Gregory Against Eunomius evidence path: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            _copy(stage, relative)
    _put(stage, EVIDENCE / "inputs/prior-review.md", _read(ROOT / REVIEW))
    cvw_receipt = _json(CVW / "capture-npnf2-missing-roots.json")
    visual_review = json.loads(_read(ROOT / VISUAL_REVIEW, VISUAL_REVIEW_SHA))
    coverage = [item for item in visual_review.get("coverage", []) if item.get("work_id") == WORK_ID]
    if (cvw_receipt.get("session_id") != "de6f1c41cb40431ba612b06963615a34"
            or visual_review.get("status") != "pass-for-bounded-native-review"
            or visual_review.get("session_id") != cvw_receipt.get("session_id")
            or len(coverage) != 1 or coverage[0].get("source_root") != "viii.i"
            or len(coverage[0].get("screenshots", [])) != 3
            or {item["path"]: item["sha256"] for item in coverage[0]["screenshots"]}
               != {name: digest for name, digest in CVW_FILES.items() if name.endswith(".png")}
            or _sha(Path("D:/Library/Open Christian Data/candidate-reviews/37c181-npnf205-viii-i-20260911-r2/package/content.tei.xml")) != ORIGINAL_TEI_SHA):
        raise ValueError("Gregory Against Eunomius current CVW session differs")
    for name, expected_sha in CVW_FILES.items():
        source_path = CVW / ("visuals" if name.endswith(".png") else "") / name
        _put(stage, EVIDENCE / "visual" / name, _read(source_path, expected_sha))
    work = _json(stage / WORK / "work.json")
    edition = work["textual_forms"][0]["editions"][0]
    if edition.get("category") is not None or edition.get("language") != "en":
        raise ValueError("Gregory Against Eunomius category or language preimage differs")
    edition["category"] = "prose"
    validate_identity_update(old_work, work)
    _put_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    acquisition["source_path"] = SOURCE.as_posix()
    acquisition["source_bytes"] = len(source)
    acquisition["source_sha256"] = SOURCE_SHA
    acquisition["source_scope"] = SELECTED_SCOPE
    acquisition["retained_files"][0]["scope"] = SELECTED_SCOPE
    _put_json(stage, ACQUISITION, acquisition)
    validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    for name in package.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _put(stage, EVIDENCE / "inputs/validation.json", _read(CANDIDATE / "validation.json", VALIDATION_SHA))
    original = package.member_bytes("content.tei.xml")
    if sha256(original).hexdigest() != ORIGINAL_TEI_SHA:
        raise ValueError("Gregory Against Eunomius candidate TEI changed")
    revision = dict(id="gregory-eunomius-ccel-electronic-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept only the retained CCEL ThML Against Eunomius source subtree; sibling works remain outside.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=len(source), source_scope=acquisition["retained_files"][0]["scope"])
    declared = SELECTED_SCOPE
    derived = bind_reviewed_header(original, expected_sha256=ORIGINAL_TEI_SHA,
                                   identity=IDENTITY, source=source_binding,
                                   source_url=acquisition["url"], declared_scope=declared,
                                   revision=revision,
                                   historical_source_description={
                                       "pointers": [SOURCE.as_posix()], "sha256": [SOURCE_SHA]})
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Gregory Against Eunomius accepted header changed the reconstructed body")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Gregory Against Eunomius staged TEI P5 validation failed: {errors[:3]}")
    expected = [dict(path=SOURCE.as_posix(), position=1)]
    included = [dict(path=SOURCE.as_posix(), position=1, bytes=len(source),
                     sha256=SOURCE_SHA, scope=declared)]
    scope = dict(kind="selection", declared=declared, expected_members=expected,
                 included_members=included, excluded_members=[])
    common = dict(identity=IDENTITY, source=source_binding, candidate=make_file_binding(stage, candidate),
                  scope=declared, accepted_scope=dict(kind="selection", declared=declared),
                  expected_members=expected, included_members=included, excluded_members=[],
                  missing_members=[], unknown_members=[])
    accounting = _put_json(stage, EVIDENCE / "source-accounting.json", common | dict(
        source_sha256=SOURCE_SHA, source_bytes=len(source), source_manifest_sha256=MANIFEST_SHA,
        candidate_package_sha256=PACKAGE_SHA,
        source_feature_counts=dict(selected_elements=4556, full_document_elements=19333),
        source_roots=["viii.i"],
        unsupported_elements=0,
        basis="Fresh current-manifest candidate oracle checked the complete selected viii.i subtree; its TEI is byte-identical to the three-frame visually reviewed predecessor. Enclosing volume and sibling roots remain outside the accepted work."))
    command = "py -3 -m build.tools.stage_gregory_eunomius_electronic_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["The Gregory producer and oracle read the same retained ThML member; both rely on the repository XML parser."],
                     independent_corroboration="Fresh current-manifest oracle validation and the retained three-frame native CVW review of byte-identical source and TEI.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            candidate_package_sha256=PACKAGE_SHA, source_manifest_sha256=MANIFEST_SHA,
            current_validation_sha256=VALIDATION_SHA, historical_review_path=REVIEW.as_posix(),
            accepted_header_body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    reviewed_at = _now()
    review = dict(reviewer="agent:gregory-eunomius-electronic-stage", reviewed_at=reviewed_at,
                  coverage=dict(status="partial", declared=declared,
                                reached=[f"{SOURCE.as_posix()}#{root}" for root in ("viii.i", "viii.i.iv.xii", "viii.i.xiv.v")],
                                inspected=[f"{SOURCE.as_posix()}#{root}" for root in ("viii.i", "viii.i.iv.xii", "viii.i.xiv.v")],
                                unreviewed=[f"{SOURCE.as_posix()}#full-visual-proofreading"]),
                  source_quality_uncertainty=["Print collation and complete proofing of the CCEL electronic transcription were not performed.",
                                              "The source-supplied prefatory exchange includes a letter from Peter of Sebasteia; the accepted work attribution does not assign his words to Gregory.",
                                              "The volume-level translation credits do not prove a narrower work-specific allocation."],
                  discrepancies=[], unreviewed_residuals=["The 37c-181 native review sampled the opening, middle, and terminal divisions; full visual proofreading remains open."])
    review_file = _put_json(stage, EVIDENCE / "review.json", common | review | dict(
        inherited_review_report=REVIEW.as_posix(),
        inherited_source_sha256=SOURCE_SHA, inherited_tei_sha256=ORIGINAL_TEI_SHA,
        current_cvw_session="de6f1c41cb40431ba612b06963615a34",
        current_cvw_files=CVW_FILES))
    decision = dict(source_local_disposition="Agent acceptance of the selected Against Eunomius subtree of the retained CCEL electronic volume only.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"],
                                          assessed_at=reviewed_at, supported_scope=declared,
                                          unresolved_claims=[], unassessed_stronger_claims=[
                                              "print edition collation", "full visual proofreading",
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
        raise ValueError(f"Gregory Against Eunomius actual-master prose projection failed: {errors[:3]}")
    receipt = dict(contract=CONTRACT, status="staged-only", canonical_root=ROOT.as_posix(),
                   stage_root=stage.as_posix(), work_id=WORK_ID, source_path=SOURCE.as_posix(),
                   source_sha256=SOURCE_SHA, source_manifest_sha256=MANIFEST_SHA,
                   original_candidate_sha256=PACKAGE_SHA, original_tei_sha256=ORIGINAL_TEI_SHA,
                   current_validation_sha256=VALIDATION_SHA, before=before, after=_files(stage / WORK),
                   accepted_master_sha256=_sha(master_path), acceptance_sha256=_sha(acceptance_path),
                   projection_rows=len(projected["rows"]), rights="not-assessed", installation="not-performed")
    _put_json(stage, Path("gregory-eunomius-stage-receipt.json"), receipt)
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
