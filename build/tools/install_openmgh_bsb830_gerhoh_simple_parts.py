"""Guarded bsb830 five Gerhoh installer; default action is read-only preflight."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb830_gerhoh_simple_parts as source
from build.tei.openmgh_bsb830_gerhoh_simple_parts_oracle import check
from build.tools import stage_openmgh_bsb830_gerhoh_simple_parts as staging
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file
from build.tools.openmgh_review import preflight as _shared_preflight
from build.tools.openmgh_review import work_pin as _shared_work_pin


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb830-gerhoh-simple-freeze-20260928-v1.json"
FREEZE_SHA = "59a307d0ab781f5420a9da18af985a51ec46d4644685b075502a92a82b3e35a6"
CONTRACT = "ocd-openmgh-bsb830-gerhoh-simple-freeze-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _frozen() -> dict:
    if _sha(FREEZE) != FREEZE_SHA:
        raise PipelineError("bsb830 reviewed freeze changed")
    frozen = _read(FREEZE)
    if (frozen.get("contract") != CONTRACT or frozen.get("status") != "review-ready-staged-only"
            or frozen.get("canonical_install") != "not-performed" or len(frozen.get("works", [])) != 5
            or {item["work_id"] for item in frozen["works"]} != set(source.SELECTIONS)
            or frozen.get("selected_part_count") != 5
            or {item.get("source_part_index") for item in frozen.get("held_parts", [])} != source.HELD_PARTS
            or any(item.get("source_work_div_index") != 6 for item in frozen.get("held_parts", []))
            or frozen.get("source_sha256") != source.SOURCE_SHA
            or frozen.get("package_sha256") != source.PACKAGE_SHA
            or Path(frozen["canonical_root"]).resolve(strict=True) != ROOT.resolve(strict=True)):
        raise PipelineError("bsb830 freeze scope or authority differs")
    for path, digest in ((source.SOURCE, source.SOURCE_SHA), (source.PACKAGE, source.PACKAGE_SHA),
                         (source.ACQUISITION_RECEIPT, source.ACQUISITION_RECEIPT_SHA)):
        if _sha(ROOT / path) != digest:
            raise PipelineError(f"bsb830 retained source/package/receipt differs: {path}")
    if _sha(Path(frozen["direct_receipt"])) != staging.DIRECT_SHA:
        raise PipelineError("bsb830 direct candidate receipt differs")
    return frozen


def _work_pin(frozen: dict, work_id: str) -> tuple[dict, Path, dict]:
    return _shared_work_pin(frozen, work_id, _read=_read, _sha=_sha, source=source,
        staging=staging)


def preflight(work_id: str) -> dict:
    return _shared_preflight(work_id, ROOT=ROOT, _frozen=_frozen, _read=_read, _sha=_sha,
        _work_pin=_work_pin, check=check, source=source, staging=staging)


def install(work_id: str, *, fail_at: Callable[[str], None] | None = None) -> dict:
    preflight(work_id)
    frozen = _frozen()
    pin, stage, record = _work_pin(frozen, work_id)
    work = Path("library/works") / work_id
    target = ROOT / work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _sha(stage / "stage-receipt.json") != pin["stage_receipt_sha256"]:
            raise PipelineError("bsb830 stage receipt changed under lock")
        preflight(work_id)
        return _commit_generation(ROOT, target, stage / work, work_id=work_id,
                                  before=record["before"], after=record["after"],
                                  existed=True, replacement=False,
                                  operation_kind="openmgh-bsb830-gerhoh-simple-initial-install",
                                  result_status="installed-and-validated", accepted_editions=1, fail_at=fail_at)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(source.SELECTIONS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.work_id) if args.apply else preflight(args.work_id)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
