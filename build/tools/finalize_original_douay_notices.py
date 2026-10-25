"""Preserve every shipped source byte and add one terminal-LF Markdown divider."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _files

from build.tools.stage_original_douay_current import ROOT, WORK, EDITION


LOG = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1"
PROMOTED = Path("D:/Library/Open Christian Data/candidate-reviews/original-douay-current-20261002-v2-promoted")
FREEZE_SHA = "bba49ab37609479bb821d98c37ba5f181098d4c525f9fbf208967169b988c4eb"


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    freeze_bytes = (LOG / "coordinator-install-freeze.json").read_bytes()
    freeze = json.loads(freeze_bytes)
    if sha(freeze_bytes) != FREEZE_SHA or _files(ROOT / WORK) != freeze["after"]:
        raise ValueError("Installed Douay work differs from frozen generation")
    original_bindings = json.loads((PROMOTED / "original-douay-notice-bindings.json").read_bytes())["bindings"]
    if len(original_bindings) != 170 or original_bindings[0]["notice_sha256"] != freeze["full_paired_credit_sha256"]:
        raise ValueError("Original source-bound notice set differs")
    final_bindings = [dict(original_bindings[0])]
    changes: list[tuple[Path, bytes, bytes]] = []
    suffixes: dict[int, int] = {}
    for item in original_bindings[1:]:
        relative = item["notice_path"]
        target = ROOT / relative
        before = target.read_bytes()
        if sha(before) != item["notice_sha256"] or not before.endswith(b"\n"):
            raise ValueError("Canonical notice differs from reviewed derivative: " + relative)
        trailing = len(before) - len(before.rstrip(bytes([10])))
        suffixes[trailing] = suffixes.get(trailing, 0) + 1
        after = before + (b"\n" if trailing == 1 else b"") + b"---\n"
        if not after.endswith(b"\n") or after.endswith(b"\n\n") or not after.startswith(before):
            raise ValueError("Terminal format changed source wording: " + relative)
        final = dict(item)
        final["notice_sha256"] = sha(after)
        final_bindings.append(final)
        changes.append((target, before, after))
    applied: list[tuple[Path, bytes]] = []
    try:
        for target, before, after in changes:
            target.write_bytes(after)
            applied.append((target, before))
        texts = notice_texts_for_item(ROOT, {
            "item_id": "original-douay-rheims", "work_id": "original-douay-rheims",
            "public_notices": final_bindings,
        }, ROOT / EDITION / "acceptance.json")
        if len(texts) != 170 or _files(ROOT / WORK) != freeze["after"]:
            raise ValueError("Final notice gate or installed work changed")
    except Exception:
        for target, before in reversed(applied):
            target.write_bytes(before)
        raise
    proof = {
        "status": "pass",
        "work_id": "original-douay-rheims",
        "frozen_work_sha256": freeze["bound_master_sha256"],
        "original_notice_bindings_sha256": freeze["notice_bindings_sha256"],
        "native_derivative_proof_sha256": freeze["markdown_derivative_proof_sha256"],
        "notice_count": len(final_bindings),
        "preserved_context_prefixes": len(changes),
        "trailing_source_lfs_before": suffixes,
        "suffix_added": "Markdown horizontal rule separator, followed by exactly one terminal LF",
        "literal_nonverse_utf8_bytes_unchanged": freeze["literal_nonverse_utf8_bytes"],
        "source_fields_unchanged": freeze["native_nonverse_fields"],
        "bindings": final_bindings,
    }
    target = LOG / "final-private-release-notice-bindings.json"
    if target.exists():
        raise FileExistsError("Final private-release notice binding already exists")
    target.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in proof.items() if key != "bindings"}, indent=2))


if __name__ == "__main__":
    main()
