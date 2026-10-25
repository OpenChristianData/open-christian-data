"""Stage one complete bsb830 York native part externally."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

from build.tei.openmgh_bsb830_york_oracle import _oracle
from build.tools import prepare_openmgh_bsb830_york as parts
from ocd_kernel.library.acquisitions import validate_acquisition
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


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = "openmgh-bsb830-york-electronic-v1"
CONTRACT = "ocd-openmgh-bsb830-york-acceptance-stage-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _put(root: Path, relative: Path, content: bytes) -> Path:
    target = root / relative
    Path(_io_path(target.parent)).mkdir(parents=True, exist_ok=True)
    Path(_io_path(target)).write_bytes(content)
    return target


def _put_json(root: Path, relative: Path, value: object) -> Path:
    return _put(root, relative, parts._json(value))


def _copy(root: Path, stage: Path, relative: Path) -> None:
    source = Path(_io_path(root / relative))
    target = Path(_io_path(stage / relative))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_work(root: Path, stage: Path, work: Path) -> dict[str, str]:
    before = _files(root / work)
    if not before:
        raise ValueError("empty canonical work generation")
    for relative in before:
        _copy(root, stage, work / relative)
    if _files(stage / work) != before:
        raise ValueError("work copy differs from canonical preimage")
    return before


def _bind_stage_manifest(stage: Path, manifest_rel: Path, profile_rel: Path,
                         work_rel: Path, acquisition_rel: Path) -> SourceManifest:
    profile = _read(stage / profile_rel)
    profile["acquisition_sha256"] = _sha(stage / acquisition_rel)
    _put_json(stage, profile_rel, profile)
    manifest = _read(stage / manifest_rel)
    for authority in manifest["authorities"]:
        if authority["path"] in {profile_rel.as_posix(), (work_rel / "work.json").as_posix()}:
            target = stage / authority["path"]
            authority["bytes"] = Path(_io_path(target)).stat().st_size
            authority["sha256"] = _sha(target)
    _put_json(stage, manifest_rel, manifest)
    return SourceManifest.load(stage / manifest_rel, repository_root=stage)


def prepare(root: Path, package_receipt: Path, work_id: str,
            stage: Path, receipt: Path) -> dict:
    root = root.resolve(strict=True)
    package_receipt = package_receipt.resolve(strict=True)
    stage = stage.absolute()
    receipt = receipt.absolute()
    if (Path(_io_path(stage)).exists() or Path(_io_path(receipt)).exists()
            or root == stage or root in stage.parents):
        raise ValueError("fresh external stage and receipt are required")
    if not Path(_io_path(stage.parent)).is_dir() or not Path(_io_path(receipt.parent)).is_dir():
        raise ValueError("stage/receipt parent is absent")
    packages = _read(package_receipt)
    if (packages.get("contract") != "ocd-openmgh-bsb830-york-packages-v1"
            or packages.get("source_sha256") != parts.SOURCE_SHA
            or packages.get("frozen_batch_path") != parts.BATCH.as_posix()
            or packages.get("frozen_batch_sha256") != parts.BATCH_SHA
            or len(packages.get("works", [])) != 2):
        raise ValueError("parts package receipt changed")
    matches = [item for item in packages["works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise ValueError("work outside exact parts package receipt")
    item = matches[0]
    work = Path("library/works") / work_id
    manifest_rel = Path(item["manifest_path"])
    profile_rel = Path(item["profile_path"])
    boundary_rel = Path(item["boundary_path"])
    acquisition_rel = Path(item["acquisition_path"])
    if (not manifest_rel.is_relative_to(parts.SIDE_HOME / work_id)
            or not profile_rel.is_relative_to(parts.SIDE_HOME / work_id)
            or not boundary_rel.is_relative_to(parts.SIDE_HOME / work_id)
            or not acquisition_rel.is_relative_to(work)):
        raise ValueError("work-local source or acquisition path differs")
    original_manifest = SourceManifest.load(root / manifest_rel, repository_root=root)
    package_root = Path(item["package_root"])
    original_package = CandidatePackage.load(package_root / "package")
    if (_sha(root / manifest_rel) != item["manifest_sha256"]
            or _sha(root / profile_rel) != item["profile_sha256"]
            or _sha(root / boundary_rel) != item["boundary_sha256"]
            or _sha(root / acquisition_rel) != item["acquisition_sha256"]
            or _sha(root / work / "work.json") != item["work_sidecar_sha256"]
            or original_package.sha256 != item["package_sha256"]
            or _sha(package_root / "validation.json") != item["validation_sha256"]
            or _sha(package_root / "package/content.tei.xml") != item["candidate_tei_sha256"]):
        raise ValueError("source, sidecar, candidate, or validation preimage changed")
    result = validate(original_manifest, original_package, _oracle)
    prior_validation = _read(package_root / "validation.json")
    if (result.status != "pass" or result.findings
            or result.sha256 != prior_validation["report_sha256"]):
        raise ValueError("current independent oracle differs from package receipt")
    boundary = _read(root / boundary_rel)
    category = item["category"]
    if category != "prose" or item["language"] != "la":
        raise ValueError("unsupported part category or language")
    edition = (work / "forms" / f"{work_id}-openmgh-retained" / "editions"
               / f"{work_id}-openmgh-electronic")
    acceptance_rel = edition / "acceptance.json"
    master_rel = edition / "master.tei.xml"
    if Path(_io_path(root / acceptance_rel)).exists() or Path(_io_path(root / master_rel)).exists():
        raise ValueError("work already has an accepted master")
    before = _copy_work(root, stage, work)
    manifest = _read(root / manifest_rel)
    dependencies = {parts.SOURCE, parts.RECEIPT, parts.BATCH, manifest_rel,
                    profile_rel, boundary_rel,
                    Path("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"),
                    Path("ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd")}
    dependencies.update(Path(authority["path"]) for authority in manifest["authorities"])
    dependencies.update(Path(manifest[key]["implementation_path"])
                        for key in ("converter", "validator"))
    dependencies.add(Path(manifest["package_schema"]["path"]))
    policy = _read(root / parts.SIDE_HOME / "validation-policy.json")
    dependencies.update(Path(path) for path in policy["closure_inputs"])
    acquisition = _read(root / acquisition_rel)
    dependencies.update(Path(file["path"]) for file in acquisition["retained_files"])
    for relative in sorted(dependencies):
        if not relative.is_relative_to(work):
            _copy(root, stage, relative)
    work_record = _read(stage / work / "work.json")
    old_work = _read(root / work / "work.json")
    form = work_record["textual_forms"][0]
    edition_record = form["editions"][0]
    if edition_record["edition_id"] != edition.name or "category" in edition_record or "language" in edition_record:
        raise ValueError("edition category/language preimage changed")
    edition_record["category"] = "prose"
    edition_record["language"] = "la"
    validate_identity_update(old_work, work_record)
    _put_json(stage, work / "work.json", work_record)
    load_work(Path(_io_path(stage / work / "work.json")))
    scope_text = ("The complete native York part in extracted openMGH bsb00000830 "
                  f"source division 22, tractate {boundary['source_part_ordinal']} of 6; "
                  "the shared collection heading and other "
                  "source works remain in the retained XML.")
    acquisition["source_scope"] = scope_text
    acquisition["retained_files"][1]["scope"] = scope_text
    _put_json(stage, acquisition_rel, acquisition)
    validate_acquisition(Path(_io_path(stage / acquisition_rel)), root=Path(_io_path(stage)))
    current_manifest = _bind_stage_manifest(stage, manifest_rel, profile_rel, work,
                                            acquisition_rel)
    current_root = stage.parent / f"{stage.name}-candidate"
    process = subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--manifest",
         manifest_rel.as_posix(), "--destination", str(current_root),
         "--repository-root", str(stage)],
        cwd=root, capture_output=True, text=True, check=True,
    )
    if not process.stdout.strip():
        raise ValueError("fresh candidate command gave no receipt")
    current_package = CandidatePackage.load(current_root / "package")
    current_validation = _read(current_root / "validation.json")
    if (current_validation.get("status") != "pass" or current_validation.get("findings")
            or current_validation.get("source_manifest_sha256") != current_manifest.sha256
            or current_package.member_bytes("content.tei.xml")
            != original_package.member_bytes("content.tei.xml")):
        raise ValueError("current source closure or reproduced candidate differs")
    evidence = work / "integration" / EVIDENCE
    for name in current_package.member_names:
        _put(stage, evidence / "inputs/current/package" / name,
             current_package.member_bytes(name))
    _put(stage, evidence / "inputs/current/validation.json",
         Path(_io_path(current_root / "validation.json")).read_bytes())
    for name in original_package.member_names:
        _put(stage, evidence / "inputs/original/package" / name,
             original_package.member_bytes(name))
    _put(stage, evidence / "inputs/original/validation.json",
         Path(_io_path(package_root / "validation.json")).read_bytes())
    identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"],
                "edition_id": edition_record["edition_id"],
                "acquisition_id": edition_record["acquisition_ids"][0]}
    revision = {"id": f"{work_id}-bsb830-york-electronic-v1",
                "date": datetime.now(timezone.utc).date().isoformat(),
                "note": "Accept the exact complete native tractate of the retained electronic witness."}
    source_binding = {"source_path": parts.SOURCE.as_posix(),
                      "source_sha256": parts.SOURCE_SHA,
                      "source_bytes": Path(_io_path(root / parts.SOURCE)).stat().st_size,
                      "source_scope": scope_text}
    original = current_package.member_bytes("content.tei.xml")
    derived = bind_reviewed_header(
        original, expected_sha256=sha256(original).hexdigest(), identity=identity,
        source=source_binding, source_url=acquisition["url"],
        declared_scope=scope_text, revision=revision,
    )
    if derived.split(b"</teiHeader>", 1)[1] != original.split(b"</teiHeader>", 1)[1]:
        raise ValueError("accepted header binding changed candidate body")
    candidate_rel = evidence / "candidate.tei.xml"
    candidate = _put(stage, candidate_rel, derived)
    if errors := validate_file(Path(_io_path(candidate))):
        raise ValueError(f"accepted TEI XSD failed: {errors[:3]}")
    included = [{"path": parts.SOURCE.as_posix(), "position": 2,
                 "bytes": source_binding["source_bytes"], "sha256": parts.SOURCE_SHA,
                 "scope": scope_text}]
    excluded = [{"path": acquisition["retained_files"][0]["path"], "position": 1,
                 "reason": "Retained ZIP download package only; extracted XML is text authority."}]
    expected = [{"path": excluded[0]["path"], "position": 1},
                {"path": parts.SOURCE.as_posix(), "position": 2}]
    scope = {"kind": "selection", "declared": scope_text,
             "expected_members": expected, "included_members": included,
             "excluded_members": excluded}
    common = {"identity": identity, "source": source_binding,
              "candidate": make_file_binding(stage, candidate), "scope": scope_text,
              "accepted_scope": {"kind": "selection", "declared": scope_text},
              "expected_members": expected, "included_members": included,
              "excluded_members": excluded, "missing_members": [], "unknown_members": []}
    accounting_rel = evidence / "source-accounting.json"
    accounting = _put_json(stage, accounting_rel, common | {
        "source_sha256": parts.SOURCE_SHA,
        "source_bytes": source_binding["source_bytes"],
        "source_part_ordinal": boundary["source_part_ordinal"],
        "catalog_start_xml_id": boundary["catalog_start_xml_id"],
        "catalog_end_xml_id": boundary["catalog_end_xml_id"],
        "selection_c14n_sha256": boundary["selection_c14n_sha256"],
        "source_manifest_sha256": current_manifest.sha256,
        "candidate_package_sha256": current_package.sha256,
        "oracle_report_sha256": current_validation["report_sha256"],
        "shared_matter_disposition": boundary["shared_matter_disposition"],
        "unassigned_fragment_disposition": boundary["unassigned_fragment_disposition"],
    })
    proof_command = "py -3 -m build.tools.stage_openmgh_bsb830_york_acceptance"
    technical = {
        "producer": {"id": current_manifest.record["converter"]["id"]},
        "checker": {"id": current_manifest.record["validator"]["id"]},
        "shared_assumptions": ["Producer and oracle share pinned locator identities; independent source container, group-heading, and part-count checks constrain them."],
        "independent_corroboration": "The source-tree oracle, native part boundary sidecar, XSD, fresh-process reproduction, and independently checked prose row agree.",
    }
    for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
        proof = _put_json(stage, evidence / f"{name}.json", common | {
            "status": "pass", "command": proof_command, "exit_code": 0,
            "original_package_sha256": original_package.sha256,
            "current_package_sha256": current_package.sha256,
            "current_validation_sha256": _sha(current_root / "validation.json"),
            "source_manifest_sha256": current_manifest.sha256,
            "boundary_sha256": _sha(stage / boundary_rel),
            "candidate_body_unchanged": True,
            "claim": name,
        })
        technical[name] = {"path": proof, "status": "pass",
                           "command": proof_command, "exit_code": 0}
    reviewed_at = _now()
    review = {
        "reviewer": f"agent:{work_id}-bsb830-york-source-review",
        "reviewed_at": reviewed_at,
        "coverage": {"status": "unavailable", "declared": scope_text,
                     "reached": ["retained XML native part container", "exact candidate TEI"],
                     "inspected": ["retained XML native part container/boundaries and sibling headings",
                                   "exact candidate TEI/source-tree oracle comparison"],
                     "unreviewed": ["close visual source/TEI comparison"]},
        "source_quality_uncertainty": ["No print witness was collated."],
        "discrepancies": [],
        "unreviewed_residuals": ["Visual and human review remain unrecorded."],
    }
    review_path = _put_json(stage, evidence / "review.json", common | review)
    decision = {
        "source_local_disposition": "Agent acceptance of this complete native electronic part only.",
        "blockers": [],
        "agent_assessment": {"status": "accepted", "actor": review["reviewer"],
                             "assessed_at": reviewed_at, "supported_scope": scope_text,
                             "unresolved_claims": [],
                             "unassessed_stronger_claims": ["close visual review", "human acceptance",
                                                            "print collation", "rights clearance", "publication"]},
        "human_decision": {"status": "not-recorded"},
    }
    acceptance = build_acceptance_record(
        stage, identity=identity, candidate_path=candidate,
        source_accounting_path=accounting, scope=scope, technical=technical,
        review=review | {"report_path": review_path},
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
    targets = [target for target in state["targets"]
               if target["target_type"] == "edition" and target["target_id"] == edition.name]
    if len(targets) != 1 or targets[0]["stage"] != "acquired":
        raise ValueError("edition state preimage is not uniquely acquired")
    targets[0].update(stage="accepted", reason=PROMOTED_MASTER_REASON, updated_at=_now())
    targets[0]["evidence"].extend([master_rel.as_posix(), acceptance_rel.as_posix()])
    _put_json(stage, work / "state.json", state)
    validated = validate_acceptance(Path(_io_path(stage / acceptance_rel)),
                                    root=Path(_io_path(stage)))
    validate_state(Path(_io_path(stage / work / "state.json")), root=Path(_io_path(stage)))
    projected = project_accepted_prose(Path(_io_path(stage)),
                                       acceptance_path=Path(_io_path(stage / acceptance_rel)))
    errors = verify_accepted_prose(Path(_io_path(stage)),
                                   acceptance_path=Path(_io_path(stage / acceptance_rel)),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise ValueError(f"actual-master native prose projection failed: {errors[:3]}")
    result = {
        "contract": CONTRACT, "status": "staged-only", "work_id": work_id,
        "canonical_root": root.as_posix(), "stage_root": stage.as_posix(),
        "package_receipt": package_receipt.as_posix(),
        "package_receipt_sha256": _sha(package_receipt),
        "source_path": parts.SOURCE.as_posix(), "source_sha256": parts.SOURCE_SHA,
        "manifest_path": manifest_rel.as_posix(), "profile_path": profile_rel.as_posix(),
        "source_manifest_before_sha256": item["manifest_sha256"],
        "source_manifest_after_sha256": _sha(stage / manifest_rel),
        "profile_before_sha256": item["profile_sha256"],
        "profile_after_sha256": _sha(stage / profile_rel),
        "before": before, "after": _files(stage / work),
        "accepted_master_sha256": validated["promotion"]["master"]["sha256"],
        "acceptance_sha256": _sha(stage / acceptance_rel),
        "category": "prose", "language": "la", "projection_rows": 1,
        "projection_status": "independent-check-pass", "installation": "not-performed",
    }
    _put_json(receipt.parent, Path(receipt.name), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id")
    parser.add_argument("--package-receipt", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = prepare(args.root, args.package_receipt, args.work_id, args.stage, args.receipt)
    print(json.dumps({"work_id": result["work_id"],
                      "master_sha256": result["accepted_master_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
