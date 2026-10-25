"""Guardedly install one reviewed Goffridus division-21 native part stage.

The exact receipt is preflighted under a work lock. The complete work generation,
source profile, and source manifest are swapped with retained rollback bytes.
No corpus view or public release is generated here.
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

from build.tools.preflight_openmgh_bsb829_gof_parts import preflight as receipt_preflight
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import (
    project_accepted_prose, verify_accepted_prose,
)
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable


CONTRACT = "ocd-openmgh-bsb829-gof-parts-acceptance-install-v1"
IDS = frozenset({
    "goffridus-de-ordinatione-episcopi-to-peter-leonis",
    "goffridus-de-ordinatione-episcoporum-to-bernerius",
    "goffridus-de-promissionibus-abbatum-episcopis",
    "goffridus-de-simonia-et-investitura-to-calixtus",
    "goffridus-libellus-to-paschal-ii-on-investiture",
    "goffridus-libellus-to-rainald-on-lay-investiture",
    "goffridus-quae-tria-ecclesia-habere-debet",
    "goffridus-qualiter-dispensationes-fieri-debent",
})


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read(path: Path) -> dict:
    result = json.loads(_io_path(path).read_bytes())
    if not isinstance(result, dict):
        raise PipelineError(f"JSON object required: {path}")
    return result


@cached_edition_lookups()
def _installed_check(root: Path, record: dict) -> dict:
    work_id = record["work_id"]
    work = Path("library/works") / work_id
    manifest = Path(record["manifest_path"])
    profile = Path(record["profile_path"])
    if (_files(root / work) != record["after"]
            or _sha(root / manifest) != record["source_manifest_after_sha256"]
            or _sha(root / profile) != record["profile_after_sha256"]):
        raise PipelineError("installed work or source sidecars differ from stage")
    SourceManifest.load(root / manifest, repository_root=root)
    edition = work / "forms" / f"{work_id}-openmgh-retained" / "editions" / f"{work_id}-openmgh-electronic"
    acceptance = edition / "acceptance.json"
    accepted = validate_acceptance(root / acceptance, root=root)
    validate_state(root / work / "state.json", root=root)
    if (accepted["identity"]["work_id"] != work_id
            or accepted["promotion"]["master"]["sha256"] != record["accepted_master_sha256"]
            or _sha(root / edition / "master.tei.xml") != record["accepted_master_sha256"]):
        raise PipelineError("installed public acceptance/master differs")
    if record.get("category") != "prose" or record.get("projection_rows") != 1:
        raise PipelineError("native part requires one Latin prose row")
    projected = project_accepted_prose(_io_path(root),
                                       acceptance_path=_io_path(root / acceptance))
    errors = verify_accepted_prose(_io_path(root), acceptance_path=_io_path(root / acceptance),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"installed actual-master prose check failed: {errors[:3]}")
    return {"rows": len(projected["rows"]), "master_sha256": record["accepted_master_sha256"]}


def install(
    receipt: Path, *, fail_at: Callable[[str], None] | None = None,
    operation_prefix: str = "openmgh-bsb829-gof-parts",
    expected_receipt_sha256: str | None = None,
) -> dict:
    receipt = receipt.resolve(strict=True)
    record = _read(receipt)
    if record.get("work_id") not in IDS:
        raise PipelineError("work is outside the guarded installer allowlist")
    if expected_receipt_sha256 is None:
        raise PipelineError("an exact reviewed stage receipt SHA-256 is required")
    if _sha(receipt) != expected_receipt_sha256:
        raise PipelineError("exact reviewed stage receipt hash changed")
    receipt_preflight(receipt)
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    work = Path("library/works") / record["work_id"]
    target = root / work
    manifest = Path(record["manifest_path"])
    profile = Path(record["profile_path"])
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _sha(receipt) != expected_receipt_sha256:
            raise PipelineError("reviewed stage receipt changed under work lock")
        receipt_preflight(receipt)
        operation = root / "library/.sidecar-operations" / f"{operation_prefix}-{uuid.uuid4().hex[:16]}"
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming = operation / "incoming"
        previous = operation / "previous"
        failed_new = operation / "failed-new"
        journal = operation / "operation.json"
        backups = {
            profile: (operation / "profile-before.json", operation / "profile-after.json"),
            manifest: (operation / "manifest-before.json", operation / "manifest-after.json"),
        }
        expected = {
            profile: (record["profile_before_sha256"], record["profile_after_sha256"]),
            manifest: (record["source_manifest_before_sha256"], record["source_manifest_after_sha256"]),
        }
        state = {
            "contract": CONTRACT,
            "work_id": record["work_id"],
            "stage_receipt": receipt.as_posix(),
            "stage_receipt_sha256": _sha(receipt),
            "before": record["before"], "after": record["after"],
            "external_before": {p.as_posix(): expected[p][0] for p in backups},
            "external_after": {p.as_posix(): expected[p][1] for p in backups},
            "phase": "created", "updated_at": _now(),
        }
        _write_json_durable(journal, state)
        moved = live = False
        swapped: list[Path] = []
        try:
            shutil.copytree(_io_path(stage / work), _io_path(incoming))
            for relative, (before_path, after_path) in backups.items():
                shutil.copy2(_io_path(root / relative), _io_path(before_path))
                shutil.copy2(_io_path(stage / relative), _io_path(after_path))
                if (_sha(before_path), _sha(after_path)) != expected[relative]:
                    raise PipelineError(f"copied source sidecar differs: {relative}")
            if _files(incoming) != record["after"] or _files(target) != record["before"]:
                raise PipelineError("incoming or canonical work generation changed")
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
            for relative, (_before_path, after_path) in backups.items():
                os.replace(_io_path(after_path), _io_path(root / relative))
                swapped.append(relative)
                state.update(phase=f"new-{relative.name}-live", updated_at=_now())
                _write_json_durable(journal, state)
                if fail_at:
                    fail_at(f"after-{relative.name}-swap")
            checked = _installed_check(root, record)
            if fail_at:
                fail_at("after-validation")
            state.update(phase="complete", validation=checked, updated_at=_now())
            _write_json_durable(journal, state)
            return {
                "status": "installed-and-validated", "work_id": record["work_id"],
                "operation": operation.as_posix(), "before_count": len(record["before"]),
                "after_count": len(record["after"]), "projection_rows": checked["rows"],
            }
        except BaseException:
            try:
                for relative in reversed(swapped):
                    before_path, _after_path = backups[relative]
                    if _sha(root / relative) != expected[relative][1]:
                        raise PipelineError(f"source sidecar changed before rollback: {relative}")
                    restore = operation / f"restore-{relative.name}"
                    shutil.copy2(_io_path(before_path), _io_path(restore))
                    os.replace(_io_path(restore), _io_path(root / relative))
                    if _sha(root / relative) != expected[relative][0]:
                        raise PipelineError(f"source sidecar rollback differs: {relative}")
                if live:
                    if _files(target) != record["after"]:
                        raise PipelineError("live work changed before rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != record["before"]:
                        raise PipelineError("previous work changed before rollback")
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != record["before"]:
                        raise PipelineError("work rollback differs")
                state.update(phase="rolled-back" if moved else "failed-before-swap", updated_at=_now())
                _write_json_durable(journal, state)
            except BaseException as error:
                state.update(phase="recovery-required", rollback_error=str(error), updated_at=_now())
                _write_json_durable(journal, state)
                raise PipelineError(f"rollback requires recovery: {operation}") from error
            raise


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
        result = receipt_preflight(args.receipt)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
