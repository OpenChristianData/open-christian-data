"""Preflight or guardedly install one exact bsb830 remainder stage.

The default is read-only. Apply rechecks the reviewed receipt under the work
lock, journal-swaps work/profile/manifest, and checks the installed category.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tools.install_openmgh_bsb830_next import install as install_transaction
from build.tools.preflight_openmgh_bsb830_next import preflight as stage_preflight
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[2]
PINS = {
    "merseburg-fragment-on-clerical-celibacy": (
        "9a559d4b6baf1407b48f2558d8c2109c2abe53f2bc8047eed2812a0aca9d054f",
        "ocd-openmgh-bsb830-derived-acceptance-stage-v1", "prose"),
    "poem-on-the-simoniacal-heresy": (
        "6c1b4052759a7e15014bcac83c0dff285cc3e17c7969238d813720a7bebb72e3",
        "ocd-openmgh-bsb830-flat-ab-poetry-stage-v1", "poetry"),
    "satire-against-the-people-of-metz": (
        "1f78b1497138115be9396549664ce0d57a22de48a62ed4dacdc99e10f8c2914f",
        "ocd-openmgh-bsb830-flat-ab-poetry-stage-v1", "poetry"),
}


def pinned_receipt(work_id: str) -> tuple[Path, str]:
    if work_id not in PINS:
        raise PipelineError(f"work outside exact bsb830 remainder install route: {work_id}")
    digest, contract, category = PINS[work_id]
    receipt = (ROOT / "plans/2026-09-22-source-preflight"
               / f"{work_id}-openmgh-bsb830-remainder-stage-20260926.json")
    raw = receipt.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise PipelineError(f"reviewed stage receipt hash changed: {work_id}")
    record = json.loads(raw)
    if (record.get("work_id") != work_id or record.get("contract") != contract
            or record.get("category") != category):
        raise PipelineError(f"reviewed stage identity, contract, or category changed: {work_id}")
    return receipt, digest


def preflight(work_id: str) -> dict:
    receipt, _digest = pinned_receipt(work_id)
    return stage_preflight(receipt)


def install(work_id: str) -> dict:
    receipt, digest = pinned_receipt(work_id)
    stage_preflight(receipt)
    return install_transaction(
        receipt, allowed_ids=frozenset({work_id}),
        journal_contract="ocd-openmgh-bsb830-remainder-install-v1",
        operation_prefix="openmgh-bsb830-remainder",
        expected_receipt_sha256=digest,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(PINS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(install(args.work_id) if args.apply else preflight(args.work_id),
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
