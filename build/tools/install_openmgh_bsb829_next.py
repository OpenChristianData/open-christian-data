"""Preflight or guard-install one exact reviewed bsb829 stage.

The default is read-only. --apply uses the existing journaled work/profile/
manifest transaction and does not refresh a corpus view or release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tools import install_openmgh_bsb830_next as journaled
from build.tools.preflight_openmgh_bsb829_next import preflight
from build.tools.stage_openmgh_bsb829_inspected import ROOT, SELECTED
from ocd_kernel.library._common import PipelineError


PINS = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb829-frozen-pins-20260926.json"
PINS_SHA = "c0d60a7e1fcc209e026b2182b76f153f68aaaba32f94e588346a278b2792d6e6"
RECEIPT_HOME = ROOT / "plans/2026-09-22-source-preflight"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(receipt: Path, *, apply: bool = False) -> dict:
    receipt = receipt.resolve(strict=True)
    if _sha(PINS) != PINS_SHA:
        raise PipelineError("bsb829 frozen pins changed")
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    if pins.get("contract") != "ocd-openmgh-bsb829-frozen-review-pins-v1":
        raise PipelineError("unrecognized bsb829 pins")
    record = json.loads(receipt.read_text(encoding="utf-8"))
    work_id = record.get("work_id")
    expected = RECEIPT_HOME / f"{work_id}-openmgh-bsb829-stage-20260926.json"
    digest = pins["stage_receipts"].get(work_id)
    if (work_id not in SELECTED or digest is None or receipt != expected.resolve(strict=True)
            or _sha(receipt) != digest):
        raise PipelineError("bsb829 stage is outside the exact reviewed receipt set")
    if not apply:
        return preflight(receipt)
    original = journaled.receipt_preflight
    try:
        journaled.receipt_preflight = preflight
        return journaled.install(
            receipt,
            allowed_ids=frozenset({work_id}),
            journal_contract="ocd-openmgh-bsb829-acceptance-install-v1",
            operation_prefix="openmgh-bsb829",
            expected_receipt_sha256=digest,
        )
    finally:
        journaled.receipt_preflight = original


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.receipt, apply=args.apply), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
