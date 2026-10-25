"""Record coordinator clearance for the exact closed Douay release patch."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1"
PROPOSAL = LOG / "zero-release-proposal-v1"
PINS = {
    "ocd_kernel/projection/categories/bible.py": ("2c890668641e932d4ada645b787f484e6f579e11b87aa5cc910057115f827780", "ca13e93ff1f4374cf177f1443ea34cf6d55efbedb53de87028002ee125a2e6bb"),
    "schemas/v2/categories/bible.schema.json": ("069ef09c7872b4c3ef750ac261aeba1db8cc974329d978aaae3a727fdc05c9f2", "945364d802a3fa614287d84ae52680534a9ca238d11bb0aa5ad31b783df8f9a6"),
}
PATCH_SHA = "d2c59105e36b4510c1d4e27bd9999c8f33e0fe530d4ccc84861d92dc0c56b61f"


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    retention = json.loads((PROPOSAL / "retention.json").read_bytes())
    if retention["status"] != "pass" or retention["shared_patch_applied"]:
        raise ValueError("Durable reviewed proposal differs")
    if sha((PROPOSAL / "unapplied-closed-zero-release.patch").read_bytes()) != PATCH_SHA:
        raise ValueError("Reviewed patch SHA differs")
    for relative, (before, after) in PINS.items():
        if sha((ROOT / relative).read_bytes()) != before or sha((PROPOSAL / relative).read_bytes()) != after:
            raise ValueError("Shared preimage or proposed successor differs: " + relative)
    target = LOG / "coordinator-zero-release-patch-clearance.json"
    if target.exists():
        raise FileExistsError("Coordinator zero release clearance already exists")
    record = {
        "status": "cleared-for-scoped-two-file-apply",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": "root coordinator",
        "reviewed_patch_sha256": PATCH_SHA,
        "preimage_successor": {relative: {"before_sha256": before, "after_sha256": after} for relative, (before, after) in PINS.items()},
        "durable_proposal": str(PROPOSAL),
        "durable_proposal_retention_sha256": sha((PROPOSAL / "retention.json").read_bytes()),
        "reviewed_evidence": ["closed schema and lexical zero profile", "producer and independent checker boundary cases", "37,181 actual accepted-master candidate rows", "23,213 JPS positive rows", "typed Arrow and normal/streaming 37,181-row roundtrip"],
        "source_tei_and_install_unchanged": True,
        "public_publication": False,
    }
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
