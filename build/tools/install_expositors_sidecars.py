"""Guardedly install a reviewed 39-member Expositor source-accounting stage."""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from build.tools.prepare_expositors_sidecars import (
    CONTRACT,
    PACKET_REL,
    audit,
    outside_profile,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError, load_json, sha256_file, write_json
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import validate_record
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.install_accepted import _io_path


RECEIPT_REL = "plans/2026-09-22-source-preflight/expositors-39-member-sidecar-stage-20260926.json"


def _file(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
        raise PipelineError(f"invalid staged path: {relative}")
    return _io_path(root / path)


def _tree(directory: Path) -> dict[str, str]:
    directory = _io_path(directory)
    if not directory.is_dir():
        raise PipelineError(f"missing work generation: {directory}")
    return {path.relative_to(directory).as_posix(): sha256_file(path)
            for path in directory.rglob("*") if path.is_file()}


def preflight(root: Path, staged: Path) -> dict[str, Any]:
    root, staged = root.resolve(), staged.resolve()
    receipt = load_json(_io_path(staged / "receipt.json"))
    pinned = load_json(_file(root, RECEIPT_REL))
    packet = load_json(_file(root, PACKET_REL))
    if (receipt != pinned or sha256_file(_io_path(staged / "receipt.json")) != sha256_file(_file(root, RECEIPT_REL))
            or receipt.get("contract") != CONTRACT or receipt.get("packet_path") != PACKET_REL
            or receipt.get("packet_sha256") != sha256_file(_file(root, PACKET_REL))
            or receipt.get("source_members") != 39 or receipt.get("author_cohorts") != 22
            or len(receipt.get("files", [])) != 105 or packet.get("contract") != CONTRACT):
        raise PipelineError("Expositor stage receipt or packet differs")
    members, refs = audit(root)
    if (packet.get("source_members") != members
            or packet.get("source_manifest_and_profile_refs") != refs
            or packet.get("outside_pinned_profiles") != outside_profile(root, members)):
        raise PipelineError("Expositor retained source census differs from reviewed packet")
    work_ids = {row["work_id"] for row in members}
    if len(work_ids) != 22 or set(packet.get("before", {})) != work_ids:
        raise PipelineError("Expositor work census differs from reviewed packet")
    allowed = {item["path"] for item in receipt["files"]}
    if len(allowed) != 105:
        raise PipelineError("duplicate staged Expositor path")
    for item in receipt["files"]:
        relative = item["path"]
        staged_file, current = _file(staged, relative), _file(root, relative)
        if (not staged_file.is_file() or sha256_file(staged_file) != item["proposed_sha256"]
                or (sha256_file(current) if current.is_file() else None) != item["before_sha256"]):
            raise PipelineError(f"staged or current file differs: {relative}")
        if relative.endswith("work.json"):
            validate_record("work", load_json(staged_file), context=relative)
        elif relative.endswith("state.json"):
            validate_record("state", load_json(staged_file), context=relative)
        elif "/acquisitions/" in relative:
            acquisition = load_json(staged_file)
            validate_record("acquisition", acquisition, context=relative)
            if acquisition.get("source_path", "").casefold().endswith(".zip"):
                raise PipelineError(f"ZIP package cannot be source: {relative}")
    for wid in sorted(work_ids):
        prefix = f"library/works/{wid}/"
        items = [item for item in receipt["files"] if item["path"].startswith(prefix)]
        expected = 3 + sum(row["work_id"] == wid for row in members)
        if len(items) != expected:
            raise PipelineError(f"{wid} staged generation file count differs")
        if any(prefix + relative not in allowed for relative in _tree(staged / prefix)):
            raise PipelineError(f"{wid} has an unreviewed staged file")
        if (packet["before"][wid]["work"] != sha256_file(_file(root, prefix + "work.json"))
                or packet["before"][wid]["state"] != sha256_file(_file(root, prefix + "state.json"))):
            raise PipelineError(f"{wid} changed since packet creation")
    return receipt


def _install_one(root: Path, staged: Path, wid: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    target = root / "library/works" / wid
    prefix = f"library/works/{wid}/"
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        before = _tree(target)
        if any(before.get(item["path"][len(prefix):]) != item["before_sha256"] for item in items):
            raise PipelineError(f"{wid} changed before swap")
        operation = root / "library/.sidecar-operations" / ("expositors-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True)
        incoming, previous = operation / "incoming", operation / "previous"
        shutil.copytree(_io_path(target), _io_path(incoming))
        for item in items:
            destination = _file(incoming, item["path"][len(prefix):])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_file(staged, item["path"]), destination)
        after = _tree(incoming)
        if (any(after.get(item["path"][len(prefix):]) != item["proposed_sha256"] for item in items)
                or any(after.get(relative) != digest for relative, digest in before.items()
                       if prefix + relative not in {item["path"] for item in items})
                or _tree(target) != before):
            raise PipelineError(f"{wid} incoming generation differs")
        journal = {"contract": "ocd-expositors-sidecar-operation-v1", "work_id": wid,
                   "phase": "prepared", "before": before, "after": after}
        write_json(_io_path(operation / "operation.json"), journal)
        moved = False
        live = False
        try:
            target.rename(previous)
            moved = True
            journal["phase"] = "previous-moved"
            write_json(_io_path(operation / "operation.json"), journal)
            incoming.rename(target)
            live = True
            journal["phase"] = "new-live"
            write_json(_io_path(operation / "operation.json"), journal)
            for item in items:
                if "/acquisitions/" in item["path"]:
                    validate_acquisition(_file(root, item["path"]), root=_io_path(root))
            validate_state(_file(root, prefix + "state.json"), root=_io_path(root))
            if _tree(target) != after:
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
                    if _tree(target) != before:
                        raise PipelineError(f"{wid} restored generation differs")
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


def install(root: Path, staged: Path) -> dict[str, Any]:
    root, staged = root.resolve(), staged.resolve()
    receipt = preflight(root, staged)
    work_ids = sorted({row["path"].split("/")[2] for row in receipt["files"]})
    installed = []
    for wid in work_ids:
        prefix = f"library/works/{wid}/"
        items = [item for item in receipt["files"] if item["path"].startswith(prefix)]
        installed.append(_install_one(root, staged, wid, items))
    result = {"contract": "ocd-expositors-sidecar-apply-v1",
              "packet_sha256": sha256_file(_file(root, PACKET_REL)),
              "stage_receipt_sha256": sha256_file(_io_path(staged / "receipt.json")),
              "installed": installed}
    write_json(_io_path(staged / "apply-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = install(args.repository_root, args.stage)
        print(json.dumps({"installed": len(result["installed"])}, sort_keys=True))
    else:
        receipt = preflight(args.repository_root, args.stage)
        print(json.dumps({"preflighted": receipt["author_cohorts"], "files": len(receipt["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
