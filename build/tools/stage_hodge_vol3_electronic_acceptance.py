"""Prepare one exact Hodge Volume III electronic-witness acceptance outside the library.

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
WORK_ID = "hodge-systematic-theology-vol-3"
FORM_ID = "hodge-systematic-theology-vol-3-english"
EDITION_ID = "hodge-systematic-theology-vol-3-retained-electronic-witness"
ACQUISITION_ID = "hodge-systematic-theology-vol-3-retained-source"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/ccel/hodge/theology3.xml")
MANIFEST = Path("sources/structured-text/hodge-systematic-theology-vol-3/hodge-systematic-theology-vol-3.source-manifest.json")
REVIEW = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-205.md")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-205-hodge-systematic-theology-vol-3.md")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/hodge-vol3-current-successor-20260927-v1")
CVW = Path("D:/Library/Open Christian Data/candidate-reviews/hodge-vol3-current-cvw-session-20260927-v1")
EVIDENCE = WORK / "integration/hodge-vol3-electronic-acceptance-v1"
SOURCE_SHA = "aeb92566e8ce5019f6f43c56585538c67bafcea177d9d6f1df286006f24dda54"
MANIFEST_SHA = "ff5c7ae279edf9ef590ec4a3d1328bb25199664d98a528ae2e55678caa80b607"
PACKAGE_SHA = "f22bc66f49730dddb6768cf532e038d5c3c5946ff09fc667129f33e7e4f4af43"
VALIDATION_SHA = "e68c867755d909b71d2647f416ef40bfa5f816c03c6bf42c46f7fa405ce2dbda"
ORIGINAL_TEI_SHA = "0f86a66e27609939f379b222ded4206b7334405fc857b608f3295fa610e1d839"
CONTRACT = "ocd-hodge-vol3-electronic-stage-v1"
CVW_FILES = {
    "dbfe503a7b3940e08821600dae5d7d99.receipt.json": "45883e22c321e7dedcc0e7d18588e34b00cd9b825deba19c6756b2d16776f199",
    "compare-opening.png": "d5fde09316812d1d58edcad32677f9fee624ec0ea7523581e48089522473b8ae",
    "compare-part-iv-exact.png": "31a8e926e3183fc4be387cc2b6f18c92302468948b5d6c3df71136b582f5b5eb",
    "compare-indexes-exact.png": "96b3da7cf6b01d5d835c8bfdf7d90b67c7562a8c38264e05b56736f103dce582",
}
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Hodge Volume III source or evidence bytes changed: {path}")
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
        raise ValueError("Hodge Volume III stage must be a fresh external directory")
    source = _read(ROOT / SOURCE, SOURCE_SHA)
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(_io_path(CANDIDATE / "package"))
    validation = _json(CANDIDATE / "validation.json")
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA
            or _sha(CANDIDATE / "validation.json") != VALIDATION_SHA
            or _sha(CANDIDATE / "package/content.tei.xml") != ORIGINAL_TEI_SHA
            or validation.get("status") != "pass"
            or validation.get("findings") != ["Independently compared all 14328 source elements, their attributes, direct text, tails, child order, complete five-root envelope, and TEI schema."]
            or validation.get("source_manifest_sha256") != MANIFEST_SHA
            or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA):
        raise ValueError("current Hodge Volume III source, candidate, or validation differs")
    old_work = _json(ROOT / WORK / "work.json")
    old_state = _json(ROOT / WORK / "state.json")
    acquisition = _json(ROOT / ACQUISITION)
    if (old_work.get("work_id") != WORK_ID or old_work["textual_forms"][0]["editions"][0]["edition_id"] != EDITION_ID
            or acquisition.get("acquisition_id") != ACQUISITION_ID
            or len(acquisition.get("retained_files", [])) != 1
            or acquisition["retained_files"][0]["path"] != SOURCE.as_posix()
            or acquisition["retained_files"][0]["bytes"] != len(source)
            or acquisition["retained_files"][0]["sha256"] != SOURCE_SHA):
        raise ValueError("Hodge Volume III work or acquired XML preimage differs")
    edition_target = [t for t in old_state["targets"] if t["target_type"] == "edition" and t["target_id"] == EDITION_ID]
    if len(edition_target) != 1 or edition_target[0]["stage"] != "acquired":
        raise ValueError("Hodge Volume III edition target is not uniquely acquired")
    if _io_path(ROOT / EDITION / "acceptance.json").exists() or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("Hodge Volume III is already accepted in the canonical library")
    before = _files(ROOT / WORK)
    for relative in before:
        _copy(stage, WORK / relative)
    if _files(stage / WORK) != before:
        raise ValueError("Hodge Volume III staged work preimage differs")
    dependencies = {SOURCE, MANIFEST, TICKET, Path("docs/sources/ccel-permission.md")}
    dependencies.update(Path(authority["path"]) for authority in manifest.record["authorities"])
    for reference in set(old_work.get("evidence", [])) | {
        item for target in old_state["targets"] for item in target.get("evidence", [])
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited Hodge Volume III evidence path: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            _copy(stage, relative)
    _put(stage, EVIDENCE / "inputs/prior-review.md", _read(ROOT / REVIEW))
    cvw_receipt = _json(CVW / "dbfe503a7b3940e08821600dae5d7d99.receipt.json")
    if (cvw_receipt.get("session", {}).get("session_id") != "dbfe503a7b3940e08821600dae5d7d99"
            or PACKAGE_SHA not in cvw_receipt.get("session", {}).get("candidate_sha256", [])):
        raise ValueError("Hodge Volume III current CVW session differs")
    for name, expected_sha in CVW_FILES.items():
        _put(stage, EVIDENCE / "visual" / name, _read(CVW / name, expected_sha))
    work = _json(stage / WORK / "work.json")
    edition = work["textual_forms"][0]["editions"][0]
    if edition.get("category") is not None or edition.get("language") != "en":
        raise ValueError("Hodge Volume III category or language preimage differs")
    edition["category"] = "prose"
    validate_identity_update(old_work, work)
    _put_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    for name in package.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _put(stage, EVIDENCE / "inputs/validation.json", _read(CANDIDATE / "validation.json", VALIDATION_SHA))
    original = package.member_bytes("content.tei.xml")
    if sha256(original).hexdigest() != ORIGINAL_TEI_SHA:
        raise ValueError("Hodge Volume III candidate TEI changed")
    revision = dict(id="hodge-vol3-ccel-electronic-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained CCEL ThML electronic witness of Systematic Theology, Volume III.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=len(source), source_scope=acquisition["retained_files"][0]["scope"])
    declared = source_binding["source_scope"]
    derived = bind_reviewed_header(original, expected_sha256=ORIGINAL_TEI_SHA,
                                   identity=IDENTITY, source=source_binding,
                                   source_url=acquisition["url"], declared_scope=declared,
                                   revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Hodge Volume III accepted header changed the reconstructed body")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Hodge Volume III staged TEI P5 validation failed: {errors[:3]}")
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
        source_feature_counts=dict(elements=14328),
        source_roots=["i", "ii", "iii", "iv", "v"],
        unsupported_elements=0,
        basis="Fresh current-manifest candidate oracle checked 14,328 source elements and all five body roots; byte-identical TEI and ledger match the reviewed predecessor."))
    command = "py -3 -m build.tools.stage_hodge_vol3_electronic_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["The Hodge producer and oracle read the same retained ThML member; both rely on the repository XML parser."],
                     independent_corroboration="Fresh current-manifest oracle validation and current exact-pair CVW source/TEI inspection; prior broader visual evidence applies only to byte-identical source and TEI body.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            candidate_package_sha256=PACKAGE_SHA, source_manifest_sha256=MANIFEST_SHA,
            current_validation_sha256=VALIDATION_SHA, historical_review_path=REVIEW.as_posix(),
            accepted_header_body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    reviewed_at = _now()
    review = dict(reviewer="agent:hodge-vol3-electronic-stage", reviewed_at=reviewed_at,
                  coverage=dict(status="partial", declared=declared,
                                reached=[f"{SOURCE.as_posix()}#{root}" for root in ("i", "ii", "iii", "iv", "v")],
                                inspected=[f"{SOURCE.as_posix()}#{root}" for root in ("i", "ii", "iii", "iv", "v")],
                                unreviewed=[f"{SOURCE.as_posix()}#full-visual-proofreading"]),
                  source_quality_uncertainty=["Print collation and complete proofing of the CCEL electronic transcription were not performed.",
                                              "The retained title page gives a 1940 Eerdmans imprint and separate 1872 copyright notice; exact earlier print lineage is unproven."],
                  discrepancies=[], unreviewed_residuals=["The 37c-205 visual record is bounded; its contents table extends beyond the pane width. The fresh exact-pair session sampled opening, Part IV, and indexes."])
    review_file = _put_json(stage, EVIDENCE / "review.json", common | review | dict(
        inherited_review_report=REVIEW.as_posix(),
        inherited_source_sha256=SOURCE_SHA, inherited_tei_sha256=ORIGINAL_TEI_SHA,
        current_cvw_session="dbfe503a7b3940e08821600dae5d7d99",
        current_cvw_files=CVW_FILES))
    decision = dict(source_local_disposition="Agent acceptance of the complete retained CCEL Volume III electronic witness only.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"],
                                          assessed_at=reviewed_at, supported_scope=declared,
                                          unresolved_claims=[], unassessed_stronger_claims=[
                                              "earlier print edition lineage", "full visual proofreading",
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
        raise ValueError(f"Hodge Volume III actual-master prose projection failed: {errors[:3]}")
    receipt = dict(contract=CONTRACT, status="staged-only", canonical_root=ROOT.as_posix(),
                   stage_root=stage.as_posix(), work_id=WORK_ID, source_path=SOURCE.as_posix(),
                   source_sha256=SOURCE_SHA, source_manifest_sha256=MANIFEST_SHA,
                   original_candidate_sha256=PACKAGE_SHA, original_tei_sha256=ORIGINAL_TEI_SHA,
                   current_validation_sha256=VALIDATION_SHA, before=before, after=_files(stage / WORK),
                   accepted_master_sha256=_sha(master_path), acceptance_sha256=_sha(acceptance_path),
                   projection_rows=len(projected["rows"]), rights="not-assessed", installation="not-performed")
    _put_json(stage, Path("hodge-vol3-stage-receipt.json"), receipt)
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
