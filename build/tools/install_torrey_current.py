"""Guarded one-work installation of the reviewed Torrey technical master."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, install_accepted_work


ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / ".t"
WORK = Path("library/works/torreys-topical-textbook")
EDITION = WORK / "forms/torreys-topical-textbook-retained-electronic/editions/torreys-topical-textbook-retained-electronic-witness"
REPORTS = ROOT / "reports/_logs/torrey-current-reconciliation-20261002-v1"
STAGE_RECEIPT_SHA = "fa8ac8d148569bdb3f809b1f4c1358e8eb908e687dc9797a0b15dc1b1509ede2"
ROLLBACK_SHA = "b77b1f988d50c521c9b0e83c2bc16f33b88ba30a9f2bb0aa095cef8b9f101129"
ADAPTER_SHA = "350431664aa1c29c9dd8e22eb0b47bd2f8bb40d1f866e7f4659d2b13d3be4261"
MASTER_SHA = "06817b56c133dddd431309a0ec7b4659d4d8b66a78501953db75d9101cbb3c95"
ACCEPTANCE_SHA = "c4264703a2a8629e66f8e8bedf2a770e2ed7540ae180a7f5c3ed01e633ef2a7a"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(f"Torrey install result already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    result_path = REPORTS / "canonical-install-result.json"
    if result_path.exists():
        raise FileExistsError("Torrey canonical install already has a result; inspect before rerun")
    stage_receipt_path = REPORTS / "staged-acceptance.json"
    rollback_path = REPORTS / "install-rollback-proof.json"
    if (sha(stage_receipt_path) != STAGE_RECEIPT_SHA
            or sha(rollback_path) != ROLLBACK_SHA
            or sha(ROOT / "ocd_kernel/projection/categories/topical_indexes.py") != ADAPTER_SHA):
        raise ValueError("Torrey reviewed stage, rollback, or adapter binding drifted")
    staged = json.loads(stage_receipt_path.read_text(encoding="utf-8"))
    rollback = json.loads(rollback_path.read_text(encoding="utf-8"))
    if (staged.get("status") != "staged-only" or staged.get("stage_root") != str(STAGE)
            or staged.get("master_sha256") != MASTER_SHA
            or staged.get("acceptance_sha256") != ACCEPTANCE_SHA
            or staged.get("canonical_install_performed") is not False):
        raise ValueError("Torrey exact staged acceptance differs")
    if (rollback.get("status") != "pass" or rollback.get("checkpoint") != "after-new-live"
            or rollback.get("journal_phase") != "rolled-back"
            or rollback.get("canonical_work_unchanged") is not True
            or rollback.get("before") != staged["current_work_before"]
            or rollback.get("after") != staged["staged_work_after"]):
        raise ValueError("Torrey guarded rollback proof differs")
    if (_files(ROOT / WORK) != staged["current_work_before"]
            or _files(STAGE / WORK) != staged["staged_work_after"]):
        raise ValueError("Torrey canonical preimage or promoted stage drifted")
    if any(path.endswith(("acceptance.json", "master.tei.xml")) for path in _files(ROOT / WORK)):
        raise ValueError("Torrey canonical work already has accepted authority")
    stage_acceptance = STAGE / EDITION / "acceptance.json"
    if (sha(stage_acceptance) != ACCEPTANCE_SHA
            or sha(STAGE / EDITION / "master.tei.xml") != MASTER_SHA):
        raise ValueError("Torrey staged master or acceptance differs")
    validate_acceptance(stage_acceptance, root=STAGE)
    validate_state(STAGE / WORK / "state.json", root=STAGE)
    installed = install_accepted_work(ROOT, STAGE, work_id="torreys-topical-textbook")
    if (installed.get("status") != "installed-and-validated"
            or installed.get("previous_files") != staged["current_work_before"]
            or installed.get("installed_files") != staged["staged_work_after"]
            or _files(ROOT / WORK) != staged["staged_work_after"]
            or _files(STAGE / WORK) != staged["staged_work_after"]):
        raise ValueError("Torrey guarded install result/readback differs")
    journal_path = Path(installed["operation"]) / "operation.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if (journal.get("phase") != "complete"
            or journal.get("before") != staged["current_work_before"]
            or journal.get("after") != staged["staged_work_after"]):
        raise ValueError("Torrey guarded install journal differs")
    validate_acceptance(ROOT / EDITION / "acceptance.json", root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    receipt = {
        "contract": "ocd-torrey-current-canonical-install-v1",
        "status": installed["status"],
        "work_id": "torreys-topical-textbook",
        "stage_receipt_sha256": STAGE_RECEIPT_SHA,
        "rollback_proof_sha256": ROLLBACK_SHA,
        "master_sha256": MASTER_SHA,
        "acceptance_sha256": ACCEPTANCE_SHA,
        "journal_path": str(journal_path),
        "journal_sha256": sha(journal_path),
        "journal_phase": journal["phase"],
        "canonical_generation": _files(ROOT / WORK),
        "stage_unchanged": True,
        "rights_clearance": "unresolved",
        "human_verification": "not-recorded",
        "public_publication_authorized": False,
    }
    save(result_path, receipt)
    print(json.dumps({"status": receipt["status"], "journal_phase": receipt["journal_phase"], "canonical_files": len(receipt["canonical_generation"]), "result_sha256": sha(result_path)}, sort_keys=True))


if __name__ == "__main__":
    main()
