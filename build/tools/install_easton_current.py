"""Install exactly the reviewed Easton electronic witness generation once."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, install_accepted_work


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/_logs/eastons-bible-dictionary-current-reconciliation-20261002-v1"
WORK = Path("library/works/eastons-bible-dictionary")
EDITION = WORK / "forms/eastons-bible-dictionary-retained-electronic/editions/eastons-bible-dictionary-retained-electronic-witness"
CLEARANCE_SHA = "4f8eeb2b3746eac8794f330b4170d45274d5c75a3d3b79072728f26790c15a57"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    clearance_path = OUT / "coordinator-install-clearance.json"
    if digest(clearance_path) != CLEARANCE_SHA:
        raise ValueError("Easton coordinator install clearance drifted")
    clearance = json.loads(clearance_path.read_text(encoding="utf-8"))
    if clearance["status"] != "cleared-for-one-guarded-canonical-install":
        raise ValueError("Easton canonical install is not cleared")
    stage = ROOT / ".h"
    if _files(ROOT / WORK) != clearance["canonical_work_preimage"]:
        raise ValueError("Easton canonical preimage drifted")
    if _files(stage / WORK) != clearance["staged_work_generation"]:
        raise ValueError("Easton promoted stage drifted")
    for binding in clearance["input_bindings"].values():
        path = Path(binding["path"])
        path = path if path.is_absolute() else ROOT / path
        if digest(path) != binding["sha256"]:
            raise ValueError(f"Easton install input drifted: {path}")
    result = install_accepted_work(ROOT, stage, work_id="eastons-bible-dictionary")
    if result["status"] != "installed-and-validated" or result["previous_files"] != clearance["canonical_work_preimage"] or result["installed_files"] != clearance["staged_work_generation"]:
        raise ValueError("Easton guarded installer result differs")
    if _files(ROOT / WORK) != clearance["staged_work_generation"]:
        raise ValueError("Easton canonical installed generation differs")
    acceptance = ROOT / EDITION / "acceptance.json"
    master = ROOT / EDITION / "master.tei.xml"
    if digest(acceptance) != clearance["staged_acceptance_sha256"] or digest(master) != clearance["staged_master_sha256"]:
        raise ValueError("Easton installed master or acceptance differs")
    validate_acceptance(acceptance, root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    journal = Path(result["operation"]) / "operation.json"
    operation = json.loads(journal.read_text(encoding="utf-8"))
    if operation["phase"] != "complete" or operation["before"] != clearance["canonical_work_preimage"] or operation["after"] != clearance["staged_work_generation"]:
        raise ValueError("Easton guarded install journal differs")
    receipt = {"contract": "ocd-easton-current-canonical-install-v1", "status": "installed-and-validated", "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": "eastons-bible-dictionary", "clearance_sha256": CLEARANCE_SHA, "master_sha256": digest(master), "acceptance_sha256": digest(acceptance), "operation_path": str(journal), "operation_sha256": digest(journal), "operation_phase": "complete", "canonical_generation": result["installed_files"], "source_reacquired": False, "rights_clearance": "unresolved", "publication_authorized": False}
    output = OUT / "canonical-install-result.json"
    with output.open("xb") as stream:
        stream.write((json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    print(json.dumps({"status": receipt["status"], "master_sha256": receipt["master_sha256"], "acceptance_sha256": receipt["acceptance_sha256"], "operation_phase": receipt["operation_phase"], "receipt_sha256": digest(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
