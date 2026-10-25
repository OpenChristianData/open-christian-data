"""Preflight or guarded-install two source-complete bsb829 terminal-line letters."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

from build.tools import install_openmgh_bsb830_next as transaction
from build.tools import prepare_openmgh_bsb829_terminal_lines as route
from build.tools.stage_openmgh_bsb829_terminal_lines_acceptance import CONTRACT, EVIDENCE
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import cached_edition_lookups, load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[2]
RECEIPTS = {
    "beno-letter-to-roman-church-fathers": (
        "cb9078b7ea48ce6d17821c54d0ebcc452b620f86350aa099fe0afb6add53d2cb",
        "w01r3",
    ),
    "bruno-of-segni-letter-to-st-george-brothers": (
        "b52320153d145007e128189c76aee171c34fc122d2a5480bfcd621df91d0bb1e",
        "w02",
    ),
}
RECEIPT_HOME = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb829-terminal-lines-stages-20260926"
STAGE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/b829-terminal-lines-stages-20260926")
JOURNAL_CONTRACT = "ocd-openmgh-bsb829-terminal-lines-install-v1"


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    record = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(record, dict):
        raise PipelineError(f"JSON object required: {path}")
    return record


def pinned_receipt(work_id: str) -> tuple[Path, str]:
    if work_id not in RECEIPTS:
        raise PipelineError(f"work outside two terminal-line letters: {work_id}")
    expected, _stage_name = RECEIPTS[work_id]
    path = RECEIPT_HOME / f"{work_id}-stage.json"
    if _sha(path) != expected:
        raise PipelineError(f"exact terminal-line stage receipt changed: {work_id}")
    return path, expected


def _oracle(root: Path, manifest: SourceManifest):
    path = root / manifest.record["validator"]["implementation_path"]
    spec = importlib.util.spec_from_file_location("ocd_bsb829_terminal_line_oracle", _io_path(path))
    if spec is None or spec.loader is None:
        raise PipelineError("terminal-line oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._oracle


@cached_edition_lookups()
def preflight_receipt(receipt: Path) -> dict:
    record = _read(receipt.resolve(strict=True))
    work_id = record.get("work_id")
    if (work_id not in RECEIPTS or record.get("contract") != CONTRACT
            or record.get("status") != "staged-only"
            or record.get("installation") != "not-performed"
            or record.get("category") != "prose" or record.get("language") != "la"
            or record.get("projection_rows") != 1
            or record.get("projection_status") != "independent-check-pass"):
        raise PipelineError("unrecognized terminal-line stage receipt")
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    work = Path("library/works") / work_id
    manifest_rel = route.SIDE_HOME / work_id / "source-manifest.json"
    profile_rel = route.SIDE_HOME / work_id / "reconstruction-profile.json"
    boundary_rel = route.SIDE_HOME / work_id / "boundary-review.json"
    if (root == stage or root in stage.parents or stage in root.parents
            or stage != (STAGE_HOME / RECEIPTS[work_id][1]).resolve(strict=True)
            or record.get("manifest_path") != manifest_rel.as_posix()
            or record.get("profile_path") != profile_rel.as_posix()
            or _files(root / work) != record["before"]
            or _files(stage / work) != record["after"]):
        raise PipelineError("terminal-line work identity, stage, or generation changed")
    for relative, expected in (
        (route.SOURCE, route.SOURCE_SHA), (route.BATCH, route.BATCH_SHA),
        (route.RECEIPT, route.RECEIPT_SHA), (route.PLAN, route.PLAN_SHA),
    ):
        if _sha(root / relative) != expected or _sha(stage / relative) != expected:
            raise PipelineError(f"frozen source or selection changed: {relative}")
    if _sha(root / route.PRIOR_PLAN) != route.PRIOR_PLAN_SHA:
        raise PipelineError("prior held-work selection changed")
    if (record.get("source_path") != route.SOURCE.as_posix()
            or record.get("source_sha256") != route.SOURCE_SHA
            or _sha(root / manifest_rel) != record["source_manifest_before_sha256"]
            or _sha(stage / manifest_rel) != record["source_manifest_after_sha256"]
            or _sha(root / profile_rel) != record["profile_before_sha256"]
            or _sha(stage / profile_rel) != record["profile_after_sha256"]
            or _sha(root / boundary_rel) != _sha(stage / boundary_rel)):
        raise PipelineError("terminal-line source sidecars changed")
    package_receipt = Path(record["package_receipt"]).resolve(strict=True)
    if _sha(package_receipt) != record["package_receipt_sha256"]:
        raise PipelineError("terminal-line package receipt changed")
    packages = _read(package_receipt)
    if (packages.get("contract") != "ocd-openmgh-bsb829-terminal-lines-packages-v1"
            or packages.get("source_sha256") != route.SOURCE_SHA
            or packages.get("frozen_batch_sha256") != route.BATCH_SHA
            or packages.get("selection_plan_sha256") != route.PLAN_SHA
            or len(packages.get("works", [])) != 2):
        raise PipelineError("two-work terminal-line package set changed")
    items = [item for item in packages["works"] if item["work_id"] == work_id]
    if len(items) != 1:
        raise PipelineError("work absent from terminal-line package set")
    item = items[0]
    acquisition_rel = Path(item["acquisition_path"])
    if (item["manifest_path"] != manifest_rel.as_posix()
            or item["profile_path"] != profile_rel.as_posix()
            or item["boundary_path"] != boundary_rel.as_posix()
            or item["manifest_sha256"] != record["source_manifest_before_sha256"]
            or item["profile_sha256"] != record["profile_before_sha256"]
            or item["boundary_sha256"] != _sha(root / boundary_rel)
            or not acquisition_rel.is_relative_to(work)
            or _sha(root / acquisition_rel) != item["acquisition_sha256"]):
        raise PipelineError("package and work-local source binding changed")
    original_manifest = SourceManifest.load(root / manifest_rel, repository_root=root)
    staged_manifest = SourceManifest.load(stage / manifest_rel, repository_root=stage)
    package_root = Path(item["package_root"])
    original = CandidatePackage.load(package_root / "package")
    original_validation = _read(package_root / "validation.json")
    if (original.sha256 != item["package_sha256"]
            or _sha(package_root / "package/content.tei.xml") != item["candidate_tei_sha256"]
            or _sha(package_root / "validation.json") != item["validation_sha256"]):
        raise PipelineError("original terminal-line candidate changed")
    original_oracle = validate(original_manifest, original, _oracle(root, original_manifest))
    if (original_oracle.status != "pass" or original_oracle.findings
            or original_oracle.sha256 != original_validation["report_sha256"]):
        raise PipelineError("original terminal-line source oracle changed")
    integration = work / "integration" / EVIDENCE
    current = CandidatePackage.load(stage / integration / "inputs/current/package")
    current_validation = _read(stage / integration / "inputs/current/validation.json")
    current_oracle = validate(staged_manifest, current, _oracle(stage, staged_manifest))
    if (current_oracle.status != "pass" or current_oracle.findings
            or current_oracle.sha256 != current_validation["report_sha256"]
            or current_validation["source_manifest_sha256"] != staged_manifest.sha256
            or current.member_bytes("content.tei.xml") != original.member_bytes("content.tei.xml")):
        raise PipelineError("current terminal-line candidate or oracle changed")
    if (_read(stage / profile_rel)["acquisition_sha256"] != _sha(stage / acquisition_rel)
            or _read(stage / acquisition_rel)["source_sha256"] != route.SOURCE_SHA):
        raise PipelineError("staged acquisition and profile binding changed")
    validate_acquisition(Path(_io_path(stage / acquisition_rel)), root=Path(_io_path(stage)))
    load_work(Path(_io_path(stage / work / "work.json")))
    edition = acquisition_rel.parent.parent
    acceptance_rel, master_rel = edition / "acceptance.json", edition / "master.tei.xml"
    accepted = validate_acceptance(Path(_io_path(stage / acceptance_rel)), root=Path(_io_path(stage)))
    validate_state(Path(_io_path(stage / work / "state.json")), root=Path(_io_path(stage)))
    master = Path(_io_path(stage / master_rel)).read_bytes()
    if (_sha(stage / acceptance_rel) != record["acceptance_sha256"]
            or accepted["identity"]["work_id"] != work_id
            or accepted["promotion"]["master"]["sha256"] != record["accepted_master_sha256"]
            or sha256(master).hexdigest() != record["accepted_master_sha256"]
            or master.split(b"</teiHeader>", 1)[1]
               != original.member_bytes("content.tei.xml").split(b"</teiHeader>", 1)[1]):
        raise PipelineError("terminal-line accepted master differs from source candidate")
    projected = project_accepted_prose(Path(_io_path(stage)), acceptance_path=Path(_io_path(stage / acceptance_rel)))
    errors = verify_accepted_prose(Path(_io_path(stage)), acceptance_path=Path(_io_path(stage / acceptance_rel)),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"terminal-line actual-master projection failed: {errors[:3]}")
    return {"status": "ready-for-review", "work_id": work_id,
            "before_files": len(record["before"]), "after_files": len(record["after"]),
            "projection_rows": 1, "installation": "not-performed"}


def preflight(work_id: str) -> dict:
    receipt, _digest = pinned_receipt(work_id)
    return preflight_receipt(receipt)


def install(work_id: str, *, fail_at=None) -> dict:
    receipt, digest = pinned_receipt(work_id)
    preflight_receipt(receipt)
    original = transaction.receipt_preflight
    try:
        transaction.receipt_preflight = preflight_receipt
        return transaction.install(
            receipt, allowed_ids=frozenset({work_id}),
            journal_contract=JOURNAL_CONTRACT,
            operation_prefix="openmgh-bsb829-terminal-lines",
            expected_receipt_sha256=digest, fail_at=fail_at,
        )
    finally:
        transaction.receipt_preflight = original


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(RECEIPTS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.work_id) if args.apply else preflight(args.work_id)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
