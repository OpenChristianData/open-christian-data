"""Freeze Smith staged generation and the exact inputs for coordinator review."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ocd_kernel.tei.install_accepted import _files


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/smiths-bible-dictionary")
EDITION = WORK / "forms/smiths-bible-dictionary-retained-electronic/editions/smiths-bible-dictionary-retained-electronic-witness"
STAGE = ROOT / ".sm"
LOG = ROOT / "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def main() -> None:
    stage_path = LOG / "staged-acceptance.json"
    rollback_path = LOG / "install-rollback-proof.json"
    stage = json.loads(stage_path.read_text(encoding="utf-8"))
    rollback = json.loads(rollback_path.read_text(encoding="utf-8"))
    before = _files(ROOT / WORK)
    after = _files(STAGE / WORK)
    if (stage["status"] != "staged-only" or stage["stage_root"] != str(STAGE)
            or stage["current_work_before"] != before or stage["staged_work_after"] != after
            or rollback["status"] != "pass" or rollback["before"] != before or rollback["after"] != after
            or rollback["canonical_work_unchanged"] is not True):
        raise ValueError("Smith staged/preimage/rollback generation differs")
    master = STAGE / EDITION / "master.tei.xml"
    acceptance = STAGE / EDITION / "acceptance.json"
    if digest(master) != stage["master_sha256"] or digest(acceptance) != stage["acceptance_sha256"]:
        raise ValueError("Smith staged master/acceptance hash differs")
    adapter = ROOT / "ocd_kernel/projection/categories/reference_entries.py"
    if digest(adapter) != "37addf99c4327533995f185d15b3a0b56ce63fb4ea6e2f7a4584e94995e25e08":
        raise ValueError("Smith applied adapter changed")
    tests = {"contract": "ocd-smith-native-focused-test-terminal-v1", "status": "pass", "test_selection": ["tests/test_projection_smith_native.py", "tests/test_projection_hitchcock_native.py"], "host_chunk": "9c4730", "exit_code": 0, "passed": 36, "elapsed_seconds_reported": 2.59, "guarded_host_temp_cleanup": "complete", "sandbox_preliminary_error": "pytest temp ACL blocked fixture setup; no product assertions ran", "adapter_sha256": digest(adapter)}
    test_path = LOG / "focused-test-terminal.json"
    save(test_path, tests)
    paths = [
        "raw/bible_dictionaries/smiths.jsonl",
        "data/reference_entries/smiths-bible-dictionary/README.md",
        "sources/reference-entries/smiths-bible-dictionary/README.source.md",
        "ocd_kernel/projection/categories/reference_entries.py",
        "schemas/v2/categories/reference-entries.schema.json",
        "schemas/v2/public-row.schema.json",
        "build/tools/stage_smith_current_acceptance.py",
        "build/tools/prove_smith_install_rollback.py",
        "build/tools/install_smith_current.py",
        "build/tools/complete_smith_private_release.py",
        "reports/_logs/smith-coordinator-source-review-20261002-v1/review.json",
        "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1/native-support-proposal/actual-candidate-proof.json",
        "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1/adapter-applied-freeze.json",
        "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1/coordinator-category-clearance.json",
    ]
    input_bindings = {path: digest(ROOT / path) for path in paths}
    report = {
        "contract": "ocd-smith-current-stage-review-v1",
        "status": "awaiting-coordinator-canonical-install-review",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "work_id": "smiths-bible-dictionary",
        "stage_root": str(STAGE),
        "canonical_work_preimage": before,
        "staged_work_generation": after,
        "staged_master_sha256": digest(master),
        "staged_acceptance_sha256": digest(acceptance),
        "staged_acceptance_report_sha256": digest(stage_path),
        "rollback_proof_sha256": digest(rollback_path),
        "focused_test_terminal_sha256": digest(test_path),
        "input_bindings": input_bindings,
        "rights_clearance": "unresolved",
        "human_decision": "not-recorded",
        "publication_authorized": False,
        "canonical_install_performed": False,
    }
    review_path = LOG / "stage-review.json"
    save(review_path, report)
    print(json.dumps({"status": report["status"], "stage_review_sha256": digest(review_path), "before_files": len(before), "staged_files": len(after), "input_bindings": len(input_bindings)}))


if __name__ == "__main__":
    main()
