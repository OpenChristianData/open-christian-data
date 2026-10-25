"""Retain the exact checked Douay acceptance stage under the durable library."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from ocd_kernel.library._common import io_path
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files

from build.tools.stage_original_douay_current import ROOT, WORK, EDITION


BASE = Path("D:/Library/Open Christian Data/candidate-reviews")
OLD_STAGE = ROOT / ".tmp_audit/original-douay-stage-v7"
OLD_PROMOTED = ROOT / ".tmp_audit/original-douay-promoted-v7"
NEW_STAGE = BASE / "original-douay-current-20261002-v2-stage"
NEW_PROMOTED = BASE / "original-douay-current-20261002-v2-promoted"
LOG = ROOT / "reports/_logs/original-douay-rheims-current-reconciliation-20261002-v1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    base = BASE.resolve(strict=True)
    if any(target.exists() or target.parent.resolve(strict=True) != base for target in (NEW_STAGE, NEW_PROMOTED)):
        raise ValueError("Exact durable Douay stage destinations must be fresh siblings of candidate-reviews")
    original_receipt = (OLD_PROMOTED / "stage-receipt.json").read_bytes()
    receipt = json.loads(original_receipt)
    rollback = json.loads((ROOT / ".tmp_audit/original-douay-rollback-proof.json").read_bytes())
    if (receipt["status"] != "pass" or receipt["work_id"] != "original-douay-rheims"
            or rollback["status"] != "pass" or rollback["stage_receipt_sha256"] != sha(original_receipt)
            or _files(OLD_PROMOTED / WORK) != receipt["after"]
            or _files(ROOT / WORK) != receipt["before"]):
        raise ValueError("Exact promoted stage/rollback/canonical preimage differs")
    shutil.copytree(io_path(OLD_STAGE), io_path(NEW_STAGE))
    shutil.copytree(io_path(OLD_PROMOTED), io_path(NEW_PROMOTED))
    if _files(NEW_STAGE / WORK) != _files(OLD_STAGE / WORK) or _files(NEW_PROMOTED / WORK) != receipt["after"]:
        raise ValueError("Durable copy changed staged or promoted work authority")
    if (NEW_PROMOTED / "stage-receipt.json").read_bytes() != original_receipt:
        raise ValueError("Durable stage receipt changed")
    acceptance = NEW_PROMOTED / EDITION / "acceptance.json"
    validate_acceptance(acceptance, root=NEW_PROMOTED)
    bindings = json.loads((NEW_PROMOTED / "original-douay-notice-bindings.json").read_bytes())["bindings"]
    texts = notice_texts_for_item(NEW_PROMOTED, {"item_id": "original-douay-rheims", "work_id": "original-douay-rheims", "public_notices": bindings}, acceptance)
    if len(texts) != 170:
        raise ValueError("Durable copy changed release notice bindings")
    report = {
        "status": "pass",
        "stage": str(NEW_STAGE),
        "promoted": str(NEW_PROMOTED),
        "stage_receipt_sha256": sha(original_receipt),
        "rollback_sha256": sha((ROOT / ".tmp_audit/original-douay-rollback-proof.json").read_bytes()),
        "promoted_work_files": len(receipt["after"]),
        "notice_bindings": len(texts),
        "candidate_content_sha256": receipt["candidate_content_sha256"],
        "bound_master_sha256": receipt["bound_master_sha256"],
        "canonical_install": False,
    }
    io_path(LOG / "durable-stage-location.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
