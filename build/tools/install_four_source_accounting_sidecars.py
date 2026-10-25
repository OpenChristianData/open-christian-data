"""Guardedly install a reviewed four-work source-accounting stage."""
from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from build.tools.prepare_four_source_accounting_sidecars import (
    PACKET_REL, RECEIPT_REL, WORK_IDS, preflight,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError, load_json, sha256_file, write_json
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.install_accepted import _files, _io_path


def _install_one(root: Path, stage: Path, entry: dict[str, Any]) -> dict[str, Any]:
    wid = entry["work_id"]
    if wid not in WORK_IDS:
        raise PipelineError(f"unreviewed four-work identity: {wid}")
    prefix = f"library/works/{wid}/"
    target = root / "library/works" / wid
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        before = _files(target)
        for item in entry["files"]:
            rel = item["path"]
            if not rel.startswith(prefix) or before.get(rel[len(prefix):]) != item["before_sha256"]:
                raise PipelineError(f"{wid} changed before guarded swap: {rel}")
        after = _files(stage / "library/works" / wid)
        if (any(after.get(item["path"][len(prefix):]) != item["proposed_sha256"] for item in entry["files"])
                or any(after.get(rel) != digest for rel, digest in before.items()
                       if prefix + rel not in {item["path"] for item in entry["files"]})
                or _files(target) != before):
            raise PipelineError(f"{wid} staged generation changed")
        operation = root / "library/.sidecar-operations" / ("four-source-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True)
        incoming, previous = operation / "incoming", operation / "previous"
        shutil.copytree(_io_path(stage / "library/works" / wid), _io_path(incoming))
        if _files(incoming) != after or _files(target) != before:
            raise PipelineError(f"{wid} incoming generation differs")
        journal = {"contract": "ocd-four-complex-source-operation-v1", "work_id": wid,
                   "phase": "prepared", "before": before, "after": after}
        write_json(_io_path(operation / "operation.json"), journal)
        moved, live = False, False
        try:
            target.rename(previous)
            moved = True
            journal["phase"] = "previous-moved"
            write_json(_io_path(operation / "operation.json"), journal)
            incoming.rename(target)
            live = True
            journal["phase"] = "new-live"
            write_json(_io_path(operation / "operation.json"), journal)
            for item in entry["files"]:
                if "/acquisitions/" in item["path"]:
                    validate_acquisition(_io_path(root / item["path"]), root=_io_path(root))
            validate_state(_io_path(target / "state.json"), root=_io_path(root))
            if _files(target) != after:
                raise PipelineError(f"{wid} installed generation differs")
            journal["phase"] = "complete"
            write_json(_io_path(operation / "operation.json"), journal)
        except Exception:
            if moved:
                try:
                    if live:
                        target.rename(operation / "failed")
                    if not previous.is_dir():
                        raise PipelineError(f"{wid} previous generation missing: {previous}")
                    previous.rename(target)
                    if _files(target) != before:
                        raise PipelineError(f"{wid} rollback generation differs")
                    journal["phase"] = "rolled-back"
                    write_json(_io_path(operation / "operation.json"), journal)
                except Exception as rollback_error:
                    journal["phase"] = "recovery-required"
                    journal["rollback_error"] = str(rollback_error)
                    write_json(_io_path(operation / "operation.json"), journal)
                    raise PipelineError(f"{wid} rollback requires recovery: {operation}") from rollback_error
            else:
                journal["phase"] = "failed-before-swap"
                write_json(_io_path(operation / "operation.json"), journal)
            raise
        return {"work_id": wid, "operation": str(operation), "before": before, "after": after}


def reviewed_preflight(root: Path, stage: Path) -> dict[str, Any]:
    root, stage = root.resolve(), stage.resolve()
    result = preflight(root, stage)
    receipt = load_json(_io_path(stage / "receipt.json"))
    pinned = load_json(root / RECEIPT_REL)
    if receipt != pinned:
        raise PipelineError("four-work staged receipt differs from filed reviewed receipt")
    return result


def install(root: Path, stage: Path) -> dict[str, Any]:
    root, stage = root.resolve(), stage.resolve()
    reviewed_preflight(root, stage)
    receipt = load_json(_io_path(stage / "receipt.json"))
    installed = [_install_one(root, stage, entry) for entry in receipt["entries"]]
    result = {"contract": "ocd-four-complex-source-apply-v1",
              "packet_sha256": sha256_file(root / PACKET_REL),
              "stage_receipt_sha256": sha256_file(_io_path(stage / "receipt.json")),
              "installed": installed}
    write_json(_io_path(stage / "apply-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = install(args.repository_root, args.stage)
        print(json.dumps({"installed": [item["work_id"] for item in result["installed"]]}, sort_keys=True))
    else:
        print(json.dumps(reviewed_preflight(args.repository_root, args.stage), sort_keys=True))


if __name__ == "__main__":
    main()
