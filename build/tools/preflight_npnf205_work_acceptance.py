"""Independently preflight one exact NPNF205 work stage; never install."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from build.tools import prepare_npnf205_work_candidates as family
from build.tools.stage_npnf205_work_acceptance import BATCH, BATCH_SHA, CONTRACT, EVIDENCE
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import cached_edition_lookups, load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
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


def _oracle(root: Path, manifest: SourceManifest):
    path = Path(_io_path(root / manifest.record["validator"]["implementation_path"]))
    spec = importlib.util.spec_from_file_location("ocd_npnf205_work_staged_oracle", path)
    if spec is None or spec.loader is None:
        raise PipelineError("NPNF205 work oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._oracle


@cached_edition_lookups()
def preflight(receipt: Path) -> dict:
    record = _read(receipt.resolve(strict=True))
    work_id = record.get("work_id")
    if (record.get("contract") != CONTRACT or record.get("status") != "staged-only"
            or record.get("installation") != "not-performed"
            or record.get("source_path") != family.SOURCE.as_posix()
            or record.get("source_sha256") != family.SOURCE_SHA
            or record.get("category") != "prose" or record.get("language") != "en"
            or record.get("projection_rows") != 1
            or record.get("projection_status") != "independent-check-pass"):
        raise PipelineError("unrecognized NPNF205 work stage receipt")
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("stage overlaps canonical root")
    work = Path("library/works") / work_id
    manifest_rel = Path(record["manifest_path"])
    profile_rel = Path(record["profile_path"])
    if (manifest_rel != family.HOME / work_id / "source-manifest.json"
            or profile_rel != family.HOME / work_id / "reconstruction-profile.json"
            or _files(root / work) != record["before"]
            or _files(stage / work) != record["after"]):
        raise PipelineError("NPNF205 work generation or source sidecar path changed")
    if (_sha(root / family.SOURCE) != family.SOURCE_SHA
            or _sha(stage / family.SOURCE) != family.SOURCE_SHA
            or _sha(root / family.PLAN) != _sha(stage / family.PLAN)
            or _sha(root / family.POLICY) != _sha(stage / family.POLICY)
            or _sha(root / manifest_rel) != record["source_manifest_before_sha256"]
            or _sha(stage / manifest_rel) != record["source_manifest_after_sha256"]
            or _sha(root / profile_rel) != record["profile_before_sha256"]
            or _sha(stage / profile_rel) != record["profile_after_sha256"]):
        raise PipelineError("retained source, batch, or work profile changed")
    batch_path = Path(record["package_receipt"]).resolve(strict=True)
    if (batch_path != BATCH.resolve(strict=True) or _sha(batch_path) != BATCH_SHA
            or record["package_receipt_sha256"] != BATCH_SHA):
        raise PipelineError("exact NPNF205 candidate receipt changed")
    batch = _read(batch_path)
    if (batch.get("contract") != "ocd-npnf205-fourteen-work-candidates-v1"
            or batch.get("status") != "validated-nonaccepted"
            or batch.get("work_count") != 14 or len(batch.get("works", [])) != 14
            or batch.get("source_path") != family.SOURCE.as_posix()
            or batch.get("source_sha256") != family.SOURCE_SHA
            or batch.get("selection_plan_path") != family.PLAN.as_posix()
            or batch.get("selection_plan_sha256") != _sha(root / family.PLAN)):
        raise PipelineError("NPNF205 candidate set changed")
    matches = [item for item in batch["works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise PipelineError("work outside exact NPNF205 candidate set")
    item = matches[0]
    if (item["manifest_path"] != manifest_rel.as_posix()
            or item["profile_path"] != profile_rel.as_posix()
            or item["manifest_sha256"] != record["source_manifest_before_sha256"]
            or item["profile_sha256"] != record["profile_before_sha256"]):
        raise PipelineError("NPNF205 package-to-stage source closure changed")
    acquisition_rel = Path(item["acquisition_path"])
    if not acquisition_rel.is_relative_to(work) or _sha(root / acquisition_rel) != item["acquisition_sha256"]:
        raise PipelineError("original work acquisition changed")
    original_manifest = SourceManifest.load(root / manifest_rel, repository_root=root)
    staged_manifest = SourceManifest.load(stage / manifest_rel, repository_root=stage)
    original_root = Path(item["candidate_root"])
    original = CandidatePackage.load(Path(_io_path(original_root / "package")))
    original_validation = _read(original_root / "validation.json")
    if (original.sha256 != item["candidate_sha256"]
            or _sha(original_root / "package/content.tei.xml") != item["candidate_tei_sha256"]
            or _sha(original_root / "validation.json") != item["validation_sha256"]):
        raise PipelineError("original NPNF205 work candidate changed")
    checked_original = validate(original_manifest, original, _oracle(root, original_manifest))
    if (checked_original.status != "pass" or checked_original.findings
            or checked_original.sha256 != original_validation["report_sha256"]):
        raise PipelineError("original NPNF205 source oracle changed")
    evidence = work / EVIDENCE
    current = CandidatePackage.load(Path(_io_path(stage / evidence / "inputs/current/package")))
    current_validation = _read(stage / evidence / "inputs/current/validation.json")
    checked_current = validate(staged_manifest, current, _oracle(stage, staged_manifest))
    if (checked_current.status != "pass" or checked_current.findings
            or checked_current.sha256 != current_validation["report_sha256"]
            or current_validation["source_manifest_sha256"] != staged_manifest.sha256
            or current.member_bytes("content.tei.xml") != original.member_bytes("content.tei.xml")):
        raise PipelineError("staged NPNF205 source oracle or candidate changed")
    profile = _read(stage / profile_rel)
    if (profile["work_sha256"] != _sha(stage / work / "work.json")
            or profile["acquisition_sha256"] != _sha(stage / acquisition_rel)
            or _read(stage / acquisition_rel)["source_sha256"] != family.SOURCE_SHA):
        raise PipelineError("staged work/acquisition profile binding changed")
    validate_acquisition(Path(_io_path(stage / acquisition_rel)), root=Path(_io_path(stage)))
    load_work(Path(_io_path(stage / work / "work.json")))
    edition = acquisition_rel.parent.parent
    acceptance_rel, master_rel = edition / "acceptance.json", edition / "master.tei.xml"
    accepted = validate_acceptance(Path(_io_path(stage / acceptance_rel)), root=Path(_io_path(stage)))
    validate_state(Path(_io_path(stage / work / "state.json")), root=Path(_io_path(stage)))
    if (_sha(stage / acceptance_rel) != record["acceptance_sha256"]
            or accepted["identity"]["work_id"] != work_id
            or accepted["promotion"]["master"]["sha256"] != record["accepted_master_sha256"]
            or _sha(stage / master_rel) != record["accepted_master_sha256"]
            or Path(_io_path(stage / master_rel)).read_bytes().split(b"</teiHeader>", 1)[1]
               != original.member_bytes("content.tei.xml").split(b"</teiHeader>", 1)[1]):
        raise PipelineError("accepted NPNF205 master or source body changed")
    projected = project_accepted_prose(Path(_io_path(stage)),
                                       acceptance_path=Path(_io_path(stage / acceptance_rel)))
    errors = verify_accepted_prose(Path(_io_path(stage)),
                                   acceptance_path=Path(_io_path(stage / acceptance_rel)),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"NPNF205 actual-master projection changed: {errors[:3]}")
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
