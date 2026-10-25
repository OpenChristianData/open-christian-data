"""Apply the reviewed Smith-only lexical profile after Hitchcock release freeze."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "ocd_kernel/projection/categories/reference_entries.py"
LOG = ROOT / "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1"
PROPOSED = LOG / "native-support-proposal/reference_entries.after.py"
REVIEW = LOG / "coordinator-adapter-review.json"
HITCHCOCK_AUDIT = ROOT / "reports/_logs/hitchcocks-bible-names-dictionary-private-release-20261002-v1/coordinator-current-binding-audit.json"
BEFORE = "2211d08e5726fdabac379485bf4dedac68f1130f5f43432f226089222070d857"
AFTER = "37addf99c4327533995f185d15b3a0b56ce63fb4ea6e2f7a4584e94995e25e08"
REVIEW_SHA = "366862e0ede1a461954affb8ad514dd9c2676a084351c4c159aa9623b29c30a7"
HITCHCOCK_AUDIT_SHA = "6226bd08fccb09b43d7f11ce13212bd13024d42ef7491d53a72d56f6cf7d68df"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    original = MODULE.read_bytes()
    successor = PROPOSED.read_bytes()
    if sha(original) != BEFORE or sha(successor) != AFTER:
        raise ValueError("Smith adapter preimage or exact reviewed successor drifted")
    if sha(REVIEW.read_bytes()) != REVIEW_SHA:
        raise ValueError("Smith coordinator adapter review drifted")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if review["status"] != "reviewed-unapplied" or review["before_sha256"] != BEFORE or review["after_sha256"] != AFTER:
        raise ValueError("Smith coordinator adapter scope differs")
    if sha(HITCHCOCK_AUDIT.read_bytes()) != HITCHCOCK_AUDIT_SHA:
        raise ValueError("Hitchcock closure has not frozen the shared adapter window")
    clearance = {
        "contract": "ocd-smith-native-adapter-apply-clearance-v1",
        "status": "cleared-for-one-exact-registry-change",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "module": MODULE.relative_to(ROOT).as_posix(),
        "before_sha256": BEFORE,
        "after_sha256": AFTER,
        "coordinator_adapter_review_sha256": REVIEW_SHA,
        "hitchcock_final_audit_sha256": HITCHCOCK_AUDIT_SHA,
        "scope": "Smith exact profile, three-field identity and root ID only",
    }
    clearance_path = LOG / "coordinator-adapter-apply-clearance.json"
    with clearance_path.open("xb") as stream:
        stream.write((json.dumps(clearance, sort_keys=True, separators=(",", ":")) + "\n").encode())
    temporary = MODULE.with_name("reference_entries.smith.tmp")
    with temporary.open("xb") as stream:
        stream.write(successor)
    os.replace(temporary, MODULE)
    if sha(MODULE.read_bytes()) != AFTER:
        raise ValueError("Smith shared adapter readback differs")
    freeze = {
        "contract": "ocd-smith-native-adapter-applied-freeze-v1",
        "status": "applied-readback-pass",
        "module": MODULE.relative_to(ROOT).as_posix(),
        "before_sha256": BEFORE,
        "after_sha256": AFTER,
        "clearance_sha256": sha(clearance_path.read_bytes()),
        "hitchcock_final_audit_sha256": HITCHCOCK_AUDIT_SHA,
    }
    freeze_path = LOG / "adapter-applied-freeze.json"
    with freeze_path.open("xb") as stream:
        stream.write((json.dumps(freeze, sort_keys=True, separators=(",", ":")) + "\n").encode())
    print(json.dumps({"status": "applied-readback-pass", "after_sha256": AFTER, "freeze_sha256": sha(freeze_path.read_bytes())}))


if __name__ == "__main__":
    main()
