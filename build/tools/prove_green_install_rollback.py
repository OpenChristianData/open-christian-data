"""Exercise Green metadata/receipt guards and exact isolated rollback."""

import argparse
import copy
import json
from pathlib import Path
import shutil

from build.tools.prepare_green_current import ROOT, LOG, WORK_ID, digest, save, json_bytes
from build.tools.install_green_current import WORK, install, metadata_change
from ocd_kernel.library._common import io_path, PipelineError
from ocd_kernel.tei.install_accepted import _files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    stage, fixture = args.stage.absolute(), args.fixture.absolute()
    if fixture.exists() or fixture.parent.resolve(strict=True) != Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True) or not fixture.name.startswith("green-rollback-"):
        raise ValueError("Fresh bounded isolated fixture required")
    receipt_raw = (stage / "stage-receipt.json").read_bytes()
    receipt = json.loads(receipt_raw)
    before, after = _files(ROOT / WORK), _files(stage / WORK)
    if before != receipt["before"] or after != receipt["after"]:
        raise ValueError("Frozen stage/canonical preimage changed")
    fixture.mkdir()
    for child in stage.iterdir():
        if child.name == "library":
            continue
        if child.is_dir(): shutil.copytree(io_path(child), io_path(fixture / child.name))
        else: shutil.copy2(child, fixture / child.name)
    io_path(fixture / WORK).parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(io_path(ROOT / WORK), io_path(fixture / WORK))
    guards = []
    try:
        install(fixture, stage, "0" * 64, fixture / "bad-receipt")
    except PipelineError as exc:
        if "stage receipt differs" not in str(exc): raise
        guards.append({"case": "altered-receipt-binding", "status": "rejected", "reason": str(exc)})
    else: raise ValueError("Invalid receipt accepted")
    original = json.loads(io_path(ROOT / WORK / "work.json").read_bytes())
    revised = json.loads(io_path(stage / WORK / "work.json").read_bytes())
    metadata_change(original, revised)
    for label, key, value in (("title-mutation", "title", "invented title"), ("additional-field", "invented_field", "extra")):
        changed = copy.deepcopy(revised)
        changed[key] = value
        try: metadata_change(original, changed)
        except PipelineError as exc:
            if "exact three-field" not in str(exc): raise
            guards.append({"case": label, "status": "rejected", "reason": str(exc)})
        else: raise ValueError("Additional metadata accepted")
    marker = "green-isolated-after-new-live"
    def fail_at(checkpoint):
        if checkpoint == "after-new-live": raise RuntimeError(marker)
    try:
        install(fixture, stage, digest(receipt_raw), fixture / "rollback-evidence", fail_at=fail_at)
    except RuntimeError as exc:
        if str(exc) != marker: raise
    else: raise ValueError("Fault was not exercised")
    if _files(fixture / WORK) != before or _files(ROOT / WORK) != before or _files(stage / WORK) != after:
        raise ValueError("Fault failed exact old-generation restoration")
    journals = list((fixture / ".tmp_audit").glob("accepted-install-*/operation.json"))
    if len(journals) != 1: raise ValueError("No unique rollback journal")
    journal = json.loads(journals[0].read_bytes())
    if journal["phase"] != "rolled-back" or journal["after"] != after:
        raise ValueError("Rollback journal mismatch")
    result = {"status": "pass", "stage_root": stage.as_posix(), "fixture_root": fixture.as_posix(), "stage_receipt_sha256": digest(receipt_raw), "fault": "after-new-live", "journal_path": journals[0].as_posix(), "journal_sha256": digest(journals[0].read_bytes()), "journal_phase": journal["phase"], "guards": guards, "canonical_original_generation_unchanged": True, "metadata_prerequisite_restored": True, "fixture_generation_restored": before, "staged_generation_unchanged": after, "canonical_install_performed": False}
    save(LOG / "install-rollback-proof.json", json_bytes(result))
    print(json.dumps({"status": "pass", "guards": len(guards), "journal_phase": journal["phase"], "proof_sha256": digest(json_bytes(result))}))


if __name__ == "__main__":
    main()
