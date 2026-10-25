"""Preflight or atomically install a reviewed Whitefield spine stage."""
from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path

from build.tools.prepare_whitefield_two_witness_sidecars import CONTRACT, PACKET_REL, WORK_ID, evidence
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError, load_json, sha256_file, write_json
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import validate_record
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.install_accepted import _io_path


RECEIPT_REL = "plans/2026-09-22-source-preflight/whitefield-two-witness-sidecar-stage-20260926.json"


def _tree(directory: Path) -> dict[str, str]:
    directory = _io_path(directory)
    if not directory.is_dir():
        raise PipelineError(f"missing Whitefield work generation: {directory}")
    return {path.relative_to(directory).as_posix(): sha256_file(path)
            for path in directory.rglob("*") if path.is_file()}


def _file(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
        raise PipelineError(f"invalid Whitefield staged path: {relative}")
    return _io_path(root / path)


def _paths() -> set[str]:
    prefix = f"library/works/{WORK_ID}"
    result = {f"{prefix}/work.json", f"{prefix}/state.json", f"{prefix}/SOURCE_CREDIT.md"}
    for label in ("ccel", "gutenberg"):
        edition = f"{prefix}/forms/{WORK_ID}-{label}-retained-en/editions/{WORK_ID}-{label}-retained-electronic"
        result.add(f"{edition}/acquisitions/{WORK_ID}-{label}-acquired.json")
    return result


def preflight(root: Path, staged: Path) -> dict:
    root, staged = root.resolve(), staged.resolve()
    receipt = load_json(_io_path(staged / "receipt.json"))
    pinned = load_json(_io_path(root / RECEIPT_REL))
    packet = load_json(_io_path(root / PACKET_REL))
    if (receipt != pinned or receipt.get("contract") != CONTRACT
            or receipt.get("packet_path") != PACKET_REL
            or receipt.get("packet_sha256") != sha256_file(_io_path(root / PACKET_REL))
            or packet != evidence(root)):
        raise PipelineError("Whitefield packet, source evidence, or receipt differs")
    files = receipt.get("files")
    if not isinstance(files, list) or len(files) != 5:
        raise PipelineError("Whitefield staged file count differs")
    listed = {item.get("path") for item in files if isinstance(item, dict)}
    if listed != _paths() or len(listed) != len(files):
        raise PipelineError("Whitefield staged path set differs")
    prefix = f"library/works/{WORK_ID}/"
    if {prefix + rel for rel in _tree(staged / prefix)} != listed:
        raise PipelineError("Whitefield stage contains unreviewed work files")
    for item in files:
        rel = item["path"]
        proposed, current = _file(staged, rel), _file(root, rel)
        before = sha256_file(current) if current.is_file() else None
        if (not proposed.is_file() or sha256_file(proposed) != item["proposed_sha256"]
                or before != item["before_sha256"]):
            raise PipelineError(f"Whitefield staged/current file changed: {rel}")
        if rel.endswith("/work.json"):
            validate_record("work", load_json(proposed), context=rel)
        elif rel.endswith("/state.json"):
            validate_record("state", load_json(proposed), context=rel)
        elif "/acquisitions/" in rel:
            validate_acquisition(proposed, root=_io_path(staged))
    validate_state(_file(staged, prefix + "state.json"), root=_io_path(staged))
    return receipt


def install(root: Path, staged: Path) -> dict:
    root, staged = root.resolve(), staged.resolve()
    receipt = preflight(root, staged)
    prefix = f"library/works/{WORK_ID}/"
    target = root / "library" / "works" / WORK_ID
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        before = _tree(target)
        if any(before.get(item["path"][len(prefix):]) != item["before_sha256"] for item in receipt["files"]):
            raise PipelineError("Whitefield changed before swap")
        operation = root / "library" / ".sidecar-operations" / ("whitefield-two-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True)
        incoming, previous = operation / "incoming", operation / "previous"
        shutil.copytree(_io_path(target), _io_path(incoming))
        for item in receipt["files"]:
            destination = _file(incoming, item["path"][len(prefix):])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_file(staged, item["path"]), destination)
        after = _tree(incoming)
        proposed = {item["path"][len(prefix):]: item["proposed_sha256"] for item in receipt["files"]}
        if (any(after.get(rel) != digest for rel, digest in proposed.items())
                or any(after.get(rel) != digest for rel, digest in before.items() if rel not in proposed)
                or _tree(target) != before):
            raise PipelineError("Whitefield incoming generation differs")
        journal = {"contract": "ocd-whitefield-two-witness-operation-v1", "work_id": WORK_ID,
                   "phase": "prepared", "before": before, "after": after}
        write_json(_io_path(operation / "operation.json"), journal)
        moved = live = False
        try:
            target.rename(previous)
            moved = True
            journal["phase"] = "previous-moved"
            write_json(_io_path(operation / "operation.json"), journal)
            incoming.rename(target)
            live = True
            journal["phase"] = "new-live"
            write_json(_io_path(operation / "operation.json"), journal)
            for rel in proposed:
                if "/acquisitions/" in rel:
                    validate_acquisition(_file(root, prefix + rel), root=_io_path(root))
            validate_state(_file(root, prefix + "state.json"), root=_io_path(root))
            if _tree(target) != after:
                raise PipelineError("Whitefield installed generation differs")
            journal["phase"] = "complete"
            write_json(_io_path(operation / "operation.json"), journal)
        except Exception:
            if moved:
                try:
                    if live:
                        target.rename(operation / "failed")
                    if not previous.is_dir():
                        raise PipelineError("Whitefield previous generation missing")
                    previous.rename(target)
                    if _tree(target) != before:
                        raise PipelineError("Whitefield rollback generation differs")
                    journal["phase"] = "rolled-back"
                    write_json(_io_path(operation / "operation.json"), journal)
                except Exception as rollback_error:
                    journal["phase"] = "recovery-required"
                    journal["rollback_error"] = str(rollback_error)
                    write_json(_io_path(operation / "operation.json"), journal)
                    raise PipelineError(f"Whitefield rollback requires recovery: {operation}") from rollback_error
            else:
                journal["phase"] = "failed-before-swap"
                write_json(_io_path(operation / "operation.json"), journal)
            raise
        return {"work_id": WORK_ID, "operation": str(operation), "before": before, "after": after}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = install(args.repository_root, args.stage)
        print(json.dumps({"installed": result["work_id"], "operation": result["operation"]}, sort_keys=True))
    else:
        receipt = preflight(args.repository_root, args.stage)
        print(json.dumps({"preflighted": WORK_ID, "files": len(receipt["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
