"""Stage two independently selected CCEL NPNF2-07 works outside the checkout."""

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

from build.tei.npnf2_missing_work_oracle import _oracle


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/ccel/npnf2/npnf207.xml")
SOURCE_SHA = "3ac73f4179c0b7d6e66e6fea04ae572e64c0e4a80e8fa38980b40366c8a13928"
SOURCE_BYTES = 4_247_548
VISUAL = Path("plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/npnf2-missing-roots-native-visual-review.json")
CONTRACT = "ocd-npnf207-two-selected-work-ccel-stage-v1"
OLD_STATUS = b"Nonaccepted reconstruction candidate; publication is not authorized."
NEW_STATUS = b"Source-bound selected electronic reconstruction; human acceptance, rights clearance, and publication are not authorized."
CREDIT = b'<bibl xmlns="http://www.tei-c.org/ns/1.0"><note type="source-credit">sourced via CCEL.org</note></bibl>'
ROUTES = {
    "cyril-of-jerusalem-catechetical-lectures": {
        "root_id": "ii", "root_title": "The Catechetical Lectures of S. Cyril.",
        "manifest": "sources/structured-text/cyril-of-jerusalem-catechetical-lectures/cyril-of-jerusalem-catechetical-lectures.source-manifest.json",
        "manifest_sha": "eb18037fde4a81b9b8ebccc7ca0e720df58ea15260a4f78f62462e9520472c6c",
        "package": "4a3422f8a7d012d4951660ba2dad11181b982cd993fd76c5e132932ec080f3ad",
        "issue": "37c-130-cyril-of-jerusalem-catechetical-lectures.md",
        "child_count": 28,
        "loci": ("ii", "ii.viii", "ii.xxvii"),
    },
    "gregory-of-nazianzus-select-orations": {
        "root_id": "iii", "root_title": "Select Orations of Saint Gregory Nazianzen.",
        "manifest": "sources/structured-text/gregory-of-nazianzus-select-orations/gregory-of-nazianzus-select-orations.source-manifest.json",
        "manifest_sha": "9ee0745367b4b5160e2527b9b45e9ee1664f13d8f9904bb586cb7edf1694e0e2",
        "package": "c3a70a31663ca9deb326c28bad3209a95bddd5706e2c1e848500af08401d3852",
        "issue": "37c-180-gregory-of-nazianzus-select-orations.md",
        "child_count": 27,
        "loci": ("iii", "iii.xii", "iii.xxvii"),
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path, expected: str | None = None) -> bytes:
    content = _io_path(path).read_bytes()
    if expected is not None and sha256(content).hexdigest() != expected:
        raise ValueError(f"NPNF207 source or evidence changed: {path}")
    return content


def _put(stage: Path, relative: Path, content: bytes) -> Path:
    target = stage / relative
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    _io_path(target).write_bytes(content)
    return target


def _json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, (json.dumps(value, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":")) + "\n").encode("utf-8"))


def prepare(work_id: str, stage: Path) -> dict[str, object]:
    route = ROUTES[work_id]
    stage = stage.absolute()
    if stage.exists() or not stage.parent.is_dir() or ROOT.resolve() in stage.resolve().parents:
        raise ValueError("NPNF207 work stage requires a fresh external root")
    source = _read(ROOT / SOURCE, SOURCE_SHA)
    if len(source) != SOURCE_BYTES:
        raise ValueError("NPNF207 retained source length changed")
    manifest_path = Path(route["manifest"])
    manifest = SourceManifest.load(ROOT / manifest_path, repository_root=ROOT)
    manifest.verify()
    package_path = Path("D:/Library/Open Christian Data/candidate-reviews") / (
        work_id + "-npnf207-native-screen-20260928-v1")
    package = CandidatePackage.load(package_path)
    report = validate(manifest, package, _oracle)
    if (manifest.sha256 != route["manifest_sha"] or package.sha256 != route["package"]
            or report.status != "pass" or manifest.record["work_id"] != work_id
            or tuple(manifest.record["scope"]["root_path"]) != (route["root_id"],)):
        raise ValueError(f"NPNF207 {work_id} source-bound package changed")
    profiles = [item for item in manifest.record["authorities"]
                if item["name"] == "reconstruction-profile"]
    if len(profiles) != 1:
        raise ValueError(f"NPNF207 {work_id} reconstruction profile is not unique")
    profile = json.loads(_read(ROOT / Path(profiles[0]["path"])))
    if (profile["work_id"] != work_id or profile["root_path"] != [route["root_id"]]
            or profile["root_title"] != route["root_title"]
            or len(profile["selected_child_ids"]) != route["child_count"]):
        raise ValueError(f"NPNF207 {work_id} complete root or title changed")
    visual = json.loads(_read(ROOT / VISUAL))
    matches = [item for item in visual["coverage"] if item["work_id"] == work_id]
    if (len(matches) != 1 or matches[0]["source_root"] != route["root_id"]
            or matches[0]["source_locations"] != list(route["loci"])
            or len(matches[0]["screenshots"]) != 3):
        raise ValueError(f"NPNF207 {work_id} bounded visual evidence changed")
    work_path = Path("library/works") / work_id
    before = _files(ROOT / work_path)
    work = json.loads(_read(ROOT / work_path / "work.json"))
    state = json.loads(_read(ROOT / work_path / "state.json"))
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                "edition_id": edition["edition_id"], "acquisition_id": edition["acquisition_ids"][0]}
    edition_path = work_path / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
    acquisition_path = edition_path / "acquisitions" / (identity["acquisition_id"] + ".json")
    acquisition = json.loads(_read(ROOT / acquisition_path))
    retained = acquisition["retained_files"]
    if (len(before) != 3 or edition.get("category") is not None
            or len(retained) != 1 or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA or retained[0]["bytes"] != SOURCE_BYTES
            or acquisition["url"] != "https://www.ccel.org/ccel/schaff/npnf207.xml"
            or any((ROOT / edition_path / name).exists() for name in ("acceptance.json", "master.tei.xml"))):
        raise ValueError(f"NPNF207 {work_id} acquired edition differs")
    edition_targets = [item for item in state["targets"] if item["target_type"] == "edition"
                       and item["target_id"] == identity["edition_id"]]
    if len(edition_targets) != 1 or edition_targets[0]["stage"] != "acquired":
        raise ValueError(f"NPNF207 {work_id} edition is not uniquely acquired")
    stage.mkdir(parents=True)
    for relative, digest in before.items():
        _put(stage, work_path / relative, _read(ROOT / work_path / relative, digest))
    issue = Path("plans/2026-08-31-sample-first-library-verification/issues") / route["issue"]
    dependencies = {SOURCE, manifest_path, VISUAL, issue,
                    Path(manifest.record["converter"]["implementation_path"]),
                    Path(manifest.record["validator"]["implementation_path"])}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    for ref in set(work.get("evidence", [])) | {
        value for target in state["targets"] for value in target.get("evidence", [])
    }:
        relative = Path(ref.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe NPNF207 inherited evidence: {ref}")
        if not relative.is_relative_to(work_path):
            dependencies.add(relative)
    for relative in sorted(dependencies):
        _put(stage, relative, _read(ROOT / relative))
    evidence = work_path / "integration" / (work_id + "-npnf207-selected-v1")
    for name in package.member_names:
        _put(stage, evidence / "inputs/package" / name, package.member_bytes(name))
    _json(stage, evidence / "inputs/validation.json", {
        "status": report.status, "candidate_sha256": package.sha256,
        "source_manifest_sha256": manifest.sha256, "report_sha256": report.sha256,
        "attestation": dict(report.attestation), "findings": list(report.findings)})
    updated_work = json.loads(json.dumps(work))
    updated_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    validate_identity_update(work, updated_work)
    _json(stage, work_path / "work.json", updated_work)
    load_work(_io_path(stage / work_path / "work.json"))
    selected_scope = (f"Complete source-native ThML.body/div1[@id='{route['root_id']}'] "
                      f"({route['root_title']}) only; the enclosing NPNF2-07 header and sibling "
                      "div1 works remain outside this edition's accepted selection.")
    acquired_scope = retained[0]["scope"]
    source_binding = {"source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
                      "source_bytes": SOURCE_BYTES, "source_scope": acquired_scope}
    revision = {"id": work_id + "-npnf207-selected-v1", "date": datetime.now(timezone.utc).date().isoformat(),
                "note": f"Represent only retained NPNF2-07 root {route['root_id']} for {route['root_title']}; anthology and print claims remain separate."}
    original = package.member_bytes("content.tei.xml")
    derived = bind_reviewed_header(original, expected_sha256=sha256(original).hexdigest(),
                                   identity=identity, source=source_binding,
                                   source_url=acquisition["url"], declared_scope=selected_scope,
                                   revision=revision, historical_source_description={
                                       "pointers": [SOURCE.as_posix()], "sha256": [SOURCE_SHA]})
    if derived.count(OLD_STATUS) != 1 or derived.count(b"</sourceDesc>") != 1:
        raise ValueError(f"NPNF207 {work_id} reviewed header changed")
    derived = derived.replace(OLD_STATUS, NEW_STATUS, 1).replace(
        b"</sourceDesc>", CREDIT + b"</sourceDesc>", 1)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError(f"NPNF207 {work_id} selected source text changed")
    candidate_path = _put(stage, evidence / "candidate.tei.xml", derived)
    if errors := validate_file(_io_path(candidate_path)):
        raise ValueError(f"NPNF207 {work_id} P5 errors: {errors[:2]}")
    expected = [{"path": SOURCE.as_posix(), "position": 1}]
    included = [{"path": SOURCE.as_posix(), "position": 1, "bytes": SOURCE_BYTES,
                 "sha256": SOURCE_SHA, "scope": selected_scope}]
    scope = {"kind": "selection", "declared": selected_scope, "expected_members": expected,
             "included_members": included, "excluded_members": []}
    common = {"identity": identity, "source": source_binding,
              "candidate": make_file_binding(stage, candidate_path), "scope": selected_scope,
              "accepted_scope": {"kind": "selection", "declared": selected_scope},
              "expected_members": expected, "included_members": included,
              "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = _json(stage, evidence / "source-accounting.json", common | {
        "scope": acquired_scope, "source_sha256": SOURCE_SHA, "source_bytes": SOURCE_BYTES,
        "source_manifest_sha256": manifest.sha256, "candidate_package_sha256": package.sha256,
        "selected_root_id": route["root_id"], "selected_root_title": route["root_title"],
        "selected_child_ids": profile["selected_child_ids"],
        "selected_tag_counts": profile["selected_tag_counts"], "unsupported_elements": 0,
        "basis": "Current independent source oracle; complete named subtree, exact sibling exclusion, byte-identical TEI text, P5 and one accepted native prose row."})
    command = "py -3 -m build.tools.stage_npnf207_two_work_ccel_acceptance --stage-root <fresh-external-root>"
    technical = {"producer": {"id": manifest.record["converter"]["id"]},
                 "checker": {"id": manifest.record["validator"]["id"]},
                 "shared_assumptions": ["Producer and oracle inspect the same retained NPNF2-07 XML file."],
                 "independent_corroboration": "Current per-work source oracle, P5, unchanged selected text, stock native projection, and prior bounded NPNF207 source/TEI visual review."}
    for label in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _json(stage, evidence / (label + ".json"), common | {
            "status": "pass", "command": command, "exit_code": 0, "claim": label,
            "candidate_package_sha256": package.sha256,
            "source_manifest_sha256": manifest.sha256, "oracle_report_sha256": report.sha256,
            "accepted_header_body_unchanged": True})
        technical[label] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    reviewed_at = _now()
    loci = [f"{SOURCE.as_posix()}#{value}" for value in route["loci"]]
    review = {"reviewer": "agent:npnf207-selected-work-stage", "reviewed_at": reviewed_at,
              "coverage": {"status": "partial", "declared": selected_scope,
                           "reached": loci, "inspected": loci,
                           "unreviewed": [f"{SOURCE.as_posix()}#{route['root_id']}-complete-visual-proofreading"]},
              "source_quality_uncertainty": ["Prior bounded native views were inspected; complete text proofreading and print collation were not performed."],
              "discrepancies": [],
              "unreviewed_residuals": ["Full visual/human review, work-level contributor allocation, rights and publication remain unresolved."]}
    review_file = _json(stage, evidence / "review.json", common | review | {
        "prior_bounded_visual_evidence": VISUAL.as_posix(),
        "selected_root_id": route["root_id"], "selected_source_loci": list(route["loci"])})
    decision = {"source_local_disposition": f"Agent technical acceptance of only the complete retained NPNF2-07 div1 {route['root_id']} subtree for {work_id}; sibling anthology material excluded.",
                "blockers": [], "human_decision": {"status": "not-recorded"},
                "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                                     "assessed_at": reviewed_at, "supported_scope": selected_scope,
                                     "unresolved_claims": [], "unassessed_stronger_claims": [
                                         "sibling anthology material", "print edition and contributor allocation",
                                         "complete proofreading", "human review", "rights clearance", "publication"]}}
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
    target = next(item for item in state["targets"] if item["target_type"] == "edition"
                  and item["target_id"] == identity["edition_id"])
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
        raise ValueError(f"NPNF207 {work_id} accepted native projection differs: {errors[:2]}")
    after = _files(stage / work_path)
    dependencies_map = {key: value for key, value in _files(stage).items()
                        if not key.startswith(work_path.as_posix() + "/") and key != "stage-receipt.json"}
    receipt = {"contract": CONTRACT, "status": "staged-only", "installation": "not-performed",
               "rights": "not-assessed", "canonical_root": ROOT.as_posix(),
               "stage_root": stage.as_posix(), "dependencies": dependencies_map,
               "work": {"work_id": work_id, "work_path": work_path.as_posix(),
                        "before": before, "after": after, "source_path": SOURCE.as_posix(),
                        "source_sha256": SOURCE_SHA, "source_manifest_sha256": manifest.sha256,
                        "candidate_package_sha256": package.sha256,
                        "selected_root_id": route["root_id"],
                        "new_master_sha256": sha256(derived).hexdigest(),
                        "new_acceptance_sha256": sha256(_read(acceptance_path)).hexdigest(),
                        "native_rows": 1}}
    _json(stage, Path("stage-receipt.json"), receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-root", required=True, type=Path)
    args = parser.parse_args()
    stage_root = args.stage_root.absolute()
    if stage_root.exists() or not stage_root.parent.is_dir():
        raise ValueError("NPNF207 batch requires a fresh external parent")
    stage_root.mkdir()
    output = {}
    for work_id in ROUTES:
        receipt = prepare(work_id, stage_root / work_id)
        output[work_id] = {"before": len(receipt["work"]["before"]),
                           "after": len(receipt["work"]["after"]),
                           "master_sha256": receipt["work"]["new_master_sha256"]}
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
