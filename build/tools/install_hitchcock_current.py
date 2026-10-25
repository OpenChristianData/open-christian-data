"""Apply exactly one pinned category prerequisite and guarded Hitchcock generation."""

import argparse
import json
from pathlib import Path

from build.tools.prepare_hitchcock_current import ROOT, LOG, WORK_ID, FORM_ID, EDITION_ID, SOURCE_SHA, digest, json_bytes, save
from build.tools.stage_hitchcock_current_acceptance import WORK, EDITION, TITLE
from ocd_kernel.library._common import io_path, PipelineError
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.tei.acceptance import _validate_acceptance_for_work
from ocd_kernel.tei.install_accepted import _files, install_accepted_work


def metadata_change(original, revised):
    expected = json.loads(json_bytes(original))
    if (original["work_id"] != WORK_ID or original["title"] != TITLE
            or len(original["textual_forms"]) != 1
            or original["textual_forms"][0]["textual_form_id"] != FORM_ID
            or original["textual_forms"][0]["language"] != "en"
            or len(original["textual_forms"][0]["editions"]) != 1
            or original["textual_forms"][0]["editions"][0]["edition_id"] != EDITION_ID
            or original["textual_forms"][0]["editions"][0]["language"] != "en"
            or "category" in original["textual_forms"][0]["editions"][0]):
        raise PipelineError("Exact Hitchcock metadata preimage differs")
    expected["textual_forms"][0]["editions"][0]["category"] = "reference-entries"
    if expected != revised:
        raise PipelineError("Metadata exceeds exact one-field reference category prerequisite")
    validate_identity_update(original, revised)


def install(root, promoted, receipt_sha, evidence, *, fail_at=None):
    root, promoted = root.resolve(strict=True), promoted.resolve(strict=True)
    stage_bytes = (promoted / "stage-receipt.json").read_bytes()
    if digest(stage_bytes) != receipt_sha:
        raise PipelineError("Frozen Hitchcock stage receipt differs")
    receipt = json.loads(stage_bytes)
    if (receipt["status"] != "pass" or receipt["work_id"] != WORK_ID
            or receipt["source_sha256"] != SOURCE_SHA or receipt["category"] != "reference-entries"
            or receipt["language"] != "en" or receipt["rows"] != 2622
            or _files(root / WORK) != receipt["before"] or _files(promoted / WORK) != receipt["after"]):
        raise PipelineError("Frozen work/source/stage generation differs")
    for path, expected in receipt["schema_pins"].items():
        if digest((ROOT / path).read_bytes()) != expected:
            raise PipelineError("Frozen runtime/schema differs: " + path)
    original_bytes = io_path(root / WORK / "work.json").read_bytes()
    revised_bytes = io_path(promoted / WORK / "work.json").read_bytes()
    metadata_change(json.loads(original_bytes), json.loads(revised_bytes))
    for path, expected in receipt["before"].items():
        if path not in {"work.json", "state.json"} and receipt["after"].get(path) != expected:
            raise PipelineError("Existing authority exceeds guarded changes: " + path)
    acceptance = _validate_acceptance_for_work(promoted / EDITION / "acceptance.json", root=promoted, work_id=WORK_ID)
    if acceptance["source"]["source_sha256"] != SOURCE_SHA:
        raise PipelineError("Staged accepted source differs")
    candidate = promoted / acceptance["technical"]["candidate"]["path"]
    if io_path(candidate).read_bytes() != io_path(promoted / EDITION / "master.tei.xml").read_bytes():
        raise PipelineError("Staged master differs from exact reviewed candidate")
    evidence.mkdir(parents=True, exist_ok=False)
    save(evidence / "original-work.json", original_bytes)
    save(evidence / "stage-receipt.json", stage_bytes)
    save(evidence / "metadata-prerequisite.json", json_bytes({"changed_fields": ["textual_forms[0].editions[0].category"], "before_sha256": digest(original_bytes), "after_sha256": digest(revised_bytes), "identity_language_title_acquisition_preserved": True}))
    temporary = root / WORK / ".hitchcock-metadata.tmp"
    if temporary.exists() or _files(root / WORK) != receipt["before"]:
        raise PipelineError("Immediate original generation differs")
    temporary.write_bytes(revised_bytes)
    temporary.replace(root / WORK / "work.json")
    try:
        result = install_accepted_work(root, promoted, work_id=WORK_ID, fail_at=fail_at)
    except Exception:
        if not io_path(root / EDITION / "master.tei.xml").exists() and io_path(root / WORK / "work.json").read_bytes() == revised_bytes:
            temporary.write_bytes(original_bytes)
            temporary.replace(root / WORK / "work.json")
            if _files(root / WORK) != receipt["before"]:
                raise PipelineError("Failed install did not restore exact original generation")
            save(evidence / "metadata-rollback.json", json_bytes({"status": "rolled-back", "exact_original_generation": True}))
        raise
    if _files(root / WORK) != receipt["after"]:
        raise PipelineError("Installed generation differs")
    operation_path = Path(result["operation"]) / "operation.json"
    operation = json.loads(operation_path.read_bytes())
    if operation["phase"] != "complete" or operation["after"] != receipt["after"]:
        raise PipelineError("Installed journal incomplete or differs")
    save(evidence / "installation.json", json_bytes(result))
    audit = {"status": "pass", "work_id": WORK_ID, "operation": operation_path.as_posix(), "operation_sha256": digest(operation_path.read_bytes()), "operation_phase": "complete", "installed_files": receipt["after"], "master_sha256": receipt["master_sha256"], "stage_receipt_sha256": receipt_sha, "sole_metadata_change": "edition category", "rights_clearance": "unresolved", "human_decision": "not-recorded", "publication_authorized": False}
    save(evidence / "installed-generation.json", json_bytes(audit))
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--clearance-sha256", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    clearance = LOG / "coordinator-install-clearance.json"
    if digest(clearance.read_bytes()) != args.clearance_sha256:
        raise PipelineError("Coordinator clearance differs")
    if json.loads(clearance.read_bytes())["status"] != "cleared-for-one-guarded-canonical-install":
        raise PipelineError("Canonical installation is not cleared")
    print(json.dumps(install(ROOT, args.stage, args.receipt_sha256, args.evidence)))


if __name__ == "__main__":
    main()
