"""Guardedly install one exact Greenleaf PG34989 acceptance stage.

The default command is read-only preflight. ``--apply`` swaps only this work
under a lock, retains prior bytes in a journaled operation, and rolls back on
failed post-install validation. It does not refresh a corpus or publish data.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import uuid

from build.tools.preflight_greenleaf_pg34989_acceptance import preflight
from build.tools.stage_greenleaf_pg34989_acceptance import EDITION, WORK, WORK_ID
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable

CONTRACT = "ocd-greenleaf-pg34989-install-v1"


def _sha(path: Path) -> str:
    return sha256(io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _installed_check(root: Path, receipt: dict) -> dict:
    if _files(root / WORK) != receipt["after"]:
        raise PipelineError("installed Greenleaf work generation differs")
    acceptance = root / EDITION / "acceptance.json"
    accepted = validate_acceptance(acceptance, root=root)
    master = root / EDITION / "master.tei.xml"
    if (accepted["identity"]["work_id"] != WORK_ID
            or _sha(master) != receipt["accepted_master_sha256"]
            or _sha(acceptance) != receipt["acceptance_sha256"]):
        raise PipelineError("installed Greenleaf acceptance/master differs")
    projection = project_accepted_prose(io_path(root), acceptance_path=io_path(acceptance))
    errors = verify_accepted_prose(io_path(root), acceptance_path=io_path(acceptance),
                                   rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 13:
        raise PipelineError(f"installed Greenleaf actual-master projection differs: {errors[:3]}")
    for key, value in (("native_rows_sha256", projection["rows"]),
                       ("native_receipt_sha256", projection["receipt"])):
        actual = sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8")).hexdigest()
        if actual != receipt.get(key):
            raise PipelineError(f"installed Greenleaf {key} differs from reviewed stage")
    return dict(rows=13, master_sha256=receipt["accepted_master_sha256"])


def _swap_work(
    target: Path, source: Path, operation: Path, *, before: dict[str, str],
    after: dict[str, str], work_id: str, stage_receipt: Path,
    stage_receipt_sha256: str, validate: Callable[[], dict],
    fail_at: Callable[[str], None] | None = None,
) -> dict:
    """Swap one complete generation; retain and restore exact prior bytes."""
    io_path(operation).mkdir(parents=True, exist_ok=False)
    incoming = operation / "incoming"
    previous = operation / "previous"
    failed_new = operation / "failed-new"
    journal = operation / "operation.json"
    state = dict(contract=CONTRACT, work_id=work_id,
                 stage_receipt=stage_receipt.as_posix(),
                 stage_receipt_sha256=stage_receipt_sha256,
                 phase="created", before=before, after=after, updated_at=_now())
    _write_json_durable(journal, state)
    moved = live = False
    try:
        shutil.copytree(_io_path(source), _io_path(incoming))
        if _files(incoming) != after or _files(target) != before:
            raise PipelineError("Greenleaf incoming or live preimage changed")
        state.update(phase="prepared", updated_at=_now())
        _write_json_durable(journal, state)
        if fail_at:
            fail_at("after-copy")
        os.replace(_io_path(target), _io_path(previous))
        moved = True
        state.update(phase="previous-moved", updated_at=_now())
        _write_json_durable(journal, state)
        if fail_at:
            fail_at("after-old-rename")
        os.replace(_io_path(incoming), _io_path(target))
        live = True
        state.update(phase="new-work-live", updated_at=_now())
        _write_json_durable(journal, state)
        if fail_at:
            fail_at("after-new-rename")
        checked = validate()
        if fail_at:
            fail_at("after-validation")
        state.update(phase="complete", validation=checked, updated_at=_now())
        _write_json_durable(journal, state)
        return dict(status="installed-and-validated", operation=operation.as_posix(),
                    before_count=len(before), after_count=len(after), projection_rows=checked["rows"])
    except BaseException:
        try:
            if live:
                if _files(target) != after:
                    raise PipelineError("Greenleaf live work changed before rollback")
                os.replace(_io_path(target), _io_path(failed_new))
            if moved:
                if _io_path(target).exists() or _files(previous) != before:
                    raise PipelineError("Greenleaf prior work changed before rollback")
                os.replace(_io_path(previous), _io_path(target))
                if _files(target) != before:
                    raise PipelineError("Greenleaf work rollback differs")
            state.update(phase="rolled-back" if moved else "failed-before-swap", updated_at=_now())
            _write_json_durable(journal, state)
        except BaseException as error:
            state.update(phase="recovery-required", rollback_error=str(error), updated_at=_now())
            _write_json_durable(journal, state)
            raise PipelineError(f"Greenleaf rollback requires recovery: {operation}") from error
        raise


def install(receipt: Path, *, expected_sha256: str,
            fail_at: Callable[[str], None] | None = None) -> dict:
    receipt = receipt.resolve(strict=True)
    preflight(receipt, expected_sha256=expected_sha256)
    record = json.loads(io_path(receipt).read_bytes())
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    target = root / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _sha(receipt) != expected_sha256:
            raise PipelineError("Greenleaf reviewed receipt changed under work lock")
        preflight(receipt, expected_sha256=expected_sha256)
        operation = root / "library/.sidecar-operations" / f"greenleaf-pg34989-{uuid.uuid4().hex[:16]}"
        return _swap_work(target, stage / WORK, operation, before=record["before"],
                          after=record["after"], work_id=WORK_ID, stage_receipt=receipt,
                          stage_receipt_sha256=expected_sha256,
                          validate=lambda: _installed_check(root, record),
                          fail_at=fail_at)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = (install(args.receipt, expected_sha256=args.expected_sha256) if args.apply
              else preflight(args.receipt, expected_sha256=args.expected_sha256))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
