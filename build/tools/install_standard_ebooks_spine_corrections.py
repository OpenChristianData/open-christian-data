"""Preflight or atomically install one reviewed Standard Ebooks spine correction."""
from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path

from build.tools.prepare_standard_ebooks_spine_corrections import CONTRACT, IDS, PACKET_REL, evidence
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError, load_json, sha256_file, write_json
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import validate_record
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.install_accepted import _io_path


RECEIPT_REL = "plans/2026-09-22-source-preflight/standard-ebooks-four-spine-correction-stage-20260926.json"


def _tree(directory: Path) -> dict[str, str]:
    directory = _io_path(directory)
    if not directory.is_dir():
        raise PipelineError(f"missing work generation: {directory}")
    return {path.relative_to(directory).as_posix(): sha256_file(path)
            for path in directory.rglob("*") if path.is_file()}


def _file(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != relative:
        raise PipelineError(f"invalid staged path: {relative}")
    return _io_path(root / path)


def preflight(root: Path, staged: Path, work_id: str | None = None) -> dict:
    root, staged = root.resolve(), staged.resolve()
    receipt = load_json(_io_path(staged / "receipt.json"))
    pinned = load_json(_io_path(root / RECEIPT_REL))
    packet = load_json(_io_path(root / PACKET_REL))
    if work_id is not None and work_id not in IDS:
        raise PipelineError(f"unexpected work: {work_id}")
    selected = (work_id,) if work_id else IDS
    current = evidence(root, selected)
    expected_packet = dict(packet)
    expected_packet["works"] = [row for row in packet["works"] if row["work_id"] in selected]
    if (receipt != pinned or receipt.get("contract") != CONTRACT
            or receipt.get("packet_path") != PACKET_REL
            or receipt.get("packet_sha256") != sha256_file(_io_path(root / PACKET_REL))
            or expected_packet != current):
        raise PipelineError("Standard Ebooks correction packet, sources, or receipt differ")
    files = receipt.get("files")
    if not isinstance(files, list) or len(files) != 20:
        raise PipelineError("Standard Ebooks correction staged file count differs")
    expected_paths = set()
    for row in packet["works"]:
        paths = row["paths"]
        expected_paths.update(paths[key] for key in ("work", "acquisition", "descriptor", "support", "credit"))
    listed = {item.get("path") for item in files if isinstance(item, dict)}
    if listed != expected_paths or len(listed) != len(files):
        raise PipelineError("Standard Ebooks correction staged path set differs")
    for selected_work in selected:
        prefix = f"library/works/{selected_work}/"
        stage_paths = {prefix + rel for rel in _tree(staged / prefix)}
        if stage_paths != {rel for rel in expected_paths if rel.startswith(prefix)}:
            raise PipelineError(f"{selected_work} stage contains unreviewed work files")
    for item in files:
        rel = item["path"]
        if not any(rel.startswith(f"library/works/{selected_work}/") for selected_work in selected):
            continue
        proposed, current = _file(staged, rel), _file(root, rel)
        before = sha256_file(current) if current.is_file() else None
        if (not proposed.is_file() or sha256_file(proposed) != item["proposed_sha256"]
                or before != item["before_sha256"]):
            raise PipelineError(f"Standard Ebooks staged/current file changed: {rel}")
        if rel.endswith("/work.json"):
            validate_record("work", load_json(proposed), context=rel)
        elif "/acquisitions/" in rel:
            validate_acquisition(proposed, root=_io_path(staged))
    return receipt


def install_one(root: Path, staged: Path, work_id: str) -> dict:
    if work_id not in IDS:
        raise PipelineError(f"unexpected work: {work_id}")
    receipt = preflight(root, staged, work_id)
    prefix = f"library/works/{work_id}/"
    items = [item for item in receipt["files"] if item["path"].startswith(prefix)]
    target = root / "library" / "works" / work_id
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        before = _tree(target)
        if any(before.get(item["path"][len(prefix):]) != item["before_sha256"] for item in items):
            raise PipelineError(f"{work_id} changed before swap")
        operation = root / "library" / ".sidecar-operations" / ("se-spine-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True)
        incoming, previous = operation / "incoming", operation / "previous"
        shutil.copytree(_io_path(target), _io_path(incoming))
        for item in items:
            destination = _file(incoming, item["path"][len(prefix):])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_file(staged, item["path"]), destination)
        after = _tree(incoming)
        proposed = {item["path"][len(prefix):]: item["proposed_sha256"] for item in items}
        if (any(after.get(rel) != digest for rel, digest in proposed.items())
                or any(after.get(rel) != digest for rel, digest in before.items() if rel not in proposed)
                or _tree(target) != before):
            raise PipelineError(f"{work_id} incoming generation differs")
        journal = {"contract": "ocd-standard-ebooks-spine-operation-v1", "work_id": work_id,
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
            for item in items:
                if "/acquisitions/" in item["path"]:
                    validate_acquisition(_file(root, item["path"]), root=_io_path(root))
            validate_state(_file(root, prefix + "state.json"), root=_io_path(root))
            if _tree(target) != after:
                raise PipelineError(f"{work_id} installed generation differs")
            journal["phase"] = "complete"
            write_json(_io_path(operation / "operation.json"), journal)
        except Exception:
            if moved:
                try:
                    if live:
                        target.rename(operation / "failed")
                    if not previous.is_dir():
                        raise PipelineError(f"{work_id} previous generation missing")
                    previous.rename(target)
                    if _tree(target) != before:
                        raise PipelineError(f"{work_id} rollback generation differs")
                    journal["phase"] = "rolled-back"
                    write_json(_io_path(operation / "operation.json"), journal)
                except Exception as rollback_error:
                    journal["phase"] = "recovery-required"
                    journal["rollback_error"] = str(rollback_error)
                    write_json(_io_path(operation / "operation.json"), journal)
                    raise PipelineError(f"{work_id} rollback requires recovery: {operation}") from rollback_error
            else:
                journal["phase"] = "failed-before-swap"
                write_json(_io_path(operation / "operation.json"), journal)
            raise
        return {"work_id": work_id, "operation": str(operation), "before": before, "after": after}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--work", choices=IDS)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        if not args.work:
            parser.error("--apply requires --work")
        result = install_one(args.repository_root.resolve(), args.stage.resolve(), args.work)
        print(json.dumps({"installed": result["work_id"], "operation": result["operation"]}, sort_keys=True))
    else:
        receipt = preflight(args.repository_root, args.stage)
        print(json.dumps({"preflighted": list(IDS), "files": len(receipt["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
