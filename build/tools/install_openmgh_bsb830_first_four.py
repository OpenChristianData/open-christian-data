"""Preflight or guardedly install one frozen bsb830 first-four stage.

The source-family pin index fixes each reviewed receipt, candidate, and master.
Apply delegates the locked work/profile/manifest transaction to the maintained
bsb830 installer; it does not refresh the corpus view.
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
PINS = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb830-first-four-stage-pins-20260927.json"
PINS_SHA = "0fb944bbb50a752266604943762e6e3b3b67225ba9c88d44fe91877adc0cebb6"
BATCH_SHA = "3b70eafa4501a7bc56ac73c04e9233e916d424f09bca719751df15e0e333ec5f"
SOURCE_SHA = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
IDS = frozenset({
    "question-on-the-sacraments-of-heretics",
    "tractatus-de-scismate",
    "treatise-in-favor-of-clerical-marriage",
    "theobald-of-etampes-letter-to-roscelin",
})


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pinned_receipt(work_id: str) -> tuple[Path, str]:
    if work_id not in IDS or _sha(PINS) != PINS_SHA:
        raise PipelineError("work or frozen bsb830 pin index changed")
    pins = json.loads(PINS.read_bytes())
    entries = pins.get("entries")
    if (pins.get("contract") != "ocd-openmgh-bsb830-first-four-stage-pins-v1"
            or pins.get("source_path") != "raw/openmgh/bsb00000830/tei/bsb00000830.xml"
            or pins.get("source_sha256") != SOURCE_SHA
            or pins.get("candidate_batch") != "plans/2026-09-22-source-preflight/openmgh-bsb830-first-four-inspected-20260927.json"
            or pins.get("candidate_batch_sha256") != BATCH_SHA
            or not isinstance(entries, list) or len(entries) != 4
            or any(not isinstance(item, dict) for item in entries)
            or {item.get("work_id") for item in entries} != IDS
            or len({item.get("receipt") for item in entries}) != 4):
        raise PipelineError("frozen bsb830 pin index is invalid")
    entry = next(item for item in entries if item["work_id"] == work_id)
    stage_root = Path(pins["stage_root"]).resolve(strict=True)
    receipt = (stage_root / entry["receipt"]).resolve(strict=True)
    if receipt.parent != stage_root or _sha(receipt) != entry["receipt_sha256"]:
        raise PipelineError("exact reviewed bsb830 receipt changed")
    record = json.loads(receipt.read_bytes())
    if (record.get("work_id") != work_id
            or record.get("source_path") != pins["source_path"]
            or record.get("source_sha256") != SOURCE_SHA
            or record.get("original_inspection_receipt") != pins["candidate_batch"]
            or record.get("original_inspection_receipt_sha256") != BATCH_SHA
            or record.get("original_candidate_sha256") != entry["original_candidate_sha256"]
            or record.get("accepted_master_sha256") != entry["accepted_master_sha256"]
            or record.get("category") != "prose"
            or record.get("installation") != "not-performed"):
        raise PipelineError("reviewed bsb830 stage differs from frozen source/master pins")
    return receipt, entry["receipt_sha256"]


def preflight(work_id: str) -> dict:
    receipt, _digest = pinned_receipt(work_id)
    return stage_preflight(receipt)


def install(work_id: str) -> dict:
    receipt, digest = pinned_receipt(work_id)
    stage_preflight(receipt)
    return install_transaction(
        receipt, allowed_ids=frozenset({work_id}),
        journal_contract="ocd-openmgh-bsb830-first-four-install-v1",
        operation_prefix="openmgh-bsb830-first-four",
        expected_receipt_sha256=digest,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(IDS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(install(args.work_id) if args.apply else preflight(args.work_id),
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
