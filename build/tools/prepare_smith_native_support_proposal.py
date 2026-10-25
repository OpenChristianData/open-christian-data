"""Save an unapplied Smith-only profile extension to the frozen lexical adapter."""

from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "ocd_kernel/projection/categories/reference_entries.py"
OUT = ROOT / "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1/native-support-proposal"
BEFORE = "2211d08e5726fdabac379485bf4dedac68f1130f5f43432f226089222070d857"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    original = MODULE.read_bytes()
    if sha(original) != BEFORE:
        raise ValueError("Frozen reference adapter preimage changed")
    newline = "\r\n" if b"\r\n" in original else "\n"
    text = original.decode("utf-8").replace("\r\n", "\n")
    changes = [
        (
            '_HITCHCOCK_ROOT_ID = "hitchcocks-bible-names-dictionary-candidate"',
            '''_HITCHCOCK_ROOT_ID = "hitchcocks-bible-names-dictionary-candidate"
_SMITH_PROFILE = "smith-native-lexical-v1"
_SMITH_IDENTITY = {
    "work_id": "smiths-bible-dictionary",
    "textual_form_id": "smiths-bible-dictionary-retained-electronic",
    "edition_id": "smiths-bible-dictionary-retained-electronic-witness",
}
_SMITH_ROOT_ID = "smiths-bible-dictionary-candidate"''',
        ),
        (
            '        _HITCHCOCK_PROFILE: (_HITCHCOCK_IDENTITY, _HITCHCOCK_ROOT_ID),',
            '        _HITCHCOCK_PROFILE: (_HITCHCOCK_IDENTITY, _HITCHCOCK_ROOT_ID),\n        _SMITH_PROFILE: (_SMITH_IDENTITY, _SMITH_ROOT_ID),',
        ),
    ]
    for old, new in changes:
        if text.count(old) != 1:
            raise ValueError(f"Unexpected profile insertion match count: {old}")
        text = text.replace(old, new)
    successor = text.replace("\n", newline).encode("utf-8")
    compile(successor, str(MODULE), "exec")
    diff = "".join(difflib.unified_diff(original.decode().splitlines(True), successor.decode().splitlines(True), fromfile="before/reference_entries.py", tofile="after/reference_entries.py")).encode()
    details = {
        "contract": "ocd-smith-native-support-proposal-v1",
        "status": "unapplied-proposal",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "module": MODULE.relative_to(ROOT).as_posix(),
        "before_sha256": BEFORE,
        "after_sha256": sha(successor),
        "diff_sha256": sha(diff),
        "scope": "Add only exact Smith retained electronic profile/three-field identity/root ID to existing closed native lexical adapter. Easton, Hitchcock, and default routes unchanged.",
        "producer_checker_contract": "Existing generic native path validates entry/form/orth/sense/ordered-def IDs and attributes, reads literal headword and definition text, and compares independent lxml traversal and inventory.",
        "schema_change": False,
        "source_proof": "reports/_logs/smith-coordinator-source-review-20261002-v1/review.json",
        "rights_clearance": "unresolved",
        "publication_authorized": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "reference_entries.before.py": original,
        "reference_entries.after.py": successor,
        "patch.diff": diff,
        "design.json": (json.dumps(details, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
    }
    for name, payload in artifacts.items():
        target = OUT / name
        if target.exists():
            if target.read_bytes() != payload:
                raise FileExistsError(f"Existing Smith proposal artifact differs: {target}")
        else:
            target.write_bytes(payload)
    print(json.dumps({"status": "unapplied-proposal", "before_sha256": BEFORE, "after_sha256": sha(successor), "diff_sha256": sha(diff)}))


if __name__ == "__main__":
    main()
