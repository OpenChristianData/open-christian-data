"""Stage only Gregory's complete Select Letters subtree from CCEL NPNF2-07."""

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

from build.tei.npnf2_lib046_gregory_select_letters_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "gregory-of-nazianzus-select-letters"
SOURCE = Path("raw/ccel/npnf2/npnf207.xml")
SOURCE_SHA = "3ac73f4179c0b7d6e66e6fea04ae572e64c0e4a80e8fa38980b40366c8a13928"
SOURCE_BYTES = 4_247_548
MANIFEST = Path("sources/structured-text/gregory-of-nazianzus-select-letters/gregory-select-letters.source-manifest.json")
MANIFEST_SHA = "580a785f5842ba47e8eed12b0b847a017250b063733f94ad55f5af0aaa790b7a"
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/gregory-select-letters-npnf207-native-screen-20260928-v1")
PACKAGE_SHA = "250fb3d30e67a437c71b5af4c5649289e6f717be9a2fae8ab59f3b1e28343655"
ISSUE = Path("plans/2026-08-31-sample-first-library-verification/issues/37c-179-gregory-of-nazianzus-select-letters.md")
CONTRACT = "ocd-gregory-select-letters-npnf207-selected-ccel-stage-v1"
ROOT_TITLE = "Select Letters of Saint Gregory Nazianzen."
CREDIT = b'<bibl xmlns="http://www.tei-c.org/ns/1.0"><note type="source-credit">sourced via CCEL.org</note></bibl>'
SOURCE_TITLE_LABEL = b'<bibl xmlns="http://www.tei-c.org/ns/1.0"><note type="retained-electronic-title-source-label" n="npnf207">Electronic volume title source @n: npnf207</note></bibl>'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"Gregory Select Letters source or evidence changed: {path}")
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
        raise ValueError("Gregory Select Letters requires a fresh external stage")
    if len(_read(ROOT / SOURCE, SOURCE_SHA)) != SOURCE_BYTES:
        raise ValueError("Gregory Select Letters retained file length changed")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(PACKAGE)
    report = validate(manifest, package, _oracle)
    scope = manifest.record["scope"]
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA
            or report.status != "pass" or scope["kind"] != "complete-source-subtree"
            or tuple(scope["assigned_roots_in_source_order"]) != (("npnf207", "iv", WORK_ID),)
            or tuple(scope["excluded_top_level_roots"]) != ("i", "ii", "iii", "v")
            or tuple(scope["direct_assigned_div2_order"]) != ("iv.i", "iv.ii", "iv.iii", "iv.iv")):
        raise ValueError("Gregory Select Letters current manifest, package, or oracle differs")
    profiles = [item for item in manifest.record["authorities"]
                if item["name"] == "reconstruction-profile"]
    if len(profiles) != 1:
        raise ValueError("Gregory Select Letters reconstruction profile is not unique")
    profile = json.loads(_read(ROOT / profiles[0]["path"]))
    envelope = profile["source_envelope"]
    if (envelope["assigned_root_title"] != ROOT_TITLE
            or envelope["top_level_div1_ids_in_order"] != ["i", "ii", "iii", "iv", "v"]
            or envelope["direct_div2_ids_in_order"] != ["iv.i", "iv.ii", "iv.iii", "iv.iv"]
            or profile["assigned_census"]["elements"] != 892):
        raise ValueError("Gregory Select Letters exact source envelope differs")
    work_path = Path("library/works") / WORK_ID
    before = _files(ROOT / work_path)
    work = json.loads(_read(ROOT / work_path / "work.json"))
    state = json.loads(_read(ROOT / work_path / "state.json"))
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    identity = {"work_id": WORK_ID, "textual_form_id": form["textual_form_id"],
                "edition_id": edition["edition_id"], "acquisition_id": edition["acquisition_ids"][0]}
    edition_path = (work_path / "forms" / identity["textual_form_id"] /
                    "editions" / identity["edition_id"])
    acquisition_path = edition_path / "acquisitions" / f"{identity['acquisition_id']}.json"
    acquisition = json.loads(_read(ROOT / acquisition_path))
    retained = acquisition["retained_files"]
    if (len(before) != 3 or edition.get("category") is not None or len(retained) != 1
            or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA or retained[0]["bytes"] != SOURCE_BYTES
            or acquisition["url"] != "https://www.ccel.org/ccel/schaff/npnf207.xml"
            or any((ROOT / edition_path / name).exists() for name in ("acceptance.json", "master.tei.xml"))):
        raise ValueError("Gregory Select Letters acquired edition differs")
    targets = [item for item in state["targets"] if item["target_type"] == "edition"
               and item["target_id"] == identity["edition_id"]]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError("Gregory Select Letters edition is not uniquely acquired")
    stage.mkdir(parents=True)
    for relative, digest in before.items():
        _put(stage, work_path / relative, _read(ROOT / work_path / relative, digest))
    dependencies = {SOURCE, MANIFEST, ISSUE,
                    Path(manifest.record["converter"]["implementation_path"]),
                    Path(manifest.record["validator"]["implementation_path"])}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    for ref in set(work.get("evidence", [])) | {
        value for target in state["targets"] for value in target.get("evidence", [])
    }:
        relative = Path(ref.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe Gregory Select Letters inherited evidence: {ref}")
        if not relative.is_relative_to(work_path):
            dependencies.add(relative)
    for relative in sorted(dependencies):
        _put(stage, relative, _read(ROOT / relative))
    evidence = work_path / "integration" / "gregory-select-letters-npnf207-selected-v1"
    for member in package.member_names:
        _put(stage, evidence / "inputs/package" / member, package.member_bytes(member))
    _json(stage, evidence / "inputs/validation.json", {
        "status": report.status, "candidate_sha256": package.sha256,
        "source_manifest_sha256": manifest.sha256, "report_sha256": report.sha256,
        "attestation": dict(report.attestation), "findings": list(report.findings)})
    updated_work = json.loads(json.dumps(work))
    updated_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    validate_identity_update(work, updated_work)
    _json(stage, work_path / "work.json", updated_work)
    load_work(_io_path(stage / work_path / "work.json"))
    selected_scope = ("Complete source-native ThML.body/div1[@id='iv'] (Select Letters of "
                      "Saint Gregory Nazianzen.) only; the enclosing NPNF2-07 header, "
                      "title page, Cyril, Gregory Orations and volume indexes remain outside "
                      "this accepted constituent selection.")
    acquired_scope = retained[0]["scope"]
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
                      "source_bytes": SOURCE_BYTES, "source_scope": acquired_scope}
    revision = {"id": "gregory-select-letters-npnf207-selected-v1",
                "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Represent only the complete retained NPNF2-07 root iv; volume-level translation credit is not allocated to individual letters."}
    original = package.member_bytes("content.tei.xml")
    derived = bind_reviewed_header(original, expected_sha256=sha256(original).hexdigest(),
                                   identity=identity, source=source_binding,
                                   source_url=acquisition["url"], declared_scope=selected_scope,
                                   revision=revision, historical_source_description={
                                       "pointers": [], "sha256": []})
    source_title = b'<title type="retained-electronic-title" n="npnf207">'
    if (derived.count(b"</sourceDesc>") != 1 or derived.count(CREDIT) != 0
            or derived.count(source_title) != 1):
        raise ValueError("Gregory Select Letters reviewed header shape changed")
    derived = derived.replace(source_title, b'<title type="retained-electronic-title">', 1)
    derived = derived.replace(b"</sourceDesc>", CREDIT + SOURCE_TITLE_LABEL + b"</sourceDesc>", 1)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("Gregory Select Letters selected source text changed")
    candidate_path = _put(stage, evidence / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate_path)):
        raise ValueError(f"Gregory Select Letters P5 errors: {errors[:2]}")
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": SOURCE_BYTES,
                 "sha256": SOURCE_SHA, "scope": selected_scope}]
    acceptance_scope = {"kind": "selection", "declared": selected_scope,
                        "expected_members": expected, "included_members": included,
                        "excluded_members": []}
    common = {"identity": identity, "source": source_binding,
              "candidate": make_file_binding(stage, candidate_path), "scope": selected_scope,
              "accepted_scope": {"kind": "selection", "declared": selected_scope},
              "expected_members": expected, "included_members": included,
              "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = _json(stage, evidence / "source-accounting.json", common | {
        "scope": acquired_scope, "source_sha256": SOURCE_SHA, "source_bytes": SOURCE_BYTES,
        "source_manifest_sha256": manifest.sha256, "candidate_package_sha256": package.sha256,
        "selected_root_id": "iv", "selected_root_title": ROOT_TITLE,
        "selected_div2_ids": envelope["direct_div2_ids_in_order"],
        "excluded_top_level_div1_ids": envelope["excluded_top_level_div1_ids"],
        "selected_census": profile["assigned_census"], "unsupported_elements": 0,
        "basis": "Current independent source oracle; complete named subtree, exact sibling exclusion, byte-identical TEI text, P5 and one accepted native prose row."})
    command = "py -3 -m build.tools.stage_gregory_select_letters_npnf207_acceptance --stage <fresh-external-dir>"
    technical = {"producer": {"id": manifest.record["converter"]["id"]},
                 "checker": {"id": manifest.record["validator"]["id"]},
                 "shared_assumptions": ["Producer and independent oracle inspect the same retained NPNF2-07 XML member."],
                 "independent_corroboration": "Current source oracle, P5, unchanged selected text, stock native projection and exact source-subtree census."}
    for label in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _json(stage, evidence / (label + ".json"), common | {
            "status": "pass", "command": command, "exit_code": 0, "claim": label,
            "candidate_package_sha256": package.sha256,
            "source_manifest_sha256": manifest.sha256, "oracle_report_sha256": report.sha256,
            "accepted_header_body_unchanged": True})
        technical[label] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    reviewed_at = _now()
    review = {"reviewer": "agent:gregory-select-letters-npnf207-stage", "reviewed_at": reviewed_at,
              "coverage": {"status": "partial", "declared": selected_scope,
                           "reached": [f"{SOURCE.as_posix()}#iv"],
                           "inspected": [f"{SOURCE.as_posix()}#iv"],
                           "unreviewed": [f"{SOURCE.as_posix()}#iv-complete-visual-proofreading"]},
              "source_quality_uncertainty": ["Complete visual proofreading and print collation were not performed."],
              "discrepancies": [],
              "unreviewed_residuals": ["Full visual/human review, constituent translator allocation, rights and publication remain unresolved."]}
    review_file = _json(stage, evidence / "review.json", common | review | {
        "selected_root_id": "iv", "source_profile": profiles[0]["path"]})
    decision = {"source_local_disposition": "Agent technical acceptance of only complete retained NPNF2-07 div1 iv for Gregory Select Letters; sibling anthology material excluded.",
                "blockers": [], "human_decision": {"status": "not-recorded"},
                "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                                     "assessed_at": reviewed_at, "supported_scope": selected_scope,
                                     "unresolved_claims": [], "unassessed_stronger_claims": [
                                         "sibling anthology material", "work-specific translator allocation",
                                         "complete proofreading", "human review", "rights clearance", "publication"]}}
    acceptance = build_acceptance_record(stage, identity=identity, candidate_path=candidate_path,
                                         source_accounting_path=accounting, scope=acceptance_scope,
                                         technical=technical, review=review | {"report_path": review_file},
                                         representation_revision=revision, decision=decision)
    acceptance_path = stage / edition_path / "acceptance.json"
    write_acceptance(_io_path(acceptance_path), acceptance)
    master_path = _put(stage, edition_path / "master.tei.xml", derived)
    acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                   master=make_file_binding(stage, master_path))
    write_acceptance(_io_path(acceptance_path), acceptance)
    target = targets[0]
    target.update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    target["evidence"].extend([master_path.relative_to(stage).as_posix(),
                               acceptance_path.relative_to(stage).as_posix()])
    _json(stage, work_path / "state.json", state)
    validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / work_path / "state.json"), root=_io_path(stage))
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"Gregory Select Letters accepted native projection differs: {errors[:2]}")
    after = _files(stage / work_path)
    dependencies_map = {key: value for key, value in _files(stage).items()
                        if not key.startswith(work_path.as_posix() + "/") and key != "stage-receipt.json"}
    receipt = {"contract": CONTRACT, "status": "staged-only", "installation": "not-performed",
               "rights": "not-assessed", "canonical_root": ROOT.as_posix(),
               "stage_root": stage.as_posix(), "dependencies": dependencies_map,
               "work": {"work_id": WORK_ID, "work_path": work_path.as_posix(),
                        "before": before, "after": after, "source_path": SOURCE.as_posix(),
                        "source_sha256": SOURCE_SHA, "source_manifest_sha256": manifest.sha256,
                        "candidate_package_sha256": package.sha256, "selected_root_id": "iv",
                        "new_master_sha256": sha256(derived).hexdigest(),
                        "new_acceptance_sha256": sha256(_read(acceptance_path)).hexdigest(),
                        "native_rows": 1}}
    _json(stage, Path("stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    receipt = prepare(args.stage)
    print(json.dumps({"before": len(receipt["work"]["before"]),
                      "after": len(receipt["work"]["after"]),
                      "master_sha256": receipt["work"]["new_master_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
