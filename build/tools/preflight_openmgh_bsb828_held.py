"""Independently preflight one frozen bsb828 held-work stage; never install."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from build.tools import stage_openmgh_bsb828_held_candidates as held
from build.tools.stage_openmgh_bsb828_held_acceptance import (
    BATCH_SHA, CONTRACT, EVIDENCE, REPRO, REPRO_SHA, STAGE_IDS,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import cached_edition_lookups, load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.projection.categories.poetry import project_accepted_poetry, verify_accepted_poetry
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _staged_oracle(stage: Path, manifest: SourceManifest):
    path = Path(_io_path(stage / manifest.record["validator"]["implementation_path"]))
    spec = importlib.util.spec_from_file_location("ocd_bsb828_held_staged_oracle", path)
    if spec is None or spec.loader is None:
        raise PipelineError("staged held-work oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._oracle


@cached_edition_lookups()
def preflight(receipt: Path) -> dict:
    record = _read(receipt.resolve(strict=True))
    work_id = record.get("work_id")
    if (record.get("contract") != CONTRACT or work_id not in STAGE_IDS
            or record.get("status") != "staged-only"
            or record.get("installation") != "not-performed"
            or record.get("source_path") != held.SOURCE.as_posix()
            or record.get("source_sha256") != held.SOURCE_SHA
            or record.get("category") not in {"prose", "poetry"}
            or record.get("language") != "la"
            or record.get("projection_rows") != 1
            or record.get("projection_status") != "independent-check-pass"):
        raise PipelineError("unrecognized held-work stage receipt")
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("stage overlaps canonical root")
    work = Path("library/works") / work_id
    home = held.HOME / work_id
    manifest_rel = home / "source-manifest.json"
    profile_rel = home / "reconstruction-profile.json"
    boundary_rel = home / "boundary-review.json"
    if (record["manifest_path"] != manifest_rel.as_posix()
            or record["profile_path"] != profile_rel.as_posix()
            or _files(root / work) != record["before"]
            or _files(stage / work) != record["after"]):
        raise PipelineError("work identity or generation changed")
    if (_sha(root / held.SOURCE) != held.SOURCE_SHA
            or _sha(stage / held.SOURCE) != held.SOURCE_SHA
            or _sha(root / held.BATCH) != BATCH_SHA
            or _sha(stage / held.BATCH) != BATCH_SHA
            or _sha(root / REPRO) != REPRO_SHA
            or _sha(stage / REPRO) != REPRO_SHA
            or _sha(root / manifest_rel) != record["source_manifest_before_sha256"]
            or _sha(stage / manifest_rel) != record["source_manifest_after_sha256"]
            or _sha(root / profile_rel) != record["profile_before_sha256"]
            or _sha(stage / profile_rel) != record["profile_after_sha256"]
            or _sha(root / boundary_rel) != _sha(stage / boundary_rel)):
        raise PipelineError("source, frozen batch, or sidecar changed")
    package_receipt = Path(record["package_receipt"]).resolve(strict=True)
    if _sha(package_receipt) != record["package_receipt_sha256"] or _sha(package_receipt) != BATCH_SHA:
        raise PipelineError("candidate batch receipt changed")
    batch = _read(package_receipt)
    if (batch.get("contract") != "ocd-openmgh-bsb828-held-candidate-batch-v1"
            or batch.get("source_sha256") != held.SOURCE_SHA
            or batch.get("identity_count") != 8 or len(batch.get("works", [])) != 8):
        raise PipelineError("candidate batch identity changed")
    matches = [item for item in batch["works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise PipelineError("work absent from exact candidate batch")
    item = matches[0]
    if (item["manifest_path"] != manifest_rel.as_posix()
            or item["profile_path"] != profile_rel.as_posix()
            or item["boundary_review_path"] != boundary_rel.as_posix()
            or item["manifest_sha256"] != record["source_manifest_before_sha256"]
            or item["profile_sha256"] != record["profile_before_sha256"]
            or item["boundary_review_sha256"] != _sha(root / boundary_rel)):
        raise PipelineError("candidate-to-stage closure changed")
    acquisition_rel = Path(item["acquisition_path"])
    if not acquisition_rel.is_relative_to(work) or _sha(root / acquisition_rel) != item["acquisition_sha256"]:
        raise PipelineError("original work acquisition changed")
    original_manifest = SourceManifest.load(root / manifest_rel, repository_root=root)
    staged_manifest = SourceManifest.load(stage / manifest_rel, repository_root=stage)
    original_root = Path(item["candidate_root"])
    original = CandidatePackage.load(original_root / "package")
    original_validation = _read(original_root / "validation.json")
    if (original.sha256 != item["candidate_sha256"]
            or _sha(original_root / "package/content.tei.xml") != item["candidate_tei_sha256"]
            or _sha(original_root / "validation.json") != item["validation_sha256"]):
        raise PipelineError("original candidate changed")
    oracle = validate(original_manifest, original, _staged_oracle(root, original_manifest))
    if oracle.status != "pass" or oracle.findings or oracle.sha256 != original_validation["report_sha256"]:
        raise PipelineError("original source oracle changed")
    integration = work / "integration" / EVIDENCE
    current = CandidatePackage.load(Path(_io_path(stage / integration / "inputs/current/package")))
    current_validation = _read(stage / integration / "inputs/current/validation.json")
    staged_oracle = validate(staged_manifest, current, _staged_oracle(stage, staged_manifest))
    if (staged_oracle.status != "pass" or staged_oracle.findings
            or staged_oracle.sha256 != current_validation["report_sha256"]
            or current_validation["source_manifest_sha256"] != staged_manifest.sha256
            or current.member_bytes("content.tei.xml") != original.member_bytes("content.tei.xml")):
        raise PipelineError("staged candidate or independent oracle changed")
    if (_read(stage / profile_rel)["acquisition_sha256"] != _sha(stage / acquisition_rel)
            or _read(stage / acquisition_rel)["source_sha256"] != held.SOURCE_SHA):
        raise PipelineError("staged acquisition binding changed")
    validate_acquisition(Path(_io_path(stage / acquisition_rel)), root=Path(_io_path(stage)))
    load_work(Path(_io_path(stage / work / "work.json")))
    edition = acquisition_rel.parent.parent
    acceptance_rel = edition / "acceptance.json"
    master_rel = edition / "master.tei.xml"
    accepted = validate_acceptance(Path(_io_path(stage / acceptance_rel)), root=Path(_io_path(stage)))
    validate_state(Path(_io_path(stage / work / "state.json")), root=Path(_io_path(stage)))
    if (_sha(stage / acceptance_rel) != record["acceptance_sha256"]
            or accepted["identity"]["work_id"] != work_id
            or accepted["promotion"]["master"]["sha256"] != record["accepted_master_sha256"]
            or _sha(stage / master_rel) != record["accepted_master_sha256"]
            or Path(_io_path(stage / master_rel)).read_bytes().split(b"</teiHeader>", 1)[1]
               != original.member_bytes("content.tei.xml").split(b"</teiHeader>", 1)[1]):
        raise PipelineError("accepted master or source body changed")
    if record["category"] == "poetry":
        project, verify = project_accepted_poetry, verify_accepted_poetry
    else:
        project, verify = project_accepted_prose, verify_accepted_prose
    projected = project(Path(_io_path(stage)), acceptance_path=Path(_io_path(stage / acceptance_rel)))
    errors = verify(Path(_io_path(stage)), acceptance_path=Path(_io_path(stage / acceptance_rel)),
                    rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"actual-master projection changed: {errors[:3]}")
    return {"status": "ready-for-review", "work_id": work_id,
            "before_files": len(record["before"]), "after_files": len(record["after"]),
            "projection_rows": 1, "installation": "not-performed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    print(json.dumps(preflight(args.receipt), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
