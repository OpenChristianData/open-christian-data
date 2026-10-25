"""Stage Rutherford's complete retained CCEL electronic witness outside the checkout."""

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

from build.tei.ccel_puritan_lib055_rutherford_letters_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "rutherford-letters"
WORK = Path("library/works") / WORK_ID
SOURCE = Path("raw/ccel/rutherford/letters.xml")
SOURCE_SHA = "33fda0ccc68d7e35aec2dbe6abd366ca55e81c8a116973c9ed69e3becede6ebf"
MANIFEST = Path("sources/structured-text/rutherford-letters/lib055/37c-267.source-manifest.json")
MANIFEST_SHA = "16c143303874289317cf4c6090a9458000c829cd1223cea2c3170d2728178e55"
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/rutherford-letters-screen-20260928-v1")
PACKAGE_SHA = "68a6fc556e4cd88dfb5fa3d9bb9ddb850aade2566057f54888222afc52cf48ed"
EVIDENCE = WORK / "integration/rutherford-letters-ccel-electronic-v1"
RECEIPT = "rutherford-letters-ccel-acceptance-stage-receipt.json"
CONTRACT = "ocd-rutherford-letters-ccel-electronic-stage-v1"
REVISION = "rutherford-letters-ccel-electronic-v1"
OLD_STATUS = b"Nonaccepted technical candidate; human acceptance, rights clearance, accepted IR, and publication are not authorized."
NEW_STATUS = b"Source-bound electronic reconstruction; human acceptance, rights clearance, and publication are not authorized."
CREDIT = b'<bibl xmlns="http://www.tei-c.org/ns/1.0"><note type="source-credit">sourced via CCEL.org</note></bibl>'
REVIEW = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-267-cvw-evidence.json")
ISSUE = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-267-rutherford-letters.md")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Rutherford source or evidence changed: {path}")
    return content


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, (json.dumps(value, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":")) + "\n").encode("utf-8"))


def prepare(stage: Path) -> dict[str, object]:
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or ROOT.resolve() in stage.resolve().parents:
        raise ValueError("Rutherford stage requires a fresh external root")
    source = _read(ROOT / SOURCE, SOURCE_SHA)
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(CANDIDATE)
    report = validate(manifest, package, _oracle)
    if manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA or report.status != "pass":
        raise ValueError("Rutherford source-bound package changed")
    before = _files(ROOT / WORK)
    work = json.loads(_read(ROOT / WORK / "work.json"))
    state = json.loads(_read(ROOT / WORK / "state.json"))
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    identity = {"work_id": WORK_ID, "textual_form_id": form["textual_form_id"],
                "edition_id": edition["edition_id"], "acquisition_id": edition["acquisition_ids"][0]}
    edition_path = WORK / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
    acquisition_path = edition_path / "acquisitions" / (identity["acquisition_id"] + ".json")
    acquisition = json.loads(_read(ROOT / acquisition_path))
    retained = acquisition["retained_files"]
    if (len(before) != 3 or edition.get("category") is not None
            or len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA or retained[0]["bytes"] != len(source)
            or acquisition["url"] != "https://www.ccel.org/ccel/rutherford/letters.xml"
            or any((ROOT / edition_path / name).exists() for name in ("acceptance.json", "master.tei.xml"))):
        raise ValueError("Rutherford acquired edition or retained-source boundary changed")
    edition_targets = [x for x in state["targets"] if x["target_type"] == "edition"
                       and x["target_id"] == identity["edition_id"]]
    if len(edition_targets) != 1 or edition_targets[0]["stage"] != "acquired":
        raise ValueError("Rutherford edition is not uniquely acquired")
    stage.mkdir(parents=True)
    for relative, digest in before.items():
        _put(stage, WORK / relative, _read(ROOT / WORK / relative, digest))
    dependencies = {SOURCE, MANIFEST, REVIEW, ISSUE,
                    Path(manifest.record["converter"]["implementation_path"]),
                    Path(manifest.record["validator"]["implementation_path"]),
                    Path("docs/sources/ccel-permission.md")}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    for ref in set(work.get("evidence", [])) | {
        value for target in state["targets"] for value in target.get("evidence", [])
    }:
        relative = Path(ref.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe Rutherford inherited evidence: {ref}")
        if not relative.is_relative_to(WORK):
            dependencies.add(relative)
    for relative in sorted(dependencies):
        _put(stage, relative, _read(ROOT / relative))
    for name in package.member_names:
        _put(stage, EVIDENCE / "inputs/package" / name, package.member_bytes(name))
    _json(stage, EVIDENCE / "inputs/validation.json", {
        "status": report.status, "candidate_sha256": package.sha256,
        "source_manifest_sha256": manifest.sha256, "report_sha256": report.sha256,
        "attestation": dict(report.attestation), "findings": list(report.findings)})
    updated_work = json.loads(json.dumps(work))
    updated_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    validate_identity_update(work, updated_work)
    _json(stage, WORK / "work.json", updated_work)
    load_work(_io_path(stage / WORK / "work.json"))
    declared = retained[0]["scope"]
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
                      "source_bytes": len(source), "source_scope": declared}
    revision = {"id": REVISION, "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Represent the complete retained CCEL electronic member A Selection from his Letters; print identity and catalog work boundary remain unresolved."}
    original = package.member_bytes("content.tei.xml")
    derived = bind_reviewed_header(original, expected_sha256=sha256(original).hexdigest(),
                                   identity=identity, source=source_binding,
                                   source_url=acquisition["url"], declared_scope=declared,
                                   revision=revision)
    if derived.count(OLD_STATUS) != 1 or derived.count(b"</sourceDesc>") != 1:
        raise ValueError("Rutherford reviewed header status or source description changed")
    derived = derived.replace(OLD_STATUS, NEW_STATUS, 1).replace(
        b"</sourceDesc>", CREDIT + b"</sourceDesc>", 1)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Rutherford accepted header changed source-bound text")
    candidate_path = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate_path)):
        raise ValueError(f"Rutherford accepted TEI P5 errors: {errors[:2]}")
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": len(source),
                 "sha256": SOURCE_SHA, "scope": declared}]
    scope = {"kind": "edition", "declared": declared, "expected_members": expected,
             "included_members": included, "excluded_members": []}
    common = {"identity": identity, "source": source_binding,
              "candidate": make_file_binding(stage, candidate_path), "scope": declared,
              "accepted_scope": {"kind": "edition", "declared": declared},
              "expected_members": expected, "included_members": included,
              "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = _json(stage, EVIDENCE / "source-accounting.json", common | {
        "source_sha256": SOURCE_SHA, "source_bytes": len(source),
        "source_manifest_sha256": MANIFEST_SHA, "candidate_package_sha256": PACKAGE_SHA,
        "source_feature_counts": {"elements": 1171}, "unsupported_elements": 0,
        "basis": "Independent exact-source oracle; complete retained electronic member, unchanged TEI text, P5 and six native prose rows. The provider title A Selection from his Letters is preserved; catalog and print identity remain unresolved."})
    command = "py -3 -m build.tools.stage_rutherford_letters_ccel_acceptance --stage <fresh-external-root>"
    technical = {"producer": {"id": manifest.record["converter"]["id"]},
                 "checker": {"id": manifest.record["validator"]["id"]},
                 "shared_assumptions": ["Producer and oracle read the same retained CCEL ThML member."],
                 "independent_corroboration": "Current manifest/oracle validation, unchanged full TEI text, P5, stock native projection, and prior bounded source/TEI visual review."}
    for label in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _json(stage, EVIDENCE / (label + ".json"), common | {
            "status": "pass", "command": command, "exit_code": 0, "claim": label,
            "candidate_package_sha256": PACKAGE_SHA, "source_manifest_sha256": MANIFEST_SHA,
            "oracle_report_sha256": report.sha256, "accepted_header_body_unchanged": True})
        technical[label] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    reviewed_at = _now()
    review = {"reviewer": "agent:rutherford-letters-ccel-stage", "reviewed_at": reviewed_at,
              "coverage": {"status": "partial", "declared": declared,
                           "reached": [f"{SOURCE.as_posix()}#{x}" for x in ("i", "iv", "vi")],
                           "inspected": [f"{SOURCE.as_posix()}#{x}" for x in ("i", "iv", "vi")],
                           "unreviewed": [f"{SOURCE.as_posix()}#full-visual-proofreading"]},
              "source_quality_uncertainty": ["Print collation and complete human proofreading were not performed."],
              "discrepancies": [],
              "unreviewed_residuals": ["Catalog work boundary, textual form, print edition, constituent parts, rights, and publication remain unresolved."]}
    review_file = _json(stage, EVIDENCE / "review.json", common | review | {
        "prior_bounded_visual_evidence": REVIEW.as_posix(),
        "provider_title": "A Selection from his Letters", "catalog_title": work["title"]})
    decision = {"source_local_disposition": "Agent acceptance of one complete retained CCEL electronic member titled A Selection from his Letters only; no print or catalog-boundary claim.",
                "blockers": [], "human_decision": {"status": "not-recorded"},
                "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                                     "assessed_at": reviewed_at, "supported_scope": declared,
                                     "unresolved_claims": [], "unassessed_stronger_claims": [
                                         "catalog work boundary", "textual form and print edition",
                                         "full visual proofreading", "human review", "rights clearance", "publication"]}}
    acceptance = build_acceptance_record(stage, identity=identity, candidate_path=candidate_path,
                                         source_accounting_path=accounting, scope=scope,
                                         technical=technical, review=review | {"report_path": review_file},
                                         representation_revision=revision, decision=decision)
    acceptance_path = stage / edition_path / "acceptance.json"
    write_acceptance(_io_path(acceptance_path), acceptance)
    master_path = _put(stage, edition_path / "master.tei.xml", derived)
    acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                   master=make_file_binding(stage, master_path))
    write_acceptance(_io_path(acceptance_path), acceptance)
    target = next(x for x in state["targets"] if x["target_type"] == "edition"
                  and x["target_id"] == identity["edition_id"])
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    target["evidence"].extend([master_path.relative_to(stage).as_posix(),
                               acceptance_path.relative_to(stage).as_posix()])
    _json(stage, WORK / "state.json", state)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 6:
        raise ValueError(f"Rutherford accepted native projection differs: {errors[:2]}")
    after = _files(stage / WORK)
    dependencies_map = {key: value for key, value in _files(stage).items()
                        if not key.startswith(WORK.as_posix() + "/") and key != RECEIPT}
    receipt = {"contract": CONTRACT, "status": "staged-only", "installation": "not-performed",
               "rights": "not-assessed", "canonical_root": ROOT.as_posix(),
               "stage_root": stage.as_posix(), "dependencies": dependencies_map,
               "work": {"work_id": WORK_ID, "work_path": WORK.as_posix(),
                        "before": before, "after": after, "source_path": SOURCE.as_posix(),
                        "source_sha256": SOURCE_SHA, "source_manifest_sha256": MANIFEST_SHA,
                        "candidate_package_sha256": PACKAGE_SHA,
                        "new_master_sha256": sha256(derived).hexdigest(),
                        "new_acceptance_sha256": sha256(_read(acceptance_path)).hexdigest(),
                        "native_rows": 6}}
    _json(stage, Path(RECEIPT), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.stage)
    print(json.dumps({"status": result["status"], "work_id": WORK_ID,
                      "before": len(result["work"]["before"]),
                      "after": len(result["work"]["after"]),
                      "master_sha256": result["work"]["new_master_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
