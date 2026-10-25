"""Preflight or guardedly install one reviewed accepted Standard Ebooks rebind."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from pathlib import Path

from build.tools.prepare_accepted_standard_ebooks_spine_rebind import (
    CONTRACT, IDS, PACKET_REL, _one, _tree,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError, canonical_bytes, load_json, sha256_file, write_json
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _io_path


RECEIPT_REL = "plans/2026-09-22-source-preflight/accepted-standard-ebooks-three-spine-rebind-stage-20260926.json"


def preflight(root: Path, staged: Path, work_id: str | None = None) -> dict:
    root, staged = root.resolve(), staged.resolve()
    if work_id is not None and work_id not in IDS:
        raise PipelineError(f"unexpected accepted Standard Ebooks work: {work_id}")
    selected = (work_id,) if work_id else IDS
    receipt = load_json(_io_path(staged / "receipt.json"))
    pinned = load_json(_io_path(root / RECEIPT_REL))
    packet = load_json(_io_path(root / PACKET_REL))
    if (receipt != pinned or receipt.get("contract") != CONTRACT
            or receipt.get("packet_path") != PACKET_REL
            or receipt.get("packet_sha256") != sha256_file(_io_path(root / PACKET_REL))
            or packet.get("contract") != CONTRACT):
        raise PipelineError("accepted Standard Ebooks packet or receipt differs")
    if ([row.get("work_id") for row in packet.get("works", [])] != list(IDS)
            or [row.get("work_id") for row in receipt.get("works", [])] != list(IDS)):
        raise PipelineError("accepted Standard Ebooks staged work set differs")
    for selected_id in selected:
        packet_row = next(row for row in packet["works"] if row["work_id"] == selected_id)
        receipt_row = next(row for row in receipt["works"] if row["work_id"] == selected_id)
        if packet_row != _one(root, selected_id):
            raise PipelineError(f"{selected_id} source or before generation differs")
        before_tree = _tree(root / f"library/works/{selected_id}")
        after_tree = _tree(staged / f"library/works/{selected_id}")
        before_digest = hashlib.sha256(canonical_bytes(before_tree)).hexdigest()
        after_digest = hashlib.sha256(canonical_bytes(after_tree)).hexdigest()
        if (packet_row["before_tree"] != before_tree
                or receipt_row["before_tree_sha256"] != before_digest
                or receipt_row["proposed_tree_sha256"] != after_digest
                or receipt_row["proposed_tree"] != after_tree):
            raise PipelineError(f"{selected_id} complete generation differs")
        expected_changes = [{"path": f"library/works/{selected_id}/{rel}",
                             "before_sha256": before_tree.get(rel), "proposed_sha256": after_tree.get(rel)}
                            for rel in sorted(set(before_tree) | set(after_tree))
                            if before_tree.get(rel) != after_tree.get(rel)]
        if receipt_row["changed_files"] != expected_changes:
            raise PipelineError(f"{selected_id} changed-file diff differs")
        paths = packet_row["paths"]
        original_acceptance = load_json(_io_path(root / paths["acceptance"]))
        revised_acceptance = load_json(_io_path(staged / paths["acceptance"]))
        if (original_acceptance["identity"] != revised_acceptance["identity"]
                or original_acceptance["decision"]["human_decision"] != revised_acceptance["decision"]["human_decision"]
                or original_acceptance["decision"]["agent_assessment"]["status"]
                   != revised_acceptance["decision"]["agent_assessment"]["status"]):
            raise PipelineError(f"{selected_id} acceptance identity or decision changed")
        validate_acceptance(staged / paths["acceptance"], root=staged)
    return receipt


def install_one(root: Path, staged: Path, work_id: str) -> dict:
    root, staged = root.resolve(), staged.resolve()
    receipt = preflight(root, staged, work_id)
    row = next(row for row in receipt["works"] if row["work_id"] == work_id)
    target = root / "library" / "works" / work_id
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        before = _tree(target)
        if hashlib.sha256(canonical_bytes(before)).hexdigest() != row["before_tree_sha256"]:
            raise PipelineError(f"{work_id} changed before swap")
        operation = root / "library" / ".sidecar-operations" / ("se-accepted-spine-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True)
        incoming, previous = operation / "incoming", operation / "previous"
        shutil.copytree(_io_path(staged / f"library/works/{work_id}"), _io_path(incoming))
        after = _tree(incoming)
        if after != row["proposed_tree"] or _tree(target) != before:
            raise PipelineError(f"{work_id} incoming generation differs")
        journal = {"contract": "ocd-accepted-standard-ebooks-spine-operation-v1",
                   "work_id": work_id, "phase": "prepared", "before": before, "after": after}
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
            paths = next(item for item in load_json(_io_path(root / PACKET_REL))["works"]
                         if item["work_id"] == work_id)["paths"]
            validate_acceptance(root / paths["acceptance"], root=root)
            if _tree(target) != after:
                raise PipelineError(f"{work_id} installed generation differs")
            journal["phase"] = "complete"
            write_json(_io_path(operation / "operation.json"), journal)
        except BaseException:
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
                except BaseException as rollback_error:
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
        result = install_one(args.repository_root, args.stage, args.work)
        print(json.dumps({"installed": result["work_id"], "operation": result["operation"]}, sort_keys=True))
    else:
        result = preflight(args.repository_root, args.stage, args.work)
        print(json.dumps({"preflighted": args.work or list(IDS),
                          "changed_files": sum(len(row["changed_files"]) for row in result["works"])}, sort_keys=True))


if __name__ == "__main__":
    main()
