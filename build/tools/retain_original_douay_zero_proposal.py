"""Retain the unapplied closed Douay release-compatibility proposal and proofs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".tmp_audit/original-douay-zero-release-proposal"
TARGET = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1/zero-release-proposal-v1"
FILES = [
    "unapplied-closed-zero-release.patch", "proposal-manifest.json",
    "candidate-proof.json", "candidate-actual-master-proof.json",
    "boundary-proof.json", "candidate-jps-compatibility.json",
    "ocd_kernel/projection/categories/bible.py", "schemas/v2/categories/bible.schema.json",
    "prove_candidate.py", "prove_boundaries.py",
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    if TARGET.exists():
        raise FileExistsError("Fresh exact Douay proposal evidence root required")
    manifest = json.loads((SOURCE / "proposal-manifest.json").read_bytes())
    actual = json.loads((SOURCE / "candidate-actual-master-proof.json").read_bytes())
    boundary = json.loads((SOURCE / "boundary-proof.json").read_bytes())
    jps = json.loads((SOURCE / "candidate-jps-compatibility.json").read_bytes())
    if (manifest["status"] != "pass" or manifest["shared_patch_applied"]
            or actual["status"] != "pass" or actual["rows"] != 37181 or actual["numeric_zero"] != 49
            or boundary["status"] != "pass" or jps["status"] != "pass" or jps["rows"] != 23213):
        raise ValueError("Complete unapplied Douay/JPS proposal proof required")
    TARGET.mkdir(parents=True)
    bindings = {}
    for relative in FILES:
        data = (SOURCE / relative).read_bytes()
        destination = TARGET / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        if destination.read_bytes() != data:
            raise ValueError("Durable proposal copy differs: " + relative)
        bindings[relative] = sha(data)
    report = {
        "status": "pass", "shared_patch_applied": False,
        "proposal_root": str(TARGET), "files": bindings,
        "original_douay_source_master_unchanged": True,
        "actual_candidate_master_projection_rows": actual["rows"],
        "candidate_numeric_zero_rows": actual["numeric_zero"],
        "candidate_jps_positive_rows": jps["rows"],
        "candidate_normal_and_streaming_reader_rows": json.loads((SOURCE / "candidate-proof.json").read_bytes())["normal_and_streaming_reader_rows"],
    }
    (TARGET / "retention.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
