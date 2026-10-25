"""Preflight exact remaining-bsb750 stages and journal-install only on explicit apply.

The default command is read-only. The stage, original candidate, current
canonical before generation, source-sidecar rebind, and native projection must
all agree with a pinned work-local receipt before the work lock is acquired.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from build.tools import install_openmgh_bsb830_next as transaction
from build.tools.stage_openmgh_bsb750_remaining import (
    BATCH, BATCH_SHA, CLAUSES, CONTRACT, ROOT, SOURCE, SOURCE_SHA,
    receipt_path,
)
from build.tools.stage_openmgh_inspected_acceptance import _files
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _io_path


PIN_INDEX = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb750-remaining-stage-pins-20260926.json"
PIN_INDEX_SHA = "18a8f81c653d1f737a1f6731dc8d016d6603b8c2956f3c80cefd2bb7a7edcf70"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    result = json.loads(_io_path(path).read_bytes())
    if not isinstance(result, dict):
        raise PipelineError(f"JSON object required: {path}")
    return result


def pinned_receipt(work_id: str) -> tuple[Path, str]:
    if work_id not in CLAUSES:
        raise PipelineError(f"work outside bsb750 remaining installer route: {work_id}")
    if _sha(PIN_INDEX) != PIN_INDEX_SHA:
        raise PipelineError("bsb750 remaining immutable pin index changed")
    pins = _read(PIN_INDEX)
    if pins.get("contract") != "ocd-openmgh-bsb750-remaining-pins-v1" or set(pins["works"]) != set(CLAUSES):
        raise PipelineError("stage pin index has wrong contract or work set")
    receipt = receipt_path(work_id)
    digest = pins["works"][work_id]["receipt_sha256"]
    if _sha(receipt) != digest:
        raise PipelineError(f"reviewed stage receipt changed: {work_id}")
    return receipt, digest


def preflight_receipt(receipt: Path) -> dict:
    record = _read(receipt.resolve(strict=True))
    work_id = record.get("work_id")
    if (record.get("contract") != CONTRACT or record.get("status") != "staged-only"
            or work_id not in CLAUSES or record.get("language") != "la"
            or record.get("category") != "prose" or record.get("installation") != "not-performed"):
        raise PipelineError("unrecognized bsb750 remaining stage receipt")
    if (record.get("original_inspection_receipt") != BATCH.as_posix()
            or record.get("original_inspection_receipt_sha256") != BATCH_SHA
            or record.get("source_path") != SOURCE.as_posix()
            or record.get("source_sha256") != SOURCE_SHA):
        raise PipelineError("stage is outside the pinned extracted-source tranche")
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("stage overlaps canonical root")
    work = Path("library/works") / work_id
    if _files(root / work) != record["before"] or _files(stage / work) != record["after"]:
        raise PipelineError("canonical before or staged after generation changed")
    if (_sha(root / BATCH) != BATCH_SHA or _sha(root / SOURCE) != SOURCE_SHA
            or _sha(stage / SOURCE) != SOURCE_SHA):
        raise PipelineError("inspected batch or extracted XML changed")
    batch = _read(root / BATCH)
    entries = [row for row in batch["works"] if row["work_id"] == work_id]
    if len(entries) != 1:
        raise PipelineError("inspected work is not unique")
    original = entries[0]
    candidate = CandidatePackage.load(Path(original["candidate_root"]) / "package")
    if (candidate.sha256 != record["original_candidate_sha256"]
            or _sha(Path(original["candidate_root"]) / "package/content.tei.xml")
            != record["original_candidate_tei_sha256"]):
        raise PipelineError("inspected nonaccepted candidate changed")
    manifest_rel, profile_rel = Path(record["manifest_path"]), Path(record["profile_path"])
    if (manifest_rel.as_posix() != original["manifest_path"]
            or profile_rel.as_posix() != original["profile_path"]
            or _sha(root / manifest_rel) != record["source_manifest_before_sha256"]
            or _sha(stage / manifest_rel) != record["source_manifest_after_sha256"]
            or _sha(root / profile_rel) != record["profile_before_sha256"]
            or _sha(stage / profile_rel) != record["profile_after_sha256"]):
        raise PipelineError("source manifest or profile rebind changed")
    manifest = SourceManifest.load(stage / manifest_rel, repository_root=stage)
    oracle_path = stage / manifest.record["validator"]["implementation_path"]
    spec = importlib.util.spec_from_file_location("ocd_bsb750_remaining_stage_oracle", _io_path(oracle_path))
    if spec is None or spec.loader is None:
        raise PipelineError("staged source oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    renewed = CandidatePackage.load(stage / work / "integration/openmgh-language-rebind-v1/package")
    report = validate(manifest, renewed, module._oracle)
    prior = _read(stage / work / "integration/openmgh-language-rebind-v1/oracle-validation.json")
    if report.status != "pass" or report.findings or prior["report_sha256"] != report.sha256:
        raise PipelineError("current independent source oracle failed")
    edition = work / "forms" / f"{work_id}-openmgh-retained" / "editions" / f"{work_id}-openmgh-electronic"
    acceptance = edition / "acceptance.json"
    accepted = validate_acceptance(stage / acceptance, root=stage)
    validate_state(stage / work / "state.json", root=stage)
    master = _io_path(stage / edition / "master.tei.xml").read_bytes()
    if (accepted["identity"]["work_id"] != work_id
            or accepted["promotion"]["master"]["sha256"] != record["accepted_master_sha256"]
            or hashlib.sha256(master).hexdigest() != record["accepted_master_sha256"]
            or master.split(b"</teiHeader>", 1)[1]
            != candidate.member_bytes("content.tei.xml").split(b"</teiHeader>", 1)[1]):
        raise PipelineError("accepted master differs from inspected source-faithful body")
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(stage / acceptance))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(stage / acceptance),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != record["projection_rows"]:
        raise PipelineError(f"native actual-master prose projection failed: {errors[:3]}")
    return {"status": "ready-for-review", "work_id": work_id,
            "before_files": len(record["before"]), "after_files": len(record["after"]),
            "projection_rows": len(projected["rows"]), "installation": "not-performed"}


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
            journal_contract="ocd-openmgh-bsb750-remaining-install-v1",
            operation_prefix="openmgh-bsb750-remaining",
            expected_receipt_sha256=digest, fail_at=fail_at,
        )
    finally:
        transaction.receipt_preflight = original


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(CLAUSES))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.work_id) if args.apply else preflight(args.work_id)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
