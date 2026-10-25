"""Guardedly install a reviewed direct-raw nine-work sidecar stage."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from build.tools.prepare_direct_raw_nine_sidecars import WORKS, stage
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError, load_json, sha256_file, write_json
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import load_state, validate_state
from ocd_kernel.tei.install_accepted import _io_path


RECEIPT_PATH = Path("plans/2026-09-22-source-preflight/direct-raw-nine-sidecar-stage-20260926.json")


def _tree(directory: Path) -> dict[str, str]:
    if not _io_path(directory).is_dir():
        raise PipelineError(f"missing work generation: {directory}")
    return {path.relative_to(_io_path(directory)).as_posix(): sha256_file(path)
            for path in _io_path(directory).rglob("*") if path.is_file()}


def _file(stage_root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
        raise PipelineError(f"invalid staged path: {relative}")
    return _io_path(stage_root / path)


def preflight(root: Path, packet: Path, staged: Path) -> dict[str, Any]:
    """Rebuild the proposed 39 files and check all pinned source bytes before mutation."""
    root, staged = root.resolve(), staged.resolve()
    receipt = load_json(_io_path(staged / "receipt.json"))
    pinned = load_json(_io_path(root / RECEIPT_PATH))
    if (receipt != pinned or sha256_file(_io_path(staged / "receipt.json")) != sha256_file(_io_path(root / RECEIPT_PATH))
            or receipt.get("contract") != "ocd-direct-raw-nine-stage-v1"
            or receipt.get("packet_sha256") != sha256_file(packet)
            or len(receipt.get("files", [])) != 39
            or receipt.get("entries") != list(WORKS)):
        raise PipelineError("nine-work stage receipt or packet binding differs")
    state_rel = f"library/works/{WORKS[0]}/state.json"
    staged_state = load_state(_file(staged, state_rel))
    timestamp = staged_state["targets"][-1]["updated_at"]
    temporary = Path(tempfile.mkdtemp(prefix="direct-nine-preflight-", dir=staged.parent))
    try:
        regenerated = temporary / "stage"
        expected = stage(root, packet, regenerated, timestamp=timestamp)
        if expected != receipt:
            raise PipelineError("regenerated stage differs from reviewed receipt")
        for item in receipt["files"]:
            rel = item["path"]
            if (sha256_file(_file(staged, rel)) != item["proposed_sha256"]
                    or sha256_file(_file(regenerated, rel)) != item["proposed_sha256"]):
                raise PipelineError(f"staged file differs: {rel}")
            current = _file(root, rel)
            before = sha256_file(current) if current.is_file() else None
            if before != item["before_sha256"]:
                raise PipelineError(f"current work differs: {rel}")
    finally:
        if temporary.resolve().parent != staged.parent:
            raise PipelineError("preflight scratch path escaped stage parent")
        shutil.rmtree(_io_path(temporary))
    allowed = {item["path"] for item in receipt["files"]}
    for wid in WORKS:
        prefix = f"library/works/{wid}/"
        work_items = {item["path"][len(prefix):]: item for item in receipt["files"]
                      if item["path"].startswith(prefix)}
        if len(work_items) != (7 if wid == WORKS[0] else 4):
            raise PipelineError(f"{wid} staged work file set differs")
        before_tree = _tree(root / "library/works" / wid)
        if any(before_tree.get(rel) != item["before_sha256"] for rel, item in work_items.items()):
            raise PipelineError(f"{wid} work changed during preflight")
        for relative in _tree(staged / "library/works" / wid):
            if prefix + relative not in allowed:
                raise PipelineError(f"{wid} stage contains unreviewed file: {relative}")
    return receipt


def _install_one(root: Path, staged: Path, wid: str, items: list[dict[str, Any]],
                 *, validate_live: bool = True) -> dict[str, Any]:
    """Swap one complete work generation; restore it on any post-move failure."""
    target = root / "library/works" / wid
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        before = _tree(target)
        prefix = f"library/works/{wid}/"
        if any(before.get(item["path"][len(prefix):]) != item["before_sha256"] for item in items):
            raise PipelineError(f"{wid} changed before swap")
        operation = root / "library/.sidecar-operations" / ("direct-nine-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True)
        incoming, previous = operation / "incoming", operation / "previous"
        shutil.copytree(_io_path(target), _io_path(incoming))
        for item in items:
            rel = item["path"]
            suffix = Path(rel[len(prefix):])
            source = _file(staged, rel)
            destination = _io_path(incoming / suffix)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        after = _tree(incoming)
        if (any(after.get(item["path"][len(prefix):]) != item["proposed_sha256"] for item in items)
                or any(after.get(rel) != digest for rel, digest in before.items()
                       if prefix + rel not in {item["path"] for item in items})
                or _tree(target) != before):
            raise PipelineError(f"{wid} incoming generation differs")
        journal = {"contract": "ocd-direct-raw-nine-sidecar-operation-v1", "work_id": wid,
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
            if validate_live:
                acquisitions = [item["path"] for item in items if "/acquisitions/" in item["path"]]
                for acquisition in acquisitions:
                    validate_acquisition(_file(root, acquisition), root=_io_path(root))
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


def install(root: Path, packet: Path, staged: Path) -> dict[str, Any]:
    root, staged = root.resolve(), staged.resolve()
    receipt = preflight(root, packet, staged)
    installed = []
    for wid in WORKS:
        prefix = f"library/works/{wid}/"
        items = [item for item in receipt["files"] if item["path"].startswith(prefix)]
        installed.append(_install_one(root, staged, wid, items))
    result = {"contract": "ocd-direct-raw-nine-sidecar-apply-v1",
              "packet_sha256": sha256_file(packet),
              "stage_receipt_sha256": sha256_file(_io_path(staged / "receipt.json")),
              "installed": installed}
    write_json(_io_path(staged / "apply-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true", help="install the exact reviewed 39-file stage")
    args = parser.parse_args()
    if args.apply:
        result = install(args.repository_root, args.packet, args.stage)
        print(json.dumps({"installed": len(result["installed"])}, sort_keys=True))
    else:
        receipt = preflight(args.repository_root, args.packet, args.stage)
        print(json.dumps({"preflighted": len(receipt["entries"]), "files": len(receipt["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
