"""Guardedly install the reviewed three Expositor companion XML sidecars."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build.tools.install_expositors_sidecars import _file, _install_one, _tree
from build.tools.prepare_expositors_companions import (
    COMPANIONS,
    CONTRACT,
    PACKET_REL,
    PREVIOUS_APPLY_REL,
    PREVIOUS_PACKET_REL,
    companion_rows,
)
from ocd_kernel.library._common import PipelineError, load_json, sha256_file, write_json
from ocd_kernel.library.identities import validate_record
from ocd_kernel.tei.install_accepted import _io_path


RECEIPT_REL = "plans/2026-09-22-source-preflight/expositors-three-companion-sidecar-stage-20260926.json"


def preflight(root: Path, staged: Path) -> dict[str, Any]:
    root, staged = root.resolve(), staged.resolve()
    receipt = load_json(_io_path(staged / "receipt.json"))
    pinned = load_json(_file(root, RECEIPT_REL))
    packet = load_json(_file(root, PACKET_REL))
    if (receipt != pinned or sha256_file(_io_path(staged / "receipt.json")) != sha256_file(_file(root, RECEIPT_REL))
            or receipt.get("contract") != CONTRACT or receipt.get("packet_path") != PACKET_REL
            or receipt.get("packet_sha256") != sha256_file(_file(root, PACKET_REL))
            or receipt.get("sources") != 3 or len(receipt.get("files", [])) != 12
            or packet.get("contract") != CONTRACT
            or packet.get("prior_packet") != {"path": PREVIOUS_PACKET_REL,
                                              "sha256": sha256_file(_file(root, PREVIOUS_PACKET_REL))}
            or packet.get("prior_apply") != {"path": PREVIOUS_APPLY_REL,
                                             "sha256": sha256_file(_file(root, PREVIOUS_APPLY_REL))}):
        raise PipelineError("three-companion stage receipt or packet differs")
    source_rows, before = companion_rows(root)
    if packet.get("source_members") != source_rows or packet.get("before") != before:
        raise PipelineError("retained companion sources or canonical before-state differ")
    allowed = {item["path"] for item in receipt["files"]}
    if len(allowed) != 12:
        raise PipelineError("duplicate staged companion path")
    for item in receipt["files"]:
        relative = item["path"]
        proposed, current = _file(staged, relative), _file(root, relative)
        if (not proposed.is_file() or sha256_file(proposed) != item["proposed_sha256"]
                or (sha256_file(current) if current.is_file() else None) != item["before_sha256"]):
            raise PipelineError(f"staged or current companion file differs: {relative}")
        if relative.endswith("work.json"):
            validate_record("work", load_json(proposed), context=relative)
        elif relative.endswith("state.json"):
            validate_record("state", load_json(proposed), context=relative)
        elif "/acquisitions/" in relative:
            acquisition = load_json(proposed)
            validate_record("acquisition", acquisition, context=relative)
            if acquisition.get("source_path", "").casefold().endswith(".zip"):
                raise PipelineError(f"ZIP package cannot be source: {relative}")
    for wid in COMPANIONS:
        prefix = f"library/works/{wid}/"
        items = [item for item in receipt["files"] if item["path"].startswith(prefix)]
        if len(items) != 4 or any(prefix + relative not in allowed for relative in _tree(staged / prefix)):
            raise PipelineError(f"{wid} staged generation differs from reviewed four-file scope")
        credit = _file(staged, prefix + "SOURCE_CREDIT.md").read_text(encoding="utf-8")
        source = next(row for row in source_rows if row["work_id"] == wid)
        if source["path"] not in credit or "remains unaccounted in this stage" in credit:
            raise PipelineError(f"{wid} source credit did not update the companion volume")
    return receipt


def install(root: Path, staged: Path) -> dict[str, Any]:
    root, staged = root.resolve(), staged.resolve()
    receipt = preflight(root, staged)
    installed = []
    for wid in sorted(COMPANIONS):
        prefix = f"library/works/{wid}/"
        items = [item for item in receipt["files"] if item["path"].startswith(prefix)]
        installed.append(_install_one(root, staged, wid, items))
    result = {"contract": "ocd-expositors-three-companion-sidecar-apply-v1",
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
        print(json.dumps({"preflighted": receipt["sources"], "files": len(receipt["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
