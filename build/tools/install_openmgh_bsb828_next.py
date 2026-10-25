"""Preflight or guarded-install one exact inspected bsb00000828 stage.

The default command is read-only. Applying swaps one complete work generation,
its source manifest, and its reconstruction profile under the shared journaled
transaction. No corpus view or release is generated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build.tools.install_openmgh_bsb830_next import install
from build.tools.preflight_openmgh_bsb830_next import preflight
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[2]
RECEIPT_DIGESTS = {
    "wido-monk-letter-to-archbishop-of-milan": "61adb92805e2940a2f988525627f7dab8e745653b9409f04e20303a7dbb580b4",
    "humbert-three-books-against-simoniacs": "a0702531b8ffeeaefaff64e47b5a0757ba1dfbad5c10acfce0381922e59a8c12",
    "pseudo-udalric-letter-on-clerical-continence": "5bdfc1dee29d089030a51e41ec8aa5f7f3c2e6a8d9ac8bc8e40684595c30a166",
    "gebhard-of-salzburg-letter-to-hermann": "31c52a0e450d97f85b9596a736e62d4d764b716b8357fbe51ca97df9f1432ac0",
    "letter-to-hildebrand-under-theoderic-rubric": "5285f8df9547be2a451e2394e12155a97481cfabbb01dc528919fc7212dd4f8f",
    "peter-crassus-defense-of-henry-iv": "14cc9291e6f6a7cf47dd32dc5eafeb256d5148f37b74defeb51bad2109134073",
    "liber-canonum-against-henry": "75ce3ea537c4ce5ba598f0bef6b504cff1ed1f0e35eabd98d69ca1bb62b95958",
    "anselm-of-lucca-against-wibert": "9dd64a7e29a715f51355868cba34f255172f9a3112bb4090bc17f209f5c5d60d",
    "wido-of-ferrara-on-hildebrands-schism": "24616b11e038ee5c23efe7016005e39c865a5c618bb025532327e5993afb93db",
    "bonizo-of-sutri-liber-ad-amicum": "fb9768d483b87d427098ad703ab6a0d26025db7956a5da57aaabfa875b6f2d9a",
    "clement-decree-to-orthodox-bishops": "68d696523346bd1178697edff70b08b0406b59956491485b8d761eed9cd28e75",
}
RECEIPT_HOME = ROOT / "plans/2026-09-22-source-preflight"


def _receipt_path(work_id: str) -> Path:
    stem = "wido-monk-letter" if work_id == "wido-monk-letter-to-archbishop-of-milan" else work_id
    return RECEIPT_HOME / f"{stem}-openmgh-bsb828-stage-20260926.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(receipt: Path, *, apply: bool = False) -> dict:
    receipt = receipt.resolve(strict=True)
    record = json.loads(receipt.read_text(encoding="utf-8"))
    work_id = record.get("work_id")
    if (work_id not in RECEIPT_DIGESTS
            or receipt != _receipt_path(work_id).resolve(strict=True)
            or _sha(receipt) != RECEIPT_DIGESTS[work_id]):
        raise PipelineError("bsb828 stage is outside the exact reviewed receipt set")
    if apply:
        return install(
            receipt,
            allowed_ids=frozenset({work_id}),
            journal_contract="ocd-openmgh-bsb828-derived-acceptance-install-v1",
            operation_prefix="openmgh-bsb828",
            expected_receipt_sha256=RECEIPT_DIGESTS[work_id],
        )
    return preflight(receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.receipt, apply=args.apply), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
