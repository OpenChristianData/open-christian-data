"""Stage one exact NPNF113 child electronic work outside the canonical library."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from build.tools import prepare_npnf113_work_candidates as family
from ocd_kernel.library.acquisitions import validate_acquisition
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
CONTRACT = "ocd-npnf113-work-acceptance-stage-v1"
EVIDENCE = "integration/npnf113-source-div2-electronic-v1"
BATCH = Path(r"D:\Library\Open Christian Data\candidate-reviews\npnf113-ten-work-candidates-20260927\receipt.json")
BATCH_SHA = "4658960ecf0c53d66509240914da9add7241eab117086ff545c2113c10fd1297"


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _put(stage: Path, relative: Path, data: bytes) -> Path:
    target = Path(_io_path(stage / relative))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return stage / relative


def _put_json(stage: Path, relative: Path, value: object) -> Path:
    return _put(stage, relative, _canonical(value))


def _copy(stage: Path, relative: Path) -> None:
    _put(stage, relative, Path(_io_path(ROOT / relative)).read_bytes())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def prepare(work_id: str, stage: Path, receipt: Path) -> dict:
    stage, receipt = stage.absolute(), receipt.absolute()
    if (Path(_io_path(stage)).exists() or Path(_io_path(receipt)).exists()
            or ROOT == stage or ROOT in stage.parents
            or not Path(_io_path(stage.parent)).is_dir()
            or not Path(_io_path(receipt.parent)).is_dir()):
        raise ValueError("fresh external stage and receipt required")
    batch_path = BATCH
    if _sha(batch_path) != BATCH_SHA:
        raise ValueError("ten-work candidate receipt changed")
    batch = _read(batch_path)
    if (batch.get("contract") != "ocd-npnf113-ten-work-candidates-v1"
            or batch.get("status") != "validated-nonaccepted"
            or batch.get("work_count") != 10 or len(batch.get("works", [])) != 10
            or batch.get("source_path") != family.SOURCE.as_posix()
            or batch.get("source_sha256") != family.SOURCE_SHA
            or batch.get("aggregate_tei_sha256") != family.AGGREGATE_TEI_SHA):
        raise ValueError("ten-work candidate batch changed")
    matches = [item for item in batch["works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise ValueError("work outside exact NPNF113 set")
    item = matches[0]
    work = Path("library/works") / work_id
    manifest_rel = Path(item["manifest_path"])
    profile_rel = Path(item["binding_path"])
    profile = _read(ROOT / profile_rel)
    acquisition_rel = Path(profile["acquisition_path"])
    SourceManifest.load(ROOT / manifest_rel, repository_root=ROOT)
    package_root = Path(item["candidate_root"])
    original_package = CandidatePackage.load(Path(_io_path(package_root / "package")))
    if (_sha(ROOT / manifest_rel) != item["manifest_sha256"]
            or _sha(ROOT / profile_rel) != item["binding_sha256"]
            or _sha(ROOT / acquisition_rel) != profile["acquisition_sha256"]
            or original_package.sha256 != item["candidate_sha256"]
            or _sha(package_root / "validation.json") != item["validation_sha256"]
            or _sha(package_root / "package/content.tei.xml") != item["candidate_tei_sha256"]):
        raise ValueError("work-local source or original candidate changed")
    old_work = _read(ROOT / work / "work.json")
    forms = [(form, edition) for form in old_work["textual_forms"] for edition in form["editions"]
             if edition["edition_id"] == profile["edition_id"]]
    if len(forms) != 1:
        raise ValueError("work edition identity is not unique")
    old_form, old_edition = forms[0]
    edition_rel = work / "forms" / old_form["textual_form_id"] / "editions" / old_edition["edition_id"]
    acceptance_rel, master_rel = edition_rel / "acceptance.json", edition_rel / "master.tei.xml"
    if Path(_io_path(ROOT / acceptance_rel)).exists() or Path(_io_path(ROOT / master_rel)).exists():
        raise ValueError("canonical work already accepted")
    before = _files(ROOT / work)
    if not before:
        raise ValueError("canonical work generation empty")
    for relative in before:
        _copy(stage, work / relative)
    if _files(stage / work) != before:
        raise ValueError("staged original work differs")
    dependencies = {family.SOURCE, family.AGGREGATE_MANIFEST, family.AGGREGATE_PROFILE,
                    family.POLICY, manifest_rel, profile_rel,
                    Path("build/tei/npnf113_work_reconstruction.py"),
                    Path("build/tei/npnf113_work_oracle.py"),
                    Path("build/tei/npnf113_lib041_reconstruction.py"),
                    Path("build/tei/npnf113_lib041_oracle.py"),
                    Path("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"),
                    Path("ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd")}
    manifest_record = _read(ROOT / manifest_rel)
    dependencies.add(Path(manifest_record["converter"]["implementation_path"]))
    dependencies.add(Path(manifest_record["validator"]["implementation_path"]))
    dependencies.update(Path(authority["path"]) for authority in manifest_record["authorities"])
    aggregate_manifest_record = _read(ROOT / family.AGGREGATE_MANIFEST)
    dependencies.add(Path(aggregate_manifest_record["converter"]["implementation_path"]))
    dependencies.add(Path(aggregate_manifest_record["validator"]["implementation_path"]))
    dependencies.update(Path(authority["path"]) for authority in aggregate_manifest_record["authorities"])
    dependencies.add(Path(manifest_record["package_schema"]["path"]))
    for ref in set(old_work.get("evidence", [])) | {
        ref for target in _read(ROOT / work / "state.json")["targets"] for ref in target.get("evidence", [])
    }:
        relative = Path(ref.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe inherited evidence: {ref}")
        dependencies.add(relative)
    for relative in sorted(dependencies):
        if not relative.is_relative_to(work):
            _copy(stage, relative)
    work_record = _read(stage / work / "work.json")
    edition_record = next(edition for form in work_record["textual_forms"] for edition in form["editions"]
                          if edition["edition_id"] == old_edition["edition_id"])
    if edition_record.get("category") is not None or edition_record.get("language") != "en":
        raise ValueError("work prose/language preimage changed")
    edition_record["category"] = "prose"
    validate_identity_update(old_work, work_record)
    _put_json(stage, work / "work.json", work_record)
    load_work(Path(_io_path(stage / work / "work.json")))
    profile = _read(stage / profile_rel)
    scope = profile["source_root_id"]
    scope_text = (f"Complete NPNF113 div2 {scope}, {profile['source_title']}; "
                  f"shared title and preface {', '.join(profile['shared_apparatus_ids'])} remain in the retained XML and are separately hash-accounted.")
    acquisition = _read(stage / acquisition_rel)
    if len(acquisition["retained_files"]) != 1:
        raise ValueError("one retained NPNF113 XML source expected")
    acquisition["source_scope"] = scope_text
    acquisition["retained_files"][0]["scope"] = scope_text
    _put_json(stage, acquisition_rel, acquisition)
    validate_acquisition(Path(_io_path(stage / acquisition_rel)), root=Path(_io_path(stage)))
    profile["work_sha256"] = _sha(stage / work / "work.json")
    profile["acquisition_sha256"] = _sha(stage / acquisition_rel)
    _put_json(stage, profile_rel, profile)
    staged_manifest_record = _read(stage / manifest_rel)
    for authority in staged_manifest_record["authorities"]:
        if authority["path"] == profile_rel.as_posix():
            authority["bytes"] = Path(_io_path(stage / profile_rel)).stat().st_size
            authority["sha256"] = _sha(stage / profile_rel)
    _put_json(stage, manifest_rel, staged_manifest_record)
    current_manifest = SourceManifest.load(stage / manifest_rel, repository_root=stage)
    current_root = stage.parent / f"{stage.name}-candidate"
    process = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--manifest", manifest_rel.as_posix(),
         "--destination", str(current_root), "--repository-root", str(stage)],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    if not process.stdout.strip():
        raise ValueError("staged candidate command had no validation receipt")
    current_package = CandidatePackage.load(Path(_io_path(current_root / "package")))
    current_validation = _read(current_root / "validation.json")
    if (current_validation.get("status") != "pass" or current_validation.get("findings")
            or current_validation.get("source_manifest_sha256") != current_manifest.sha256
            or current_package.member_bytes("content.tei.xml") != original_package.member_bytes("content.tei.xml")):
        raise ValueError("staged candidate differs from source-bound original")
    evidence = work / EVIDENCE
    for label, package, validation_path in (
        ("original", original_package, package_root / "validation.json"),
        ("current", current_package, current_root / "validation.json"),
    ):
        for name in package.member_names:
            _put(stage, evidence / "inputs" / label / "package" / name, package.member_bytes(name))
        _put(stage, evidence / "inputs" / label / "validation.json",
             Path(_io_path(validation_path)).read_bytes())
    identity = {"work_id": work_id, "textual_form_id": old_form["textual_form_id"],
                "edition_id": old_edition["edition_id"], "acquisition_id": profile["acquisition_id"]}
    revision = {"id": f"{work_id}-npnf113-electronic-v1",
                "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Accept only this source-defined electronic work root; shared volume matter remains outside."}
    source_binding = {"source_path": family.SOURCE.as_posix(), "source_sha256": family.SOURCE_SHA,
                      "source_bytes": Path(_io_path(ROOT / family.SOURCE)).stat().st_size,
                      "source_scope": scope_text}
    original = current_package.member_bytes("content.tei.xml")
    derived = bind_reviewed_header(original, expected_sha256=sha256(original).hexdigest(),
                                   identity=identity, source=source_binding,
                                   source_url=acquisition["url"],
                                   declared_scope=scope_text,
                                   revision=revision)
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("accepted header binding changed source body")
    candidate_rel = evidence / "candidate.tei.xml"
    candidate = _put(stage, candidate_rel, derived)
    if errors := validate_file(Path(_io_path(candidate))):
        raise ValueError(f"accepted TEI XSD failed: {errors[:3]}")
    expected = [{"path": family.SOURCE.as_posix(), "position": 1}]
    included = [{"path": family.SOURCE.as_posix(), "position": 1,
                 "bytes": source_binding["source_bytes"], "sha256": family.SOURCE_SHA,
                 "scope": scope_text}]
    scope_record = {"kind": "selection", "declared": scope_text, "expected_members": expected,
                    "included_members": included, "excluded_members": []}
    common = {"identity": identity, "source": source_binding,
              "candidate": make_file_binding(stage, candidate), "scope": scope_text,
              "accepted_scope": {"kind": "selection", "declared": scope_text},
              "expected_members": expected, "included_members": included,
              "excluded_members": [], "missing_members": [], "unknown_members": []}
    accounting = _put_json(stage, evidence / "source-accounting.json", common | {
        "source_sha256": family.SOURCE_SHA,
        "source_bytes": source_binding["source_bytes"],
        "source_root_id": scope, "source_element_count":
        _read(package_root / "package/source-accountability.json")["source_element_count"],
        "source_root_c14n_sha256": profile["source_root_c14n_sha256"],
        "original_candidate_sha256": item["candidate_sha256"],
        "source_manifest_sha256": current_manifest.sha256,
        "candidate_package_sha256": current_package.sha256,
        "oracle_report_sha256": current_validation["report_sha256"],
        "outside_material_disposition": "Shared volume matter and sibling works remain in the acquired XML.",
    })
    command = "py -3 -m build.tools.stage_npnf113_work_acceptance"
    technical = {"producer": {"id": current_manifest.record["converter"]["id"]},
                 "checker": {"id": current_manifest.record["validator"]["id"]},
                 "shared_assumptions": ["The work producer selects from the verified NPNF113 aggregate mapping; the work oracle independently reparses the retained child root and compares its complete readable TEI tree."],
                 "independent_corroboration": "Exact native source-root boundary, work-local source oracle, XSD, and native actual-master projection agree."}
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, evidence / f"{name}.json", common | {
            "status": "pass", "claim": name, "command": command, "exit_code": 0,
            "original_package_sha256": original_package.sha256,
            "current_package_sha256": current_package.sha256,
            "source_manifest_sha256": current_manifest.sha256,
            "candidate_body_unchanged": True,
        })
        technical[name] = {"path": proof, "status": "pass", "command": command, "exit_code": 0}
    at = _now()
    review = {"reviewer": f"agent:{work_id}-npnf113-source-review", "reviewed_at": at,
              "coverage": {"status": "partial", "declared": scope_text,
                           "reached": [f"{family.SOURCE.as_posix()}#{scope}", "exact candidate/source-node comparison"],
                           "inspected": [f"{family.SOURCE.as_posix()}#{scope}", "exact candidate/source-node comparison"],
                           "unreviewed": ["close visual source/TEI comparison"]},
              "source_quality_uncertainty": ["No print witness was collated."],
              "discrepancies": [], "unreviewed_residuals": ["Human and full visual review remain unrecorded."]}
    review_path = _put_json(stage, evidence / "review.json", common | review)
    decision = {"source_local_disposition": "Agent acceptance of this exact retained electronic work root only.",
                "blockers": [], "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                                                    "assessed_at": at, "supported_scope": scope_text,
                                                    "unresolved_claims": [],
                                                    "unassessed_stronger_claims": ["close visual review", "human acceptance",
                                                                                   "print collation", "rights clearance", "publication"]},
                "human_decision": {"status": "not-recorded"}}
    acceptance = build_acceptance_record(
        stage, identity=identity, candidate_path=candidate, source_accounting_path=accounting,
        scope=scope_record, technical=technical, review=review | {"report_path": review_path},
        representation_revision=revision, decision=decision,
    )
    write_acceptance(Path(_io_path(stage / acceptance_rel)), acceptance)
    validate_acceptance(Path(_io_path(stage / acceptance_rel)), root=Path(_io_path(stage)))
    _put(stage, master_rel, derived)
    acceptance["promotion"] = dict(acceptance["promotion"])
    acceptance["promotion"].update(status="promoted", promoted_at=_now(),
                                   master=make_file_binding(stage, stage / master_rel))
    write_acceptance(Path(_io_path(stage / acceptance_rel)), acceptance)
    state = _read(stage / work / "state.json")
    targets = [target for target in state["targets"] if target["target_type"] == "edition"
               and target["target_id"] == old_edition["edition_id"]]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError("edition state preimage is not acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    targets[0]["evidence"].extend([master_rel.as_posix(), acceptance_rel.as_posix()])
    _put_json(stage, work / "state.json", state)
    validated = validate_acceptance(Path(_io_path(stage / acceptance_rel)), root=Path(_io_path(stage)))
    validate_state(Path(_io_path(stage / work / "state.json")), root=Path(_io_path(stage)))
    projected = project_accepted_prose(Path(_io_path(stage)),
                                       acceptance_path=Path(_io_path(stage / acceptance_rel)))
    errors = verify_accepted_prose(Path(_io_path(stage)),
                                   acceptance_path=Path(_io_path(stage / acceptance_rel)),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"native actual-master prose projection failed: {errors[:3]}")
    result = {"contract": CONTRACT, "status": "staged-only", "work_id": work_id,
              "canonical_root": ROOT.as_posix(), "stage_root": stage.as_posix(),
              "package_receipt": batch_path.as_posix(), "package_receipt_sha256": BATCH_SHA,
              "source_path": family.SOURCE.as_posix(), "source_sha256": family.SOURCE_SHA,
              "manifest_path": manifest_rel.as_posix(), "profile_path": profile_rel.as_posix(),
              "source_manifest_before_sha256": item["manifest_sha256"],
              "source_manifest_after_sha256": _sha(stage / manifest_rel),
              "profile_before_sha256": item["binding_sha256"],
              "profile_after_sha256": _sha(stage / profile_rel),
              "before": before, "after": _files(stage / work),
              "accepted_master_sha256": validated["promotion"]["master"]["sha256"],
              "acceptance_sha256": _sha(stage / acceptance_rel),
              "category": "prose", "language": "en", "projection_rows": 1,
              "projection_status": "independent-check-pass", "installation": "not-performed"}
    _put_json(receipt.parent, Path(receipt.name), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id")
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.work_id, args.stage, args.receipt)
    print(json.dumps({"work_id": result["work_id"], "master_sha256": result["accepted_master_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
