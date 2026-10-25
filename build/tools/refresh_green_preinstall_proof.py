"""Bind the current independent checker to the frozen Green staged output."""

import json
from pathlib import Path

from build.tools.prepare_green_current import ROOT, LOG, BASE, digest, save, json_bytes
from build.tools.stage_green_current_acceptance import WORK, EDITION, WORK_ID, SOURCE_SHA, MASTER_SHA
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.tei.acceptance import _validate_acceptance_for_work
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories.prose import verify_accepted_prose


def main():
    stage = Path("D:/Library/Open Christian Data/candidate-reviews/green-current-acceptance-20261002-v1")
    receipt_path = stage / "stage-receipt.json"
    receipt_raw = receipt_path.read_bytes()
    if digest(receipt_raw) != "6aaf79f380422653602ab351c982bce63ce1b825fb059cf537107fc1fef41db6":
        raise ValueError("Frozen Green stage receipt differs")
    receipt = json.loads(receipt_raw)
    original = _files(ROOT / WORK)
    promoted = _files(stage / WORK)
    if original != receipt["before"] or promoted != receipt["after"]:
        raise ValueError("Canonical preimage or exact staged generation differs")
    for path, expected in receipt["schema_pins"].items():
        if digest((ROOT / path).read_bytes()) != expected:
            raise ValueError("Current staged runtime prerequisite differs: " + path)
    master = stage / EDITION / "master.tei.xml"
    candidate = BASE / "candidate.tei.xml"
    if digest(master.read_bytes()) != MASTER_SHA or master.read_bytes() != candidate.read_bytes():
        raise ValueError("Exact current candidate/staged master differs")
    acceptance = stage / EDITION / "acceptance.json"
    projection_path = stage / WORK / "integration/green-accepted-v1/stage-projection.json"
    projection = json.loads(projection_path.read_bytes())
    import ocd_kernel.projection.native_content as producer
    disabled_original = producer.project_content
    def disabled(*args, **kwargs):
        raise AssertionError("Producer is disabled for current Green verification")
    producer.project_content = disabled
    try:
        with cached_edition_lookups():
            accepted = _validate_acceptance_for_work(io_path(acceptance), root=io_path(stage), work_id=WORK_ID)
            errors = verify_accepted_prose(io_path(stage), acceptance_path=io_path(acceptance), rows=projection["rows"], receipt=projection["receipt"])
    finally:
        producer.project_content = disabled_original
    if errors or len(projection["rows"]) != 13 or sum(len(row["text"]) for row in projection["rows"]) != 155586:
        raise ValueError("Current independent staged-output verification failed: " + str(errors))
    if accepted["source"]["source_sha256"] != SOURCE_SHA:
        raise ValueError("Exact staged source binding differs")
    source_path = ROOT / accepted["source"]["source_path"]
    if digest(io_path(source_path).read_bytes()) != SOURCE_SHA:
        raise ValueError("Actual retained XML differs")
    if _files(ROOT / WORK) != original or _files(stage / WORK) != promoted:
        raise ValueError("Read-only current verification changed a generation")
    for path, expected in receipt["schema_pins"].items():
        if digest((ROOT / path).read_bytes()) != expected:
            raise ValueError("Current runtime drift during verification")
    old = LOG / "current-candidate-proof-v3.json"
    inputs = [old, candidate, LOG / "install-rollback-proof.json", LOG / "repaired-handoff-proof.json", LOG / "source-relationship-review.json", LOG / "active-header-source-field-review.json", ROOT / "build/tools/install_green_current.py", Path(__file__).resolve()]
    report = {"status": "pass", "claim": "Read-only current-checker independent verification of the exact frozen staged13row projection; not a new source reconstruction/P5/replay or canonical installation", "command": "py -3 -m build.tools.refresh_green_preinstall_proof", "exit_code": 0, "producer_disabled": True, "independent_verification_errors": errors, "rows": 13, "text_characters": 155586, "candidate_sha256": MASTER_SHA, "source_sha256": SOURCE_SHA, "old_receipt_preserved": {"path": old.relative_to(ROOT).as_posix(), "sha256": digest(old.read_bytes()), "dated_checker_sha256": json.loads(old.read_bytes())["input_bindings"]["ocd_kernel/projection/native_content_check.py"]}, "current_checker_sha256": digest((ROOT / "ocd_kernel/projection/native_content_check.py").read_bytes()), "stage_root": stage.as_posix(), "stage_receipt_sha256": digest(receipt_raw), "staged_acceptance_sha256": digest(acceptance.read_bytes()), "staged_projection_path": projection_path.as_posix(), "staged_projection_sha256": digest(projection_path.read_bytes()), "canonical_before": original, "staged_after": promoted, "current_runtime_pins": receipt["schema_pins"], "canonical_changes_performed": False, "bindings": {p.relative_to(ROOT).as_posix(): digest(io_path(p).read_bytes()) for p in inputs}}
    destination = LOG / "current-checker-refresh/current-candidate-proof-v3.json"
    save(destination, json_bytes(report))
    manifest = {"status": "ready-for-coordinator-review", "stage_root": stage.as_posix(), "stage_receipt_sha256": digest(receipt_raw), "current_independent_receipt": {"path": destination.relative_to(ROOT).as_posix(), "sha256": digest(json_bytes(report))}, "canonical_before_files": len(original), "staged_after_files": len(promoted), "runtime_pins": receipt["schema_pins"], "master_sha256": MASTER_SHA, "acceptance_sha256": digest(acceptance.read_bytes()), "paired_notice_pins": receipt["paired_notices"], "metadata_difference": receipt["metadata_difference"], "source_sha256": SOURCE_SHA, "original_work_sha256": original["work.json"], "proposed_work_sha256": promoted["work.json"], "original_state_sha256": original["state.json"], "proposed_state_sha256": promoted["state.json"], "rollback_proof": {"path": (LOG / "install-rollback-proof.json").relative_to(ROOT).as_posix(), "sha256": digest((LOG / "install-rollback-proof.json").read_bytes())}, "install_helper": {"path": "build/tools/install_green_current.py", "sha256": digest((ROOT / "build/tools/install_green_current.py").read_bytes())}, "canonical_install_performed": False}
    save(LOG / "final-preinstall-manifest.json", json_bytes(manifest))
    print(json.dumps({"status": "pass", "receipt_path": destination.relative_to(ROOT).as_posix(), "receipt_sha256": digest(json_bytes(report)), "preinstall_manifest_sha256": digest(json_bytes(manifest)), "checker_sha256": report["current_checker_sha256"], "rows": 13, "characters": 155586, "before_files": len(original), "after_files": len(promoted)}))


if __name__ == "__main__":
    main()
