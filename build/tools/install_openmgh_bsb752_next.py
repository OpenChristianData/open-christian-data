"""Preflight or install one of twelve exact bsb752 narrative stages.

The default is read-only. An apply uses the established guarded work/profile/
manifest transaction and rechecks the reviewed receipt hash under its work lock.
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
CONTRACT = "ocd-openmgh-bsb752-next-prose-stage-v1"
RECEIPT_HASHES = {
    "passio-sancti-germani-grandivallensis": "dd919adcd27ddf70a1e00d34e3174354a538bc3f547f6cf9785363af23435a24",
    "passio-sancti-praeiecti": "2be828b89d959d4b8792f0187d6edf94feabdd096d80a897b351401daab9156b",
    "passio-sanctorum-kiliani-et-sociorum": "6acd290a363bfa5e5257cff4e75a7f00dae3913851a7371bf09997926ecf7040",
    "revelatio-beati-baronti": "20b69eaf0287dd33ed6315c714bf37cdd1cf04ff26a9588a37b4e3925b5da5f1",
    "transitus-sancti-condedi": "400373a95eb36c7ae28dd50de255717a3fd38506959f11c68f36de4eb0ac8345",
    "vita-beati-audoini": "52e50cd06a81149f31e374ffde0dc85b5d6d35b95300a6c49d28d0004656fab5",
    "vita-sanctae-sadalbergae": "2d282e0b9a9caae1e5e41cf898031673381d354f2112b65acf95158f263b288a",
    "vita-sancti-ermenlandi": "abdff2696d8333796b9adb213d2a7cfcbcdc012458739fd3c7ef75c469096106",
    "vita-sancti-frodoberti": "e0d39edb0ddea83262df3d0681699dbd4a37df9372266ba4bcd9a1590ce11d3f",
    "vita-sancti-memmii": "d604fc2387baf8a8ba7b9b631d8c82cdb3a936e33dac1573a62d0f0822113f8b",
    "vita-sancti-menelei": "93a732bb53a5207f19e37546b3563e6775512413993a719dd5e83ef6abf3e782",
    "vita-sancti-wandregiseli": "9273c6a2387240241d5f172da51b1b94586ccce622de4ea79d54393bc2b962c8",
}


def pinned_receipt(work_id: str) -> tuple[Path, str]:
    if work_id not in RECEIPT_HASHES:
        raise PipelineError(f"work outside exact bsb752 narrative install route: {work_id}")
    receipt = (ROOT / "plans/2026-09-22-source-preflight"
               / f"{work_id}-openmgh-bsb752-acceptance-stage-20260926.json")
    raw = receipt.read_bytes()
    digest = RECEIPT_HASHES[work_id]
    if hashlib.sha256(raw).hexdigest() != digest:
        raise PipelineError(f"reviewed stage receipt hash changed: {work_id}")
    record = json.loads(raw)
    if record.get("work_id") != work_id or record.get("contract") != CONTRACT:
        raise PipelineError(f"reviewed stage identity or contract changed: {work_id}")
    return receipt, digest


def preflight(work_id: str) -> dict:
    receipt, _digest = pinned_receipt(work_id)
    return stage_preflight(receipt)


def install(work_id: str) -> dict:
    receipt, digest = pinned_receipt(work_id)
    stage_preflight(receipt)
    return install_transaction(
        receipt, allowed_ids=frozenset({work_id}),
        journal_contract="ocd-openmgh-bsb752-narrative-install-v1",
        operation_prefix="openmgh-bsb752-narrative",
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
