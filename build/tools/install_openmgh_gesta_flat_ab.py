"""Preflight or install four exact Gesta/flat-ab stages after review.

The default is read-only. Each work has one pinned stage receipt; the guarded
work/profile/manifest transaction checks that pin again under the work lock.
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
    "gesta-domni-lantberti": (
        "gesta-openmgh-derived-acceptance-stage-20260926.json",
        "8a150c285f76d39b57223ec8f86ddda901a0d8e8ac236c95cf55b370661cba98",
        "ocd-openmgh-gesta-derived-acceptance-stage-v1",
    ),
    "defense-of-priests-sons": (
        "defense-openmgh-flat-ab-acceptance-stage-20260926.json",
        "1398e7c724c9f439576c4ed853e0f1309aa98b0ea348a40cd7912461151acc90",
        "ocd-openmgh-bsb830-flat-ab-poetry-stage-v1",
    ),
    "exiled-monk-calamities-of-the-church-of-liege": (
        "exiled-monk-openmgh-flat-ab-acceptance-stage-20260926.json",
        "921d51b08aa172f4cfb41419b466c5a42da5e1b74796935c214265530309d853",
        "ocd-openmgh-bsb830-flat-ab-poetry-stage-v1",
    ),
    "hunald-carmen-de-anulo-et-baculo": (
        "hunald-openmgh-flat-ab-acceptance-stage-20260926.json",
        "15faac4d48bceb4cee1208f41738c834d515f0a7107deb68983f71a7749852c5",
        "ocd-openmgh-bsb830-flat-ab-poetry-stage-v1",
    ),
}


def pinned_receipt(work_id: str) -> tuple[Path, str]:
    if work_id not in PINS:
        raise PipelineError(f"work outside exact Gesta/flat-ab install route: {work_id}")
    name, digest, contract = PINS[work_id]
    receipt = ROOT / "plans/2026-09-22-source-preflight" / name
    raw = receipt.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise PipelineError(f"reviewed stage receipt hash changed: {work_id}")
    record = json.loads(raw)
    if record.get("work_id") != work_id or record.get("contract") != contract:
        raise PipelineError(f"reviewed stage identity or contract changed: {work_id}")
    return receipt, digest


def preflight(work_id: str) -> dict:
    receipt, _digest = pinned_receipt(work_id)
    return stage_preflight(receipt)


def install(work_id: str) -> dict:
    receipt, digest = pinned_receipt(work_id)
    stage_preflight(receipt)
    is_verse = work_id != "gesta-domni-lantberti"
    return install_transaction(
        receipt, allowed_ids=frozenset({work_id}),
        journal_contract=("ocd-openmgh-flat-ab-poetry-install-v1" if is_verse
                          else "ocd-openmgh-gesta-install-v1"),
        operation_prefix=("openmgh-flat-ab" if is_verse else "openmgh-gesta"),
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
