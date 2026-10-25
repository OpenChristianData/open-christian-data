"""Install one root-reviewed Smith stage generation with an exact clearance hash."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, install_accepted_work


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1"
WORK = Path("library/works/smiths-bible-dictionary")
EDITION = WORK / "forms/smiths-bible-dictionary-retained-electronic/editions/smiths-bible-dictionary-retained-electronic-witness"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(clearance_sha256: str) -> None:
    clearance_path = OUT / "coordinator-install-clearance.json"
    if digest(clearance_path) != clearance_sha256:
        raise ValueError("Smith coordinator install clearance differs from exact approved hash")
    clearance = json.loads(clearance_path.read_text(encoding="utf-8"))
    if clearance["status"] != "cleared-for-one-guarded-canonical-install":
        raise ValueError("Smith canonical install is not cleared")
    stage = ROOT / ".sm"
    if _files(ROOT / WORK) != clearance["canonical_work_preimage"]:
        raise ValueError("Smith canonical preimage drifted")
    if _files(stage / WORK) != clearance["staged_work_generation"]:
        raise ValueError("Smith promoted stage drifted")
    for binding in clearance["input_bindings"].values():
        path = Path(binding["path"])
        if not path.is_absolute():
            path = ROOT / path
        if digest(path) != binding["sha256"]:
            raise ValueError(f"Smith install input drifted: {path}")
    result = install_accepted_work(ROOT, stage, work_id="smiths-bible-dictionary")
    if (result["status"] != "installed-and-validated"
            or result["previous_files"] != clearance["canonical_work_preimage"]
            or result["installed_files"] != clearance["staged_work_generation"]
            or _files(ROOT / WORK) != clearance["staged_work_generation"]):
        raise ValueError("Smith guarded installer result differs")
    acceptance = ROOT / EDITION / "acceptance.json"
    master = ROOT / EDITION / "master.tei.xml"
    if digest(acceptance) != clearance["staged_acceptance_sha256"] or digest(master) != clearance["staged_master_sha256"]:
        raise ValueError("Smith installed master or acceptance differs")
    validate_acceptance(acceptance, root=ROOT)
    validate_state(ROOT / WORK / "state.json", root=ROOT)
    journal_path = Path(result["operation"]) / "operation.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if (journal["phase"] != "complete" or journal["before"] != clearance["canonical_work_preimage"]
            or journal["after"] != clearance["staged_work_generation"]):
        raise ValueError("Smith guarded install journal differs")
    receipt = {"contract": "ocd-smith-current-canonical-install-v1", "status": "installed-and-validated", "checked_at": datetime.now(timezone.utc).isoformat(), "work_id": "smiths-bible-dictionary", "clearance_sha256": clearance_sha256, "master_sha256": digest(master), "acceptance_sha256": digest(acceptance), "operation_path": str(journal_path), "operation_sha256": digest(journal_path), "operation_phase": "complete", "canonical_generation": result["installed_files"], "source_reacquired": False, "rights_clearance": "unresolved", "publication_authorized": False}
    output = OUT / "canonical-install-result.json"
    with output.open("xb") as stream:
        stream.write((json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    print(json.dumps({"status": receipt["status"], "master_sha256": receipt["master_sha256"], "acceptance_sha256": receipt["acceptance_sha256"], "operation_phase": receipt["operation_phase"], "receipt_sha256": digest(output)}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clearance-sha256", required=True)
    arguments = parser.parse_args()
    main(arguments.clearance_sha256)
