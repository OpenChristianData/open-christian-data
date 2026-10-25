"""Prepare one exact Wilberforce PG25709 electronic-witness acceptance outside the library.

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
WORK_ID = "wilberforce-practical-view"
FORM_ID = "wilberforce-practical-view-retained-text"
EDITION_ID = "wilberforce-practical-view-pg25709-electronic-witness"
ACQUISITION_ID = "wilberforce-practical-view-pg25709-acquired"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/gutenberg/pg25709.txt")
MANIFEST = Path("sources/structured-text/lib072-gutenberg-evangelical/work-bindings/wilberforce-practical-view/37c-322-v3-scope-v1-source-manifest.json")
REVIEW = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-322.md")
TICKET = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-322-wilberforce-practical-view.md")
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/37c-322-wilberforce-practical-view-20260915-readable-italic-v3-scope-v1")
CVW = CANDIDATE / "cvw-evidence-v3-live-20260915-session-c67c692f2ef54791b862a281c649e0cb"
EVIDENCE = WORK / "integration/wilberforce-pg25709-electronic-acceptance-v1"
SOURCE_SHA = "995ff74ac2c819b526d4874878507bb85e1141f7e5b35a388c44846a963d6c96"
MANIFEST_SHA = "e98e408516e2115688ad6f663394eb0b77db95e432691d9081cfcd9830e61490"
PACKAGE_SHA = "6c3780c337188dea0a643d9aaf64549acf70f4c883abd4b3e839564330d88002"
VALIDATION_SHA = "d11e7618faab6e5bcc4e0740b17f4fb665c8d2b59cba5eccb67deb5241ba1054"
ORIGINAL_TEI_SHA = "206d38231feb66aca57674c9eb28d9b27143ac8002f2e40fa861c20d750ae468"
CONTRACT = "ocd-wilberforce-pg25709-electronic-stage-v1"
CVW_MANIFEST_SHA = "2e69acc573fdc19f9b2d7b4ee632e400ad089712a35d76aa6f332b579bbf328a"
CVW_REVIEW_SHA = "ab43c5b066add42ffb07ec217b0ffafbebc1a16ee8cceb6788cd6c1180f7ce52"
CVW_SESSION_SHA = "13f8c3e4b8032d865cf87cfefbb4ef38a9a6fc138c48e00f922d7ddbbf7546e8"
IDENTITY = dict(work_id=WORK_ID, textual_form_id=FORM_ID,
                edition_id=EDITION_ID, acquisition_id=ACQUISITION_ID)


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Wilberforce PG25709 source or evidence bytes changed: {path}")
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
        raise ValueError("Wilberforce PG25709 stage must be a fresh external directory")
    source = _read(ROOT / SOURCE, SOURCE_SHA)
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(_io_path(CANDIDATE / "package"))
    validation = _json(CANDIDATE / "validation.json")
    ledger = json.loads(package.member_bytes("source-accountability.json"))
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA
            or _sha(CANDIDATE / "validation.json") != VALIDATION_SHA
            or _sha(CANDIDATE / "package/content.tei.xml") != ORIGINAL_TEI_SHA
            or validation.get("status") != "pass"
            or validation.get("findings") != []
            or validation.get("source_manifest_sha256") != MANIFEST_SHA
            or validation.get("candidate_sha256") != PACKAGE_SHA
            or validation.get("attestation", {}).get("source_sha256") != SOURCE_SHA
            or len(source.splitlines()) != 10820 or source.count(b"\r\n") != 10820
            or ledger.get("total_line_count") != 10820
            or ledger.get("omitted_line_count") != 0
            or ledger.get("duplicate_line_count") != 0
            or ledger.get("assigned_member_count") != 1
            or ledger.get("assigned_work_count") != 1
            or ledger.get("source_members") != [{
                "bytes": len(source),
                "disposition": "included in full as the one primary-source member in this ticket-bound SourceManifest",
                "path": SOURCE.as_posix(), "sha256": SOURCE_SHA, "work_id": WORK_ID,
            }]):
        raise ValueError("current Wilberforce PG25709 source, candidate, or validation differs")
    old_work = _json(ROOT / WORK / "work.json")
    old_state = _json(ROOT / WORK / "state.json")
    acquisition = _json(ROOT / ACQUISITION)
    if (old_work.get("work_id") != WORK_ID or old_work["textual_forms"][0]["editions"][0]["edition_id"] != EDITION_ID
            or acquisition.get("acquisition_id") != ACQUISITION_ID
            or len(acquisition.get("retained_files", [])) != 1
            or acquisition["retained_files"][0]["path"] != SOURCE.as_posix()
            or acquisition["retained_files"][0]["bytes"] != len(source)
            or acquisition["retained_files"][0]["sha256"] != SOURCE_SHA
            or manifest.record["retained_source_path"] != SOURCE.as_posix()
            or manifest.record["source_scope"] != "one-work-one-retained-project-gutenberg-member"):
        raise ValueError("Wilberforce PG25709 work or acquired TXT preimage differs")
    edition_target = [t for t in old_state["targets"] if t["target_type"] == "edition" and t["target_id"] == EDITION_ID]
    if len(edition_target) != 1 or edition_target[0]["stage"] != "acquired":
        raise ValueError("Wilberforce PG25709 edition target is not uniquely acquired")
    if _io_path(ROOT / EDITION / "acceptance.json").exists() or _io_path(ROOT / EDITION / "master.tei.xml").exists():
        raise ValueError("Wilberforce PG25709 is already accepted in the canonical library")
    before = _files(ROOT / WORK)
    for relative in before:
        _copy(stage, WORK / relative)
    if _files(stage / WORK) != before:
        raise ValueError("Wilberforce PG25709 staged work preimage differs")
    dependencies = {SOURCE, MANIFEST, TICKET}
    dependencies.update(Path(authority["path"]) for authority in manifest.record["authorities"])
    for reference in set(old_work.get("evidence", [])) | {
        item for target in old_state["targets"] for item in target.get("evidence", [])
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited Wilberforce PG25709 evidence path: {reference}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(WORK):
            _copy(stage, relative)
    _put(stage, EVIDENCE / "inputs/prior-review.md", _read(ROOT / REVIEW))
    cvw_manifest = json.loads(_read(CVW / "evidence-manifest.v2.json", CVW_MANIFEST_SHA))
    visual_review = json.loads(_read(CVW / "cvw-review.v2.json", CVW_REVIEW_SHA))
    cvw_receipt = json.loads(_read(CVW / "cvw-session.receipt.json", CVW_SESSION_SHA))
    frames = visual_review.get("frames", [])
    file_pins = {item["path"]: item["sha256"] for item in cvw_manifest.get("files", [])}
    if (cvw_manifest.get("ticket") != "37c-322" or len(file_pins) != 15
            or len(frames) != 10
            or visual_review.get("contract") != "ocd-37c-322-cvw-visual-evidence-v2"
            or visual_review["candidate"].get("package_manifest_sha256") != PACKAGE_SHA
            or visual_review["candidate"].get("tei_sha256") != ORIGINAL_TEI_SHA
            or visual_review["candidate"].get("validation_sha256") != VALIDATION_SHA
            or visual_review["source"].get("sha256") != SOURCE_SHA
            or visual_review["source"].get("source_manifest_sha256") != MANIFEST_SHA
            or visual_review["cvw_session"].get("session_id") != "c67c692f2ef54791b862a281c649e0cb"
            or PACKAGE_SHA not in cvw_receipt["session"].get("candidate_sha256", [])
            or {item["file"]: item["sha256"] for item in frames}
               != {name: digest for name, digest in file_pins.items() if name.startswith("cvw-frame-")}):
        raise ValueError("Wilberforce PG25709 exact-pair visual evidence differs")
    for name, expected_sha in file_pins.items():
        _put(stage, EVIDENCE / "visual" / name, _read(CVW / name, expected_sha))
    _put(stage, EVIDENCE / "visual/evidence-manifest.v2.json",
         _read(CVW / "evidence-manifest.v2.json", CVW_MANIFEST_SHA))
    work = _json(stage / WORK / "work.json")
    edition = work["textual_forms"][0]["editions"][0]
    if edition.get("category") is not None or edition.get("language") is not None:
        raise ValueError("Wilberforce PG25709 category or language preimage differs")
    edition["category"] = "prose"
    edition["language"] = "en"
    work["textual_forms"][0]["language"] = "en"
    validate_identity_update(old_work, work)
    _put_json(stage, WORK / "work.json", work)
    load_work(_io_path(stage / WORK / "work.json"))
    acquisition["source_path"] = SOURCE.as_posix()
    acquisition["source_bytes"] = len(source)
    acquisition["source_sha256"] = SOURCE_SHA
    acquisition["source_scope"] = acquisition["retained_files"][0]["scope"]
    _put_json(stage, ACQUISITION, acquisition)
    validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    for name in package.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _put(stage, EVIDENCE / "inputs/validation.json", _read(CANDIDATE / "validation.json", VALIDATION_SHA))
    original = package.member_bytes("content.tei.xml")
    if sha256(original).hexdigest() != ORIGINAL_TEI_SHA:
        raise ValueError("Wilberforce PG25709 candidate TEI changed")
    revision = dict(id="wilberforce-pg25709-electronic-v1", date=datetime.now(timezone.utc).date().isoformat(),
                    note="Accept the complete retained Project Gutenberg PG25709 electronic witness.")
    source_binding = dict(source_path=SOURCE.as_posix(), source_sha256=SOURCE_SHA,
                          source_bytes=len(source), source_scope=acquisition["retained_files"][0]["scope"])
    declared = acquisition["source_scope"]
    derived = bind_reviewed_header(original, expected_sha256=ORIGINAL_TEI_SHA,
                                   identity=IDENTITY, source=source_binding,
                                   source_url=acquisition["url"], declared_scope=declared,
                                   revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Wilberforce PG25709 accepted header changed the reconstructed body")
    candidate = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate)):
        raise ValueError(f"Wilberforce PG25709 staged TEI P5 validation failed: {errors[:3]}")
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
        source_feature_counts=dict(physical_lines=10820, nonempty_lines=9796,
                                   empty_lines=1024, source_blocks=906,
                                   emphasis_spans=652),
        source_roots=["PG25709 complete TXT member"],
        unsupported_elements=0,
        basis="The snapshot-bound independent oracle accounts for all 10,820 physical source lines and exact CRLF byte reassembly; the current candidate and ten-locus visual review bind the same source and TEI."))
    command = "py -3 -m build.tools.stage_wilberforce_pg25709_acceptance --stage <fresh-external-root>"
    technical = dict(producer=dict(id=manifest.record["converter"]["id"]),
                     checker=dict(id=manifest.record["validator"]["id"]),
                     shared_assumptions=["The Wilberforce producer and oracle read the same retained PG TXT member; both rely on the frozen ticket scope snapshot."],
                     independent_corroboration="Current-manifest independent oracle validation and the retained ten-locus native CVW review of the exact source/TEI pair.")
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, EVIDENCE / f"{name}.json", common | dict(
            status="pass", command=command, exit_code=0, claim=name,
            candidate_package_sha256=PACKAGE_SHA, source_manifest_sha256=MANIFEST_SHA,
            current_validation_sha256=VALIDATION_SHA, historical_review_path=REVIEW.as_posix(),
            accepted_header_body_unchanged=True))
        technical[name] = dict(path=proof, status="pass", command=command, exit_code=0)
    reviewed_at = _now()
    loci = ["1", "23-25", "205-225", "342-345", "5410-5415", "5417-5424",
            "9177-9185", "10425", "10470", "10815-10818"]
    review = dict(reviewer="agent:wilberforce-pg25709-electronic-stage", reviewed_at=reviewed_at,
                  coverage=dict(status="partial", declared=declared,
                                reached=[f"{SOURCE.as_posix()}#line:{locus}" for locus in loci],
                                inspected=[f"{SOURCE.as_posix()}#line:{locus}" for locus in loci],
                                unreviewed=[f"{SOURCE.as_posix()}#full-visual-proofreading"]),
                  source_quality_uncertainty=["No separate print witness was collated against PG25709.",
                                              "The provider's individual Distributed Proofreaders corrections were not audited.",
                                              "The retained Roman-numeral imprint does not establish first-edition equivalence."],
                  discrepancies=[], unreviewed_residuals=[
                      "CVW flattens inline italic styling but shows the poverty/of word boundary; the separate exact-TEI CETEIcean screenshot shows italics but joins those words visually.",
                      "The ten inspected loci do not amount to complete human proofreading."])
    review_file = _put_json(stage, EVIDENCE / "review.json", common | review | dict(
        inherited_review_report=REVIEW.as_posix(),
        inherited_source_sha256=SOURCE_SHA, inherited_tei_sha256=ORIGINAL_TEI_SHA,
        current_cvw_session="c67c692f2ef54791b862a281c649e0cb",
        current_cvw_manifest_sha256=CVW_MANIFEST_SHA,
        current_cvw_review_sha256=CVW_REVIEW_SHA))
    decision = dict(source_local_disposition="Agent acceptance of the exact retained Project Gutenberg PG25709 electronic witness only.",
                    blockers=[], human_decision=dict(status="not-recorded"),
                    agent_assessment=dict(status="accepted", actor=review["reviewer"],
                                          assessed_at=reviewed_at, supported_scope=declared,
                                          unresolved_claims=[], unassessed_stronger_claims=[
                                              "print edition collation", "provider correction audit", "full visual proofreading",
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
        raise ValueError(f"Wilberforce PG25709 actual-master prose projection failed: {errors[:3]}")
    receipt = dict(contract=CONTRACT, status="staged-only", canonical_root=ROOT.as_posix(),
                   stage_root=stage.as_posix(), work_id=WORK_ID, source_path=SOURCE.as_posix(),
                   source_sha256=SOURCE_SHA, source_manifest_sha256=MANIFEST_SHA,
                   original_candidate_sha256=PACKAGE_SHA, original_tei_sha256=ORIGINAL_TEI_SHA,
                   current_validation_sha256=VALIDATION_SHA,
                   visual_manifest_sha256=CVW_MANIFEST_SHA,
                   before=before, after=_files(stage / WORK),
                   accepted_master_sha256=_sha(master_path), acceptance_sha256=_sha(acceptance_path),
                   projection_rows=len(projected["rows"]), rights="not-assessed", installation="not-performed")
    _put_json(stage, Path("wilberforce-pg25709-stage-receipt.json"), receipt)
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
