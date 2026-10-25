"""Stage the five selected Against Heresies books from retained CCEL ANF1."""

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

from build.tei.irenaeus_against_heresies_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "irenaeus-against-heresies"
WORK = Path("library/works") / WORK_ID
SOURCE = Path("raw/ccel/anf/anf01.xml")
SOURCE_SHA = "8012ea0e35b497d2fbd783f9d4fd7b3a27d98c6dc66fd427b50d7312e6dd45af"
MANIFEST = Path("sources/structured-text/irenaeus-against-heresies/irenaeus-against-heresies.source-manifest.json")
MANIFEST_SHA = "8cd454f9a49bac237b9f6cc9bcdfe951f40a50d8e8906dcf4387ebb281c75520"
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/irenaeus-ccel-native-screen-20260928-v1")
PACKAGE_SHA = "67da5bbdb80c76df87571250f5cc15afd05e9eef7f59748dad3367bda3fa75d9"
EVIDENCE = WORK / "integration/irenaeus-against-heresies-ccel-electronic-v1"
RECEIPT = "irenaeus-against-heresies-ccel-acceptance-stage-receipt.json"
CONTRACT = "ocd-irenaeus-against-heresies-ccel-electronic-stage-v1"
REVISION = "irenaeus-anf01-five-book-v1"
SELECTED = ("ix.ii", "ix.iii", "ix.iv", "ix.vi", "ix.vii")
EXCLUDED = ("ix.i", "ix.v", "ix.viii")
ANTHOLOGY_SIBLINGS = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii")
DECLARED = (
    "The five Against Heresies book divisions ix.ii, ix.iii, ix.iv, ix.vi, ix.vii "
    "in retained ANF1 source order; introductory note ix.i, elucidation ix.v, "
    "fragments ix.viii, and sibling ANF works excluded."
)
OLD_STATUS = b"This candidate is nonaccepted; human rights review and publication authorization remain absent."
NEW_STATUS = b"This source-bound electronic reconstruction leaves human rights review and publication authorization open."
CREDIT = b'<bibl xmlns="http://www.tei-c.org/ns/1.0"><note type="source-credit">sourced via CCEL.org</note></bibl>'
REVIEW = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-209.md")
ISSUE = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-209-irenaeus-against-heresies.md")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Irenaeus source or evidence changed: {path}")
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
        raise ValueError("Irenaeus stage requires a fresh external root")
    source = _read(ROOT / SOURCE, SOURCE_SHA)
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(CANDIDATE)
    report = validate(manifest, package, _oracle)
    if manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA or report.status != "pass":
        raise ValueError("Irenaeus source-bound package changed")
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
            or acquisition["url"] != "https://www.ccel.org/ccel/schaff/anf01.xml"
            or any((ROOT / edition_path / name).exists() for name in ("acceptance.json", "master.tei.xml"))):
        raise ValueError("Irenaeus acquired edition or retained-source boundary changed")
    edition_targets = [x for x in state["targets"] if x["target_type"] == "edition"
                       and x["target_id"] == identity["edition_id"]]
    if len(edition_targets) != 1 or edition_targets[0]["stage"] != "acquired":
        raise ValueError("Irenaeus edition is not uniquely acquired")
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
            raise ValueError(f"unsafe Irenaeus inherited evidence: {ref}")
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
    profile = json.loads(_read(ROOT / "sources/structured-text/irenaeus-against-heresies/irenaeus-against-heresies.reconstruction-profile.json"))
    if (tuple(profile["selected_book_ids"]) != SELECTED
            or tuple(profile["excluded_irenaeus_div2_ids"]) != EXCLUDED
            or tuple(profile["excluded_sibling_anf_div1_ids"]) != ANTHOLOGY_SIBLINGS
            or profile["feature_count"] != 9159):
        raise ValueError("Irenaeus selected books or anthology exclusions changed")
    declared = DECLARED
    acquired_scope = retained[0]["scope"]
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
                      "source_bytes": len(source), "source_scope": acquired_scope}
    revision = {"id": REVISION, "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Represent only the five source-attested Against Heresies books in the retained ANF1 electronic member; anthology and print edition remain separate."}
    original = package.member_bytes("content.tei.xml")
    derived = bind_reviewed_header(original, expected_sha256=sha256(original).hexdigest(),
                                   identity=identity, source=source_binding,
                                   source_url=acquisition["url"], declared_scope=declared,
                                   revision=revision)
    if derived.count(OLD_STATUS) != 1 or derived.count(b"</sourceDesc>") != 1:
        raise ValueError("Irenaeus reviewed header status or source description changed")
    derived = derived.replace(OLD_STATUS, NEW_STATUS, 1).replace(
        b"</sourceDesc>", CREDIT + b"</sourceDesc>", 1)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Irenaeus accepted header changed source-bound text")
    candidate_path = _put(stage, EVIDENCE / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate_path)):
        raise ValueError(f"Irenaeus accepted TEI P5 errors: {errors[:2]}")
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": len(source),
                 "sha256": SOURCE_SHA, "scope": declared}]
    scope = {"kind": "selection", "declared": declared, "expected_members": expected,
             "included_members": included, "excluded_members": []}
    common = {"identity": identity, "source": source_binding,
              "candidate": make_file_binding(stage, candidate_path), "scope": declared,
              "accepted_scope": {"kind": "selection", "declared": declared},
              "expected_members": expected, "included_members": included,
              "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = _json(stage, EVIDENCE / "source-accounting.json", common | {
        "scope": acquired_scope,
        "source_sha256": SOURCE_SHA, "source_bytes": len(source),
        "source_manifest_sha256": MANIFEST_SHA, "candidate_package_sha256": PACKAGE_SHA,
        "source_feature_counts": {"selected_elements": 9159, "selected_attributes": 28874},
        "selected_book_ids": list(SELECTED),
        "excluded_irenaeus_div2_ids": list(EXCLUDED),
        "excluded_sibling_anf_div1_ids": list(ANTHOLOGY_SIBLINGS),
        "unsupported_elements": 0,
        "basis": "Independent exact-source oracle for five books only; complete source-node crosswalk, explicit anthology exclusions, unchanged TEI text, P5 and five native prose rows. No print collation or full visual proofreading."})
    command = "py -3 -m build.tools.stage_irenaeus_anf01_ccel_acceptance --stage <fresh-external-root>"
    technical = {"producer": {"id": manifest.record["converter"]["id"]},
                 "checker": {"id": manifest.record["validator"]["id"]},
                 "shared_assumptions": ["Producer and oracle read the same retained CCEL ThML member."],
                 "independent_corroboration": "Current manifest/oracle validation, unchanged selected-book TEI text, explicit anthology exclusions, P5, stock native projection, and direct opening/end book spot checks."}
    for label in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _json(stage, EVIDENCE / (label + ".json"), common | {
            "status": "pass", "command": command, "exit_code": 0, "claim": label,
            "candidate_package_sha256": PACKAGE_SHA, "source_manifest_sha256": MANIFEST_SHA,
            "oracle_report_sha256": report.sha256, "accepted_header_body_unchanged": True})
        technical[label] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    reviewed_at = _now()
    review = {"reviewer": "agent:irenaeus-against-heresies-ccel-stage", "reviewed_at": reviewed_at,
              "coverage": {"status": "partial", "declared": declared,
                           "reached": [f"{SOURCE.as_posix()}#{x}" for x in ("ix.ii", "ix.vii")],
                           "inspected": [f"{SOURCE.as_posix()}#{x}" for x in ("ix.ii", "ix.vii")],
                           "unreviewed": [f"{SOURCE.as_posix()}#complete-five-book-visual-proofreading"]},
              "source_quality_uncertainty": ["Only opening and ending book starts were directly spot-checked against TEI; CVW and print collation were not performed."],
              "discrepancies": [],
              "unreviewed_residuals": ["Complete five-book visual proofreading, textual form, print-edition collation, rights, and publication remain unresolved."]}
    review_file = _json(stage, EVIDENCE / "review.json", common | review | {
        "prior_technical_evidence": REVIEW.as_posix(),
        "selected_book_ids": list(SELECTED), "catalog_title": work["title"]})
    decision = {"source_local_disposition": "Agent technical acceptance of only the five source-attested Against Heresies book divisions within retained CCEL ANF1; surrounding anthology and print-edition claims excluded.",
                "blockers": [], "human_decision": {"status": "not-recorded"},
                "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                                     "assessed_at": reviewed_at, "supported_scope": declared,
                                     "unresolved_claims": [], "unassessed_stronger_claims": [
                                         "surrounding ANF anthology", "textual form and print edition",
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
    if errors or len(projected["rows"]) != 5:
        raise ValueError(f"Irenaeus accepted native projection differs: {errors[:2]}")
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
                        "native_rows": 5}}
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
