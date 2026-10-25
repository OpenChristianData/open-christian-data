"""Preflight one exact LIB-051 work cohort, then optionally install serially.

Each work keeps its own durable swap journal. A later failure reports completed
work IDs rather than claiming an all-or-nothing multi-work transaction.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from build.tools.install_lib051_owen_acceptance import install, preflight
from build.tools.stage_lib051_owen_acceptance import CHILDREN, FINAL_CHILDREN
from ocd_kernel.library._common import PipelineError


CONTRACT = "ocd-lib051-seven-work-stage-pins-v1"
FINAL_CONTRACT = "ocd-lib051-final-three-stage-pins-v1"


def _pins(path: Path, expected_sha256: str) -> list[tuple[str, Path, str]]:
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise PipelineError("LIB-051 batch pins file differs from caller hash")
    data = json.loads(raw)
    cohort = {CONTRACT: CHILDREN, FINAL_CONTRACT: FINAL_CHILDREN}.get(data.get("contract"))
    if cohort is None or data.get("status") != "staged-only":
        raise PipelineError("LIB-051 batch pins contract differs")
    entries = data.get("stages")
    if not isinstance(entries, list) or len(entries) != len(cohort):
        raise PipelineError("LIB-051 batch requires every distinct work stage in its cohort")
    result: list[tuple[str, Path, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise PipelineError("LIB-051 batch stage entry must be an object")
        work_id, stage, receipt_sha = (entry.get(key) for key in (
            "work_id", "stage_root", "stage_receipt_sha256",
        ))
        if not isinstance(work_id, str) or not isinstance(stage, str) or not isinstance(receipt_sha, str):
            raise PipelineError("LIB-051 batch stage pin fields differ")
        result.append((work_id, Path(stage), receipt_sha))
    if [work_id for work_id, _, _ in result] != sorted(cohort):
        raise PipelineError("LIB-051 batch work order or distinct identity differs")
    return result


def preflight_all(pins_path: Path, pins_sha256: str, *, root_override: Path | None = None) -> dict:
    entries = _pins(pins_path, pins_sha256)
    checks = [preflight(work_id, stage, digest, root_override=root_override)
              for work_id, stage, digest in entries]
    return {"contract": "ocd-lib051-owen-batch-preflight-v1", "status": "pass-read-only",
            "work_ids": [item["work_id"] for item in checks],
            "stage_receipts": [item["stage_receipt_sha256"] for item in checks],
            "projection_rows": sum(item["projection_rows"] for item in checks),
            "canonical_action": "none"}


def install_all(pins_path: Path, pins_sha256: str, *, root_override: Path | None = None) -> dict:
    check = preflight_all(pins_path, pins_sha256, root_override=root_override)
    completed: list[dict] = []
    for work_id, stage, digest in _pins(pins_path, pins_sha256):
        try:
            completed.append(install(work_id, stage, digest, root_override=root_override))
        except (PipelineError, OSError, ValueError) as exc:
            done = [item["work_id"] for item in completed]
            raise PipelineError(f"LIB-051 serial batch stopped after completed works {done}: {exc}") from exc
    return {"contract": "ocd-lib051-owen-batch-install-v1", "status": "installed-serially",
            "preflight": check, "results": completed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pins", required=True, type=Path)
    parser.add_argument("--pins-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = (install_all(args.pins, args.pins_sha256) if args.apply
              else preflight_all(args.pins, args.pins_sha256))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
