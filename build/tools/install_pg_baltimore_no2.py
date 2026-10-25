"""Preflight or guarded-install the frozen Gutenberg Baltimore No. 2 stage."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.catechisms import (
    project_accepted_catechisms, verify_accepted_catechisms,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path


ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "plans/2026-09-22-source-preflight/pg-baltimore-no2-stage-pin-20260927.json"
PINS_SHA = "8a36c570df359e36bd68891924e71636f22c517851c94a3a585886400460995b"
WORK_ID = "baltimore-catechism-no-2"
WORK = Path("library/works") / WORK_ID
EDITION = WORK / "forms/baltimore-catechism-no-2-retained-electronic/editions/baltimore-catechism-no-2-retained-electronic-witness"
ACQUISITION = EDITION / "acquisitions/baltimore-catechism-no-2-retained-source.json"
SOURCE = Path("raw/gutenberg/pg14552.txt")
MANIFEST = Path("sources/gutenberg-catechisms/baltimore-catechism-no-2/source-manifest.json")


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _pin(receipt: Path, record: dict) -> dict:
    if _sha(PINS) != PINS_SHA:
        raise PipelineError("frozen Baltimore No. 2 pin index changed")
    pins = _read(PINS)
    if (pins.get("contract") != "ocd-pg-baltimore-no2-stage-pin-v1"
            or pins.get("work_id") != WORK_ID
            or pins.get("source_path") != SOURCE.as_posix()
            or pins.get("category") != "catechisms"
            or pins.get("source_line_count") != 3675
            or pins.get("question_answer_count") != 421):
        raise PipelineError("Baltimore No. 2 exact source/category pins differ")
    if (receipt != Path(pins["receipt"]).resolve(strict=True)
            or _sha(receipt) != pins["receipt_sha256"]
            or record.get("contract") != "ocd-pg-baltimore-no2-acceptance-stage-v1"
            or record.get("status") != "staged-only"
            or record.get("work_id") != WORK_ID
            or record.get("source_path") != pins["source_path"]
            or record.get("source_sha256") != pins["source_sha256"]
            or record.get("source_manifest_sha256") != pins["source_manifest_sha256"]
            or record.get("package_sha256") != pins["package_sha256"]
            or record.get("validation_sha256") != pins["validation_sha256"]
            or record.get("oracle_report_sha256") != pins["oracle_report_sha256"]
            or record.get("accepted_master_sha256") != pins["accepted_master_sha256"]
            or record.get("category") != pins["category"]
            or record.get("source_line_count") != pins["source_line_count"]
            or record.get("question_answer_count") != pins["question_answer_count"]
            or record.get("projection_rows") != 1
            or record.get("installation") != "not-performed"):
        raise PipelineError("reviewed Baltimore receipt/source/master pin differs")
    return pins


def _project(root: Path, record: dict) -> None:
    acceptance = root / EDITION / "acceptance.json"
    accepted = validate_acceptance(_io_path(acceptance), root=_io_path(root))
    if (_sha(root / EDITION / "master.tei.xml") != record["accepted_master_sha256"]
            or accepted["promotion"]["master"]["sha256"] != record["accepted_master_sha256"]):
        raise PipelineError("Baltimore actual master differs from frozen stage")
    projected = project_accepted_catechisms(
        _io_path(root), acceptance_path=_io_path(acceptance))
    errors = verify_accepted_catechisms(
        _io_path(root), acceptance_path=_io_path(acceptance),
        rows=projected["rows"], receipt=projected["receipt"])
    if (errors or len(projected["rows"]) != 1
            or projected["rows"][0]["source_line_count"] != 3675
            or len(projected["rows"][0]["question_answers"]) != 421):
        raise PipelineError(f"Baltimore actual-master native row differs: {errors[:3]}")


def preflight(receipt: Path) -> dict:
    receipt = receipt.resolve(strict=True)
    record = _read(receipt)
    pins = _pin(receipt, record)
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("Baltimore stage overlaps canonical root")
    if (_sha(root / SOURCE) != pins["source_sha256"]
            or _sha(root / MANIFEST) != pins["source_manifest_sha256"]
            or _sha(stage / SOURCE) != pins["source_sha256"]
            or _sha(stage / MANIFEST) != pins["source_manifest_sha256"]):
        raise PipelineError("retained Baltimore TXT or source manifest changed")
    source_manifest = SourceManifest.load(stage / MANIFEST, repository_root=stage)
    source_manifest.verify()
    if source_manifest.sha256 != pins["source_manifest_sha256"]:
        raise PipelineError("staged Baltimore source manifest differs")
    package = CandidatePackage.load(_io_path(Path(record["package_root"]) / "package"))
    if (package.sha256 != pins["package_sha256"]
            or _sha(Path(record["package_root"]) / "validation.json") != pins["validation_sha256"]):
        raise PipelineError("reviewed Baltimore candidate/validation changed")
    acquisition = validate_acquisition(_io_path(root / ACQUISITION), root=_io_path(root))
    if (acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != pins["source_sha256"]
            or _sha(stage / ACQUISITION) != _sha(root / ACQUISITION)):
        raise PipelineError("Baltimore acquisition changed")
    if _files(root / WORK) != record["before"] or _files(stage / WORK) != record["after"]:
        raise PipelineError("Baltimore live preimage or staged generation changed")
    if _sha(stage / EDITION / "acceptance.json") != record["acceptance_sha256"]:
        raise PipelineError("Baltimore staged acceptance changed")
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    _project(stage, record)
    return {"status": "ready-for-review", "work_id": WORK_ID,
            "before_count": len(record["before"]), "after_count": len(record["after"]),
            "projection_rows": 1, "receipt_sha256": pins["receipt_sha256"]}


def install(receipt: Path, *, expected_receipt_sha256: str,
            fail_at: Callable[[str], None] | None = None) -> dict:
    receipt = receipt.resolve(strict=True)
    record = _read(receipt)
    frozen = _pin(receipt, record)["receipt_sha256"]
    if expected_receipt_sha256 != frozen:
        raise PipelineError("exact reviewed Baltimore receipt hash changed")
    preflight(receipt)
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    target, source = root / WORK, stage / WORK
    with ExitStack() as locks:
        for lock_target in sorted((target, source), key=lambda path: path.as_posix()):
            locks.enter_context(acquire_jsonl_lock(lock_target, acquire_timeout=30.0))
        if _pin(receipt, _read(receipt))["receipt_sha256"] != expected_receipt_sha256:
            raise PipelineError("Baltimore receipt changed under work lock")
        preflight(receipt)

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != record["after"]:
                    raise PipelineError("live Baltimore generation differs")
                _project(root, record)
            if fail_at:
                fail_at(point)

        result = _commit_generation(
            root, target, source, work_id=WORK_ID,
            before=record["before"], after=record["after"],
            existed=True, replacement=False,
            operation_kind="pg14552-exact-source-install",
            result_status="installed-and-validated", accepted_editions=1,
            fail_at=checkpoint,
        )
    return result | {"projection_rows": 1}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-receipt-sha256")
    args = parser.parse_args()
    if args.apply:
        result = install(args.receipt,
                         expected_receipt_sha256=args.expected_receipt_sha256)
    else:
        result = preflight(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
