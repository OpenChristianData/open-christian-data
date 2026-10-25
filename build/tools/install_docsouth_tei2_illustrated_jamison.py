"""Guarded Jamison illustrated installer; default is read-only preflight."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei import docsouth_tei2_illustrated_jamison as source
from build.tei.docsouth_tei2_illustrated_jamison_oracle import check
from build.tools import prepare_docsouth_tei2_illustrated_jamison as direct_source
from build.tools import freeze_docsouth_tei2_illustrated_jamison as freezing
from build.tools import stage_docsouth_tei2_illustrated_jamison as staging
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file
from build.tools.docsouth_review import preflight as _shared_preflight
from build.tools.docsouth_review import work_pin as _shared_work_pin


ROOT = Path(__file__).resolve().parents[2]
FREEZE_SHA = "8c19fab0669162ef0c53e8e0f43f009112d53ecc3b39556706202a7b4cb847a7"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _frozen() -> dict:
    if _sha(freezing.FREEZE) != FREEZE_SHA:
        raise PipelineError("DocSouth reviewed freeze changed")
    frozen = _read(freezing.FREEZE)
    if (frozen.get("contract") != freezing.CONTRACT or frozen.get("status") != "review-ready-staged-only"
            or frozen.get("canonical_install") != "not-performed" or frozen.get("selected_work_count") != 1
            or frozen.get("other_inventory_work_count") != 26 or len(frozen.get("works", [])) != 1
            or {item["work_id"] for item in frozen["works"]} != set(direct_source.SELECTIONS)
            or frozen.get("direct_receipt_sha256") != staging.DIRECT_SHA
            or frozen.get("inventory_sha256") != source.INVENTORY_SHA):
        raise PipelineError("DocSouth freeze scope differs")
    if (Path(frozen["canonical_root"]).resolve(strict=True) != ROOT.resolve(strict=True)
            or Path(frozen["stage_home"]).resolve(strict=True) != freezing.STAGE_HOME.resolve(strict=True)
            or Path(frozen["direct_receipt"]).resolve(strict=True) != (staging.DIRECT / "receipt.json").resolve(strict=True)):
        raise PipelineError("DocSouth frozen roots differ")
    if (_sha(ROOT / frozen["inventory_path"]) != source.INVENTORY_SHA
            or _sha(staging.DIRECT / "receipt.json") != staging.DIRECT_SHA):
        raise PipelineError("DocSouth inventory or direct receipt changed")
    return frozen


def _work_pin(frozen: dict, work_id: str) -> tuple[dict, Path, dict]:
    return _shared_work_pin(frozen, work_id, _read=_read, _sha=_sha, staging=staging)


def preflight(work_id: str) -> dict:
    return _shared_preflight(work_id, ROOT=ROOT, _frozen=_frozen, _read=_read, _sha=_sha,
        _work_pin=_work_pin, check=check, direct_source=direct_source, source=source,
        staging=staging)


def install(work_id: str, *, fail_at: Callable[[str], None] | None = None) -> dict:
    preflight(work_id)
    frozen = _frozen()
    pin, stage, record = _work_pin(frozen, work_id)
    work = Path("library/works") / work_id
    target = ROOT / work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _sha(stage / "stage-receipt.json") != pin["stage_receipt_sha256"]:
            raise PipelineError("DocSouth stage receipt changed under lock")
        preflight(work_id)
        return _commit_generation(ROOT, target, stage / work, work_id=work_id,
                                  before=record["before"], after=record["after"],
                                  existed=True, replacement=False,
                                  operation_kind="docsouth-tei2-illustrated-jamison-initial-install",
                                  result_status="installed-and-validated", accepted_editions=1, fail_at=fail_at)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(direct_source.SELECTIONS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.work_id) if args.apply else preflight(args.work_id)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
