"""Independently preflight one exact bsb830 York fourth native part stage."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb830_york_four as parts
from build.tools.stage_openmgh_bsb830_york_four_acceptance import CONTRACT, EVIDENCE
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
    result = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(result, dict):
        raise PipelineError(f"JSON object required: {path}")
    return result


def _staged_oracle(stage: Path, manifest: SourceManifest):
    path = Path(_io_path(stage / manifest.record["validator"]["implementation_path"]))
    spec = importlib.util.spec_from_file_location("ocd_bsb830_york_four_staged_oracle", path)
    if spec is None or spec.loader is None:
        raise PipelineError("staged parts oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._oracle


@cached_edition_lookups()
def preflight(receipt: Path) -> dict:
    record = _read(receipt.resolve(strict=True))
    if (record.get("contract") != CONTRACT or record.get("status") != "staged-only"
            or record.get("installation") != "not-performed"
            or record.get("source_path") != parts.SOURCE.as_posix()
            or record.get("source_sha256") != parts.SOURCE_SHA
            or record.get("category") != "prose" or record.get("language") != "la"
            or record.get("projection_rows") != 1
            or record.get("projection_status") != "independent-check-pass"):
        raise PipelineError("unrecognized native-part stage receipt")
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    if root != parts.ROOT.resolve(strict=True) or record["work_id"] != parts.WORK_ID:
        raise PipelineError("outside exact canonical fourth-tractate authority")
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("stage overlaps canonical root")
    work_id = record["work_id"]
    work = Path("library/works") / work_id
    manifest_rel = parts.SIDE_HOME / work_id / "source-manifest.json"
    profile_rel = parts.SIDE_HOME / work_id / "reconstruction-profile.json"
    boundary_rel = parts.SIDE_HOME / work_id / "boundary-review.json"
    if (record["manifest_path"] != manifest_rel.as_posix()
            or record["profile_path"] != profile_rel.as_posix()
            or _files(root / work) != record["before"]
            or _files(stage / work) != record["after"]):
        raise PipelineError("work identity or generation changed")
    if (_sha(root / parts.SOURCE) != parts.SOURCE_SHA
            or _sha(stage / parts.SOURCE) != parts.SOURCE_SHA
            or _sha(root / parts.BATCH) != parts.BATCH_SHA
            or _sha(stage / parts.BATCH) != parts.BATCH_SHA
            or _sha(root / parts.RECEIPT) != parts.RECEIPT_SHA
            or _sha(stage / parts.RECEIPT) != parts.RECEIPT_SHA
            or _sha(root / manifest_rel) != record["source_manifest_before_sha256"]
            or _sha(stage / manifest_rel) != record["source_manifest_after_sha256"]
            or _sha(root / profile_rel) != record["profile_before_sha256"]
            or _sha(stage / profile_rel) != record["profile_after_sha256"]
            or _sha(root / boundary_rel) != _sha(stage / boundary_rel)):
        raise PipelineError("retained XML, frozen batch, or source sidecar changed")
    package_receipt = Path(record["package_receipt"]).resolve(strict=True)
    if _sha(package_receipt) != record["package_receipt_sha256"]:
        raise PipelineError("parts package receipt changed")
    packages = _read(package_receipt)
    if (packages.get("contract") != "ocd-openmgh-bsb830-york-four-packages-v1"
            or packages.get("source_sha256") != parts.SOURCE_SHA
            or packages.get("frozen_batch_path") != parts.BATCH.as_posix()
            or packages.get("frozen_batch_sha256") != parts.BATCH_SHA
            or len(packages.get("works", [])) != 1):
        raise PipelineError("parts package set changed")
    items = [item for item in packages["works"] if item["work_id"] == work_id]
    if len(items) != 1:
        raise PipelineError("work is outside exact one-part set")
    item = items[0]
    if (item["manifest_path"] != manifest_rel.as_posix()
            or item["profile_path"] != profile_rel.as_posix()
            or item["boundary_path"] != boundary_rel.as_posix()
            or item["manifest_sha256"] != record["source_manifest_before_sha256"]
            or item["profile_sha256"] != record["profile_before_sha256"]
            or item["boundary_sha256"] != _sha(root / boundary_rel)):
        raise PipelineError("package-to-stage work closure changed")
    acquisition_rel = Path(item["acquisition_path"])
    if (not acquisition_rel.is_relative_to(work)
            or item["acquisition_sha256"] != _sha(root / acquisition_rel)):
        raise PipelineError("original work acquisition changed")
    old_work = _read(root / work / "work.json")
    expected_work = json.loads(json.dumps(old_work))
    edition_meta = expected_work["textual_forms"][0]["editions"][0]
    if "category" in edition_meta or "language" in edition_meta:
        raise PipelineError("category/language preimage already changed")
    edition_meta.update(category="prose",language="la")
    if _read(stage / work / "work.json") != expected_work:
        raise PipelineError("stage changes work authority outside exact prose/la additions")
    expected_acquisition = _read(root / acquisition_rel)
    qualification = _read(stage / boundary_rel)["source_breakoff"]
    source_scope = ("The complete native York fourth part in extracted openMGH bsb00000830 "
                   "source division 22, tractate 4 of 6; the shared collection heading and other "
                   "source works remain in the retained XML. " + qualification)
    expected_acquisition["source_scope"] = source_scope
    expected_acquisition["retained_files"][1]["scope"] = source_scope
    if _read(stage / acquisition_rel) != expected_acquisition:
        raise PipelineError("stage changes acquisition outside exact whole-IV/breakoff scope")
    original_manifest = SourceManifest.load(root / manifest_rel, repository_root=root)
    current_manifest = SourceManifest.load(stage / manifest_rel, repository_root=stage)
    original_package = CandidatePackage.load(Path(item["package_root"]) / "package")
    if (original_package.sha256 != item["package_sha256"]
            or _sha(Path(item["package_root"]) / "package/content.tei.xml") != item["candidate_tei_sha256"]
            or _sha(Path(item["package_root"]) / "validation.json") != item["validation_sha256"]):
        raise PipelineError("durable original package changed")
    original_validation = _read(Path(item["package_root"]) / "validation.json")
    original_oracle = validate(original_manifest, original_package,
                               _staged_oracle(root, original_manifest))
    if (original_oracle.status != "pass" or original_oracle.findings
            or original_oracle.sha256 != original_validation["report_sha256"]):
        raise PipelineError("original source oracle changed")
    integration = work / "integration" / EVIDENCE
    current_package = CandidatePackage.load(stage / integration / "inputs/current/package")
    current_validation = _read(stage / integration / "inputs/current/validation.json")
    current_oracle = validate(current_manifest, current_package,
                              _staged_oracle(stage, current_manifest))
    if (current_oracle.status != "pass" or current_oracle.findings
            or current_oracle.sha256 != current_validation["report_sha256"]
            or current_validation["source_manifest_sha256"] != current_manifest.sha256
            or current_package.member_bytes("content.tei.xml")
               != original_package.member_bytes("content.tei.xml")):
        raise PipelineError("current source oracle or candidate changed")
    if (_read(stage / profile_rel)["acquisition_sha256"] != _sha(stage / acquisition_rel)
            or _read(stage / acquisition_rel)["source_sha256"] != parts.SOURCE_SHA):
        raise PipelineError("staged acquisition source/profile binding changed")
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
               != original_package.member_bytes("content.tei.xml").split(b"</teiHeader>", 1)[1]):
        raise PipelineError("accepted master or exact source body changed")
    projected = project_accepted_prose(Path(_io_path(stage)),
                                       acceptance_path=Path(_io_path(stage / acceptance_rel)))
    errors = verify_accepted_prose(Path(_io_path(stage)),
                                   acceptance_path=Path(_io_path(stage / acceptance_rel)),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"actual-master prose projection changed: {errors[:3]}")
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
