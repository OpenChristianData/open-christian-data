"""Preflight or guardedly install one exact bsb750 prose acceptance stage.

The default is read-only. Apply rechecks the reviewed receipt under the work
lock, journal-swaps work/profile/manifest, and checks actual-master prose.
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
CONTRACT = "ocd-openmgh-bsb750-next-prose-stage-v1"
RECEIPT_HASHES = {
    "passio-sancti-memorii": "4be38c9188dc943d168d7077d78746e1de561a997e7386db5302042c18ad45af",
    "passio-sancti-quirini-tegernseensis": "f5f21fff51640aeb8b3140e73d101ab12386c39a0575e2805004968735f75558",
    "vita-sanctae-genovefae": "3ea10f4f8ad3c0772af9e712f43a2ca3e874646f80b6bcc74ad3ba3ba3d0b6b5",
    "vita-sancti-apollinaris-valentinensis": "e39a44c9e6f01159fcb870d10247219737ea8ab9267b6847b7e76e9defd21ba9",
    "vita-sancti-aviti": "46480f9e2716e0c2755c76481f593c96d8b8a7c231925c2eb6a86d4a395bec73",
    "vita-sancti-carileffi": "6289fe5bf683453f88aabfea12dc1f195d0360b808e988fa66e714b5b786cdc9",
    "vita-sancti-dalmatii": "2d55e330fb8eba4ce42c2d4fc639210fd6ad7fe509cf72a8d7c53899315961e8",
    "vita-sancti-eptadii": "15bdb52b60d440807058092c36c13c0a9a6b571cd7b61be0401f5864970bfc56",
    "vita-sancti-gaugerici": "809fe41f73f8409eae8d312d5d854563a21103dfeb6b4a69fcdcf5698801a854",
    "vita-sancti-iuniani": "c524bc73a2c4f1ea45808fea95ad2dc8e1939fa01e3e4d667af60e50f32d7d24",
    "vita-sancti-melanii": "b62efb18e384243aae997f4aca656244f6d292f6d369fcc185a268fb50e81787",
    "vita-sancti-viviani-santonensis": "791de49b5dfea7609ed7964e509fcde8268b1a10ca29efac4f10c4f71d22686c",
}


def pinned_receipt(work_id: str) -> tuple[Path, str]:
    if work_id not in RECEIPT_HASHES:
        raise PipelineError(f"work outside exact bsb750 install route: {work_id}")
    receipt = (ROOT / "plans/2026-09-22-source-preflight"
               / f"{work_id}-openmgh-bsb750-acceptance-stage-20260926.json")
    raw = receipt.read_bytes()
    digest = RECEIPT_HASHES[work_id]
    if hashlib.sha256(raw).hexdigest() != digest:
        raise PipelineError(f"reviewed stage receipt hash changed: {work_id}")
    record = json.loads(raw)
    if (record.get("work_id") != work_id or record.get("contract") != CONTRACT
            or record.get("category") != "prose"):
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
        journal_contract="ocd-openmgh-bsb750-next-install-v1",
        operation_prefix="openmgh-bsb750-next",
        expected_receipt_sha256=digest,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(RECEIPT_HASHES))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(install(args.work_id) if args.apply else preflight(args.work_id),
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
