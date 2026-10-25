"""Prove bounded accepted-work rollback in a fresh isolated Douay fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from ocd_kernel.library._common import io_path
from ocd_kernel.tei.install_accepted import _files, install_accepted_work

from build.tools.stage_original_douay_current import ROOT, WORK


class ExpectedInterruption(RuntimeError):
    pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--promoted", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    promoted = args.promoted.resolve(strict=True)
    fixture = args.fixture.absolute()
    if fixture.exists():
        raise FileExistsError("Fresh exact rollback fixture required")
    receipt_bytes = (promoted / "stage-receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    if receipt["status"] != "pass" or receipt["work_id"] != "original-douay-rheims":
        raise ValueError("Complete frozen stage receipt required")
    shutil.copytree(io_path(ROOT / WORK), io_path(fixture / WORK))
    if _files(fixture / WORK) != receipt["before"]:
        raise ValueError("Fixture original preimage differs")
    original_work = io_path(fixture / WORK / "work.json").read_bytes()
    revised_work = io_path(promoted / WORK / "work.json").read_bytes()
    io_path(fixture / WORK / "work.json").write_bytes(revised_work)
    prerequisite = _files(fixture / WORK)

    def interrupt(checkpoint: str) -> None:
        if checkpoint == "after-new-live":
            raise ExpectedInterruption(checkpoint)

    rejected = False
    try:
        install_accepted_work(fixture, promoted, work_id="original-douay-rheims", fail_at=interrupt)
    except ExpectedInterruption:
        rejected = True
    if not rejected:
        raise ValueError("Requested post-new-live interruption was not reached")
    if _files(fixture / WORK) != prerequisite:
        raise ValueError("Installer did not restore exact fixture prerequisite")
    io_path(fixture / WORK / "work.json").write_bytes(original_work)
    if _files(fixture / WORK) != receipt["before"]:
        raise ValueError("Fixture metadata restoration differs from exact canonical preimage")
    report = {
        "status": "pass",
        "checkpoint": "after-new-live",
        "stage_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "before": receipt["before"],
        "after": receipt["after"],
        "post_failure_prerequisite_restored": True,
        "original_canonical_preimage_restored": True,
        "canonical_work_changed": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"before", "after"}}, indent=2))


if __name__ == "__main__":
    main()
