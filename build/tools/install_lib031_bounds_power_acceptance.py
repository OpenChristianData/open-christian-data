"""Guardedly install the pinned Bounds Power accepted generation.

The default CLI route is read-only. Apply replaces only the complete Bounds
work folder and retains the previous bytes and operation journal for recovery.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from build.tools.preflight_lib031_bounds_power_acceptance import (
    EDITION, WORK, preflight,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable

STAGE = Path(r"D:\Library\Open Christian Data\bpow3")
RECEIPT_SHA256 = "ff395f392b73b882b75893a0dda63d16346295e959ec80b67803d87f7e8886ce"
OPERATION_CONTRACT = "ocd-lib031-bounds-power-work-swap-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _copy_generation(source: Path, destination: Path, expected: dict[str, str]) -> None:
    if _io_path(destination).exists():
        raise PipelineError("Bounds incoming generation already exists")
    _io_path(destination).mkdir(parents=True)
    for relative, digest in expected.items():
        origin = _io_path(source / relative)
        target = _io_path(destination / relative)
        if not origin.is_file() or _sha(origin) != digest:
            raise PipelineError(f"Bounds staged file changed during copy: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    if _files(destination) != expected:
        raise PipelineError("Bounds copied generation differs")


def _external_evidence(root: Path, stage: Path, *, fixture: bool) -> None:
    if _sha(stage / "stage-receipt.json") != RECEIPT_SHA256:
        raise PipelineError("Bounds stage receipt changed")
    prefix = WORK.as_posix() + "/"
    for relative, expected in _files(stage).items():
        if relative == "stage-receipt.json" or relative.startswith(prefix):
            continue
        path = root / relative if fixture or not relative.startswith(("raw/", "reports/", "exports/")) else resolve_repo_path(root, relative)
        if not _io_path(path).is_file() or _sha(path) != expected or _sha(stage / relative) != expected:
            raise PipelineError(f"Bounds external dependency changed: {relative}")


def _checked_generation(root: Path, after: dict[str, str]) -> None:
    target = root / WORK
    if _files(target) != after:
        raise PipelineError("Bounds installed generation differs")
    acceptance = _io_path(root / EDITION / "acceptance.json")
    validated = validate_acceptance(acceptance, root=_io_path(root))
    if validated["promotion"]["status"] != "promoted" or validated["identity"]["work_id"] != "bounds-power-through-prayer":
        raise PipelineError("Bounds public acceptance differs after install")
    state = validate_state(_io_path(target / "state.json"), root=_io_path(root))
    edition_id = validated["identity"]["edition_id"]
    edition_targets = [item for item in state["targets"] if item["target_id"] == edition_id]
    if len(edition_targets) != 1 or edition_targets[0]["stage"] != "accepted":
        raise PipelineError("Bounds edition state differs after install")
    projection = project_accepted_prose(root, acceptance_path=acceptance)
    problems = verify_accepted_prose(root, acceptance_path=acceptance, rows=projection["rows"], receipt=projection["receipt"])
    if problems or len(projection["rows"]) != 1 or projection["receipt"]["unsupported"]:
        raise PipelineError(f"Bounds actual-master prose projection differs: {problems[:3]}")


def install(*, root_override: Path | None = None, fail_at: Callable[[str], None] | None = None) -> dict[str, object]:
    """Recheck the exact pin, swap one work generation, and restore on failure."""
    stage = STAGE.resolve(strict=True)
    check = preflight(stage, RECEIPT_SHA256, root_override=root_override)
    root = Path(check["target_root"])
    fixture = root_override is not None
    target = root / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        # The first preflight can race other work. Repeat its whole contract
        # after acquiring the work-local lock, before any canonical mutation.
        check = preflight(stage, RECEIPT_SHA256, root_override=root_override)
        before, after = check["before"], check["after"]
        if _files(target) != before or _files(stage / WORK) != after:
            raise PipelineError("Bounds work generation changed after preflight")
        operation = root / "library/.sidecar-operations" / ("lib031-bpow-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ("incoming", "previous", "failed-new"))
        journal_path = operation / "operation.json"
        journal: dict[str, object] = {
            "contract": OPERATION_CONTRACT,
            "work_id": "bounds-power-through-prayer",
            "phase": "created",
            "stage": stage.as_posix(),
            "receipt_sha256": RECEIPT_SHA256,
            "before": before,
            "after": after,
            "updated_at": _now(),
        }
        _write_json_durable(journal_path, journal)
        moved = live = False
        try:
            _copy_generation(stage / WORK, incoming, after)
            if _files(target) != before:
                raise PipelineError("Bounds canonical generation changed during copy")
            journal.update(phase="prepared", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-copy")
            refreshed = preflight(stage, RECEIPT_SHA256, root_override=root_override)
            if refreshed["before"] != before or refreshed["after"] != after:
                raise PipelineError("Bounds staged or canonical generation changed before swap")
            _external_evidence(root, stage, fixture=fixture)
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            journal.update(phase="previous-moved", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-old-rename")
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            journal.update(phase="new-live", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-new-rename")
            _checked_generation(root, after)
            if fail_at:
                fail_at("after-postcheck")
            _external_evidence(root, stage, fixture=fixture)
            journal.update(phase="complete", updated_at=_now())
            _write_json_durable(journal_path, journal)
            return {
                "status": "installed-and-validated",
                "operation": operation.as_posix(),
                "before_count": len(before),
                "after_count": len(after),
                "master_sha256": check["master_sha256"],
                "projection_rows": 1,
            }
        except BaseException:
            try:
                if live:
                    if _files(target) != after:
                        raise PipelineError("Bounds live generation differs during rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != before:
                        raise PipelineError("Bounds prior generation differs during rollback")
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != before:
                        raise PipelineError("Bounds rollback restored wrong bytes")
                journal.update(phase="rolled-back" if moved else "failed-before-swap", updated_at=_now())
                _write_json_durable(journal_path, journal)
            except BaseException as rollback_error:
                journal.update(phase="recovery-required", rollback_error=str(rollback_error), updated_at=_now())
                _write_json_durable(journal_path, journal)
                raise PipelineError(f"Bounds rollback requires recovery: {operation}") from rollback_error
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="install the exact pinned work generation")
    args = parser.parse_args()
    if args.apply:
        result = install()
    else:
        check = preflight(STAGE, RECEIPT_SHA256)
        result = {key: value for key, value in check.items() if key not in {"before", "after"}}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
