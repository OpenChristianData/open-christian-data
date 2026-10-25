"""Apply the reviewed Smith edition category, with exact byte guards."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "library/works/smiths-bible-dictionary/work.json"
PROPOSAL = ROOT / "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1"
BEFORE = "2d82a88355c6455c76c799921b9a0c807b5cd24c53e3eb262d37fded4f4f047f"
AFTER = "386cafb583171fb3bf36461a7e0427fb57e292cbf3f528556771d2428d842a81"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    before = WORK.read_bytes()
    successor = (PROPOSAL / "work-category-successor.json").read_bytes()
    if sha(before) != BEFORE or sha(successor) != AFTER:
        raise ValueError("Smith category proposal or current preimage drifted")
    old = json.loads(before)
    new = json.loads(successor)
    old["textual_forms"][0]["editions"][0]["category"] = "reference-entries"
    if old != new:
        raise ValueError("Smith successor contains another change")
    clearance = {
        "contract": "ocd-smith-category-clearance-v1",
        "approved_by": "root-coordinator-exact-proposal-review",
        "review_chunk": "43f109",
        "review_exit_code": 0,
        "scope": "one edition.category field; no other metadata or authority change",
        "preimage_sha256": BEFORE,
        "successor_sha256": AFTER,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    clearance_path = PROPOSAL / "coordinator-category-clearance.json"
    with clearance_path.open("xb") as stream:
        stream.write((json.dumps(clearance, sort_keys=True, separators=(",", ":")) + "\n").encode())
    temporary = WORK.with_name("work.smith-category.tmp")
    with temporary.open("xb") as stream:
        stream.write(successor)
    os.replace(temporary, WORK)
    if sha(WORK.read_bytes()) != AFTER:
        raise ValueError("Smith category readback differs")
    print(json.dumps({"status": "pass", "category_sha256": AFTER, "clearance_sha256": sha(clearance_path.read_bytes())}))


if __name__ == "__main__":
    main()
