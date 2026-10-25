"""Apply only ROOT-cleared Nave category bytes and retain a stage successor."""

import json
from pathlib import Path

from build.tools.prepare_nave_current import ROOT, LOG, WORK, digest, save, json_bytes
from ocd_kernel.library._common import io_path
from ocd_kernel.tei.install_accepted import _files


def main():
    proposal = LOG / "authority-proposal"
    clearance = LOG / "coordinator-authority-clearance.json"
    if digest(clearance.read_bytes()) != "bc87789e4549de6615ef8535730125aa9f31ed865806f583358f426b18393aad":
        raise ValueError("Exact ROOT authority clearance differs")
    before = (proposal / "work.before.json").read_bytes()
    after = (proposal / "work.after.json").read_bytes()
    target = io_path(WORK / "work.json")
    state_before = (proposal / "state.before.json").read_bytes()
    if target.read_bytes() != before or io_path(WORK / "state.json").read_bytes() != state_before:
        raise ValueError("Immediate original Nave work/state differs")
    stage = Path("D:/Library/Open Christian Data/candidate-reviews/nave-current-20261002-v3")
    receipt_raw = (stage / "stage-receipt.json").read_bytes()
    receipt = json.loads(receipt_raw)
    if receipt["before"] != _files(WORK) or receipt["after"] != _files(stage / WORK.relative_to(ROOT)):
        raise ValueError("Original frozen stage generation differs")
    save(LOG / "stage-receipt-pre-category.json", receipt_raw)
    save(stage / "stage-receipt-pre-category.json", receipt_raw)
    temporary = io_path(WORK / ".nave-category.tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    temporary.write_bytes(after)
    temporary.replace(target)
    current = _files(WORK)
    wanted = dict(receipt["before"])
    wanted["work.json"] = digest(after)
    if current != wanted or io_path(WORK / "state.json").read_bytes() != state_before:
        raise ValueError("Category-only readback differs")
    receipt["before"] = current
    receipt["category_prerequisite_already_applied"] = True
    receipt["original_stage_receipt_sha256"] = digest(receipt_raw)
    (stage / "stage-receipt.json").write_bytes(json_bytes(receipt))
    save(LOG / "staged-acceptance-post-category.json", json_bytes(receipt))
    result = {"status": "pass", "sole_change": "edition.category", "state_unchanged": True,
              "original_work_sha256": digest(before), "current_work_sha256": digest(after),
              "original_stage_receipt_sha256": digest(receipt_raw), "successor_stage_receipt_sha256": digest(json_bytes(receipt)),
              "same_staged_after_generation": receipt["after"], "canonical_current_before": current,
              "precategory_isolated_rollback": {"path": (LOG / "install-rollback-proof.json").relative_to(ROOT).as_posix(), "sha256": digest((LOG / "install-rollback-proof.json").read_bytes()), "qualification": "Exact pre-category original generation restored including metadata prerequisite; current stage after generation unchanged. Canonical accepted state/master not installed by this prerequisite."}}
    save(LOG / "category-prerequisite-result.json", json_bytes(result))
    print(json.dumps({"status": "pass", "stage_receipt_sha256": result["successor_stage_receipt_sha256"], "before_files": len(current), "after_files": len(receipt["after"])}))


if __name__ == "__main__":
    main()
