"""Preflight or guardedly install a reviewed eight-work large-source stage."""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from build.tools.prepare_large_source_sets import CONTRACT, PACKET_REL, SOURCES, binding
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError, load_json, sha256_file, write_json
from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition
from ocd_kernel.library.identities import validate_record
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.install_accepted import _io_path


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


def preflight(root: Path, staged: Path, *, verify_deferred: bool = False) -> dict[str, Any]:
    root, staged = root.resolve(), staged.resolve()
    receipt = load_json(_io_path(staged / "receipt.json"))
    packet = load_json(_file(root, PACKET_REL))
    if (receipt.get("contract") != CONTRACT or packet.get("contract") != CONTRACT
            or receipt.get("packet_path") != PACKET_REL
            or receipt.get("packet_sha256") != sha256_file(_file(root, PACKET_REL))
            or len(packet.get("works", [])) != len(SOURCES)
            or len(receipt.get("files", [])) != 4 * len(SOURCES)):
        raise PipelineError("large-source receipt or packet differs")
    files = receipt["files"]
    allowed = {item["path"] for item in files}
    if len(allowed) != len(files):
        raise PipelineError("duplicate staged large-source path")
    work_ids = {row["work_id"] for row in packet["works"]}
    if work_ids != set(SOURCES):
        raise PipelineError("large-source work census differs")
    for row in packet["works"]:
        wid = row["work_id"]
        if row.get("live_file_hash_check") not in {"checked-this-run", "deferred-to-install-preflight"}:
            raise PipelineError(f"{wid} lacks explicit file verification status")
        current_info, members = binding(root, wid, verify_files=verify_deferred and row["live_file_hash_check"] == "deferred-to-install-preflight")
        for key in ("manifest_path", "manifest_sha256", "source_id", "manifest_primary_count", "source_member_count", "source_member_bytes", "support_member_count", "support_members", "member_order_sha256", "nonprimary_authority_count", "scope_warnings"):
            if row.get(key) != current_info.get(key):
                raise PipelineError(f"{wid} manifest binding differs: {key}")
        if len(members) != row["source_member_count"]:
            raise PipelineError(f"{wid} member count differs")
        for support in row["support_members"]:
            support_path = _file(root, support["path"])
            if (not support_path.is_file() or support_path.stat().st_size != support["bytes"]
                    or sha256_file(support_path) != support["sha256"]):
                raise PipelineError(f"{wid} support member differs: {support['path']}")
        prefix = f"library/works/{wid}/"
        items = [item for item in files if item["path"].startswith(prefix)]
        if len(items) != 4 or any(prefix + rel not in allowed for rel in _tree(staged / prefix)):
            raise PipelineError(f"{wid} staged generation differs")
    for item in files:
        rel = item["path"]
        staged_file, current_file = _file(staged, rel), _file(root, rel)
        if (not staged_file.is_file() or sha256_file(staged_file) != item["proposed_sha256"]
                or (sha256_file(current_file) if current_file.is_file() else None) != item["before_sha256"]):
            raise PipelineError(f"staged or current file differs: {rel}")
        if rel.endswith("/work.json"):
            validate_record("work", load_json(staged_file), context=rel)
        elif rel.endswith("/state.json"):
            validate_record("state", load_json(staged_file), context=rel)
        elif "/acquisitions/" in rel:
            acq = load_json(staged_file)
            validate_record("acquisition", acq, context=rel)
            if acq.get("source_kind") != "retained-member-set" or any(x["path"].lower().endswith(".zip") for x in acq["retained_files"]):
                raise PipelineError(f"{rel} does not bind original non-ZIP members")
            descriptor = _file(staged, acq["source_path"])
            if (descriptor.read_bytes() != source_member_set_bytes(acq)
                    or sha256_file(descriptor) != acq["source_sha256"]
                    or descriptor.stat().st_size != acq["source_bytes"]):
                raise PipelineError(f"{rel} source descriptor differs")
    return receipt


def _install_one(root: Path, staged: Path, wid: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    target = root / "library/works" / wid
    prefix = f"library/works/{wid}/"
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        before = _tree(target)
        if any(before.get(item["path"][len(prefix):]) != item["before_sha256"] for item in items):
            raise PipelineError(f"{wid} changed before swap")
        operation = root / "library/.sidecar-operations" / ("large-source-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True)
        incoming, previous = operation / "incoming", operation / "previous"
        shutil.copytree(_io_path(target), _io_path(incoming))
        for item in items:
            destination = _file(incoming, item["path"][len(prefix):])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_file(staged, item["path"]), destination)
        after = _tree(incoming)
        if (any(after.get(item["path"][len(prefix):]) != item["proposed_sha256"] for item in items)
                or any(after.get(rel) != digest for rel, digest in before.items()
                       if prefix + rel not in {item["path"] for item in items})
                or _tree(target) != before):
            raise PipelineError(f"{wid} incoming generation differs")
        journal = {"contract": "ocd-large-source-sidecar-operation-v1", "work_id": wid,
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
                        raise PipelineError(f"{wid} previous generation missing")
                    previous.rename(target)
                    if _tree(target) != before:
                        raise PipelineError(f"{wid} restored generation differs")
                    journal["phase"] = "rolled-back"
                    write_json(_io_path(operation / "operation.json"), journal)
                except Exception as exc:
                    journal["phase"] = "recovery-required"
                    journal["rollback_error"] = str(exc)
                    write_json(_io_path(operation / "operation.json"), journal)
                    raise PipelineError(f"{wid} rollback requires recovery: {operation}") from exc
            else:
                journal["phase"] = "failed-before-swap"
                write_json(_io_path(operation / "operation.json"), journal)
            raise
        return {"work_id": wid, "operation": str(operation), "before": before, "after": after}


def install(root: Path, staged: Path) -> dict[str, Any]:
    root, staged = root.resolve(), staged.resolve()
    receipt = preflight(root, staged, verify_deferred=True)
    installed = []
    for wid in sorted(SOURCES):
        prefix = f"library/works/{wid}/"
        items = [item for item in receipt["files"] if item["path"].startswith(prefix)]
        installed.append(_install_one(root, staged, wid, items))
    result = {"contract": "ocd-large-source-sidecar-apply-v1", "packet_sha256": sha256_file(_file(root, PACKET_REL)),
              "stage_receipt_sha256": sha256_file(_io_path(staged / "receipt.json")), "installed": installed}
    write_json(_io_path(staged / "apply-receipt.json"), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.repository_root, args.stage) if args.apply else preflight(args.repository_root, args.stage)
    print(json.dumps({"installed" if args.apply else "preflighted": len(result["installed"]) if args.apply else len(SOURCES)}, sort_keys=True))


if __name__ == "__main__":
    main()
