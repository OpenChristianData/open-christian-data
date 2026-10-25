"""Read back the already journaled Morning and Evening generation install."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ocd_kernel.lib.path_io import io_path
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document,
    verify_accepted_document,
)
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "spurgeons-morning-evening"
WORK = Path("library/works") / WORK_ID
FORM_ID = "spurgeons-morning-evening-english"
EDITION_ID = "spurgeons-morning-evening-ccel-thml-electronic"
ACQUISITION_ID = "spurgeons-morning-evening-ccel-retained-xml"
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/ccel/spurgeon/morneve.xml")
SOURCE_SHA256 = "3512797ae879d4fdbdcde90e5ebc04299e501658fd8fb6c09977c2e2648ad0a4"
MANIFEST = Path(
    "sources/devotionals/spurgeons-morning-evening/"
    "lib030.source-manifest-current-closure-20261003-v1.json"
)
MANIFEST_SHA256 = "8152bc4c8ad9d0cad8ce283477de7a503031f14564e6f584955662e84fba30bc"
PROJECTION = WORK / "integration/lib030-current-acceptance-20261003-v1/accepted-master-projection.json"
OPERATION = Path(".tmp_audit/accepted-install-18d7fa1eea734a1f")
JOURNAL_SHA256 = "a4765f9d07eda79c7cf2a91e650c6c20b5c3134eb7db7e300f4c04ce490132dd"
STAGE_RECEIPT = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "spurgeons-morneve-acceptance-stage-20261003-v4/stage-receipt.json"
)
STAGE_RECEIPT_SHA256 = "62c74b568ab704a9ec3e06cc6ecfcf5cb5c0db5ff0f7acd992c7877f2fe6c59b"


def _sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def readback() -> dict:
    root = ROOT.resolve(strict=True)
    journal_path = root / OPERATION / "operation.json"
    journal_bytes = io_path(journal_path).read_bytes()
    if hashlib.sha256(journal_bytes).hexdigest() != JOURNAL_SHA256:
        raise RuntimeError("completed operation journal differs from its observed byte pin")
    journal = json.loads(journal_bytes)
    if (journal.get("work_id") != WORK_ID or journal.get("phase") != "complete"
            or journal.get("result_status") != "installed-and-validated"
            or journal.get("target") != WORK.as_posix() or journal.get("existed") is not True):
        raise RuntimeError("operation journal is not the expected completed initial install")
    live, backup = root / WORK, root / OPERATION / "previous"
    if _files(live) != journal.get("after") or _files(backup) != journal.get("before"):
        raise RuntimeError("live generation or retained backup differs from its complete journal")

    stage_receipt_bytes = io_path(STAGE_RECEIPT).read_bytes()
    if hashlib.sha256(stage_receipt_bytes).hexdigest() != STAGE_RECEIPT_SHA256:
        raise RuntimeError("v4 stage receipt changed after installation")
    stage_receipt = json.loads(stage_receipt_bytes)
    if (stage_receipt.get("master_sha256") != journal["after"][
            (EDITION / "master.tei.xml").relative_to(WORK).as_posix()]
            or stage_receipt.get("acceptance_sha256") != journal["after"][
                (EDITION / "acceptance.json").relative_to(WORK).as_posix()]):
        raise RuntimeError("installed master/acceptance do not match the approved stage receipt")

    if _sha(root / SOURCE) != SOURCE_SHA256 or _sha(root / MANIFEST) != MANIFEST_SHA256:
        raise RuntimeError("retained source or source manifest changed")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    if manifest.sha256 != MANIFEST_SHA256 or manifest.verify() is not None:
        raise RuntimeError("installed source authority closure no longer verifies")
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    if acquisition.get("source_sha256") != SOURCE_SHA256:
        raise RuntimeError("installed acquisition no longer identifies the retained witness")

    acceptance_path = root / EDITION / "acceptance.json"
    acceptance = validate_acceptance(acceptance_path, root=root)
    state = validate_state(root / WORK / "state.json", root=root)
    if (acceptance["promotion"].get("status") != "promoted"
            or acceptance["identity"] != {
                "work_id": WORK_ID,
                "textual_form_id": FORM_ID,
                "edition_id": EDITION_ID,
                "acquisition_id": ACQUISITION_ID,
            }):
        raise RuntimeError("installed acceptance identity or promotion status differs")
    targets = [item for item in state["targets"] if item.get("target_id") == EDITION_ID]
    if len(targets) != 1 or targets[0].get("stage") != "accepted":
        raise RuntimeError("installed edition state is not accepted")

    master_path = root / EDITION / "master.tei.xml"
    p5_errors = validate_file(master_path)
    projection = project_accepted_document(root, acceptance_path=acceptance_path, category="prose")
    checker_errors = verify_accepted_document(
        root,
        acceptance_path=acceptance_path,
        rows=projection["rows"],
        receipt=projection["receipt"],
        category="prose",
    )
    persisted = json.loads(io_path(root / PROJECTION).read_bytes())
    if (p5_errors or checker_errors or len(projection["rows"]) != 1
            or persisted.get("rows") != projection["rows"]
            or persisted.get("receipt") != projection["receipt"]
            or persisted.get("independent_verifier_errors") != []):
        raise RuntimeError("installed P5/native projection or persisted projection readback differs")
    return {
        "status": "pass",
        "work_id": WORK_ID,
        "operation": OPERATION.as_posix(),
        "journal_sha256": JOURNAL_SHA256,
        "journal_phase": journal["phase"],
        "live_file_count": len(journal["after"]),
        "live_generation_matches_journal": True,
        "previous_file_count": len(journal["before"]),
        "backup_matches_journal": True,
        "acceptance_sha256": _sha(acceptance_path),
        "master_sha256": _sha(master_path),
        "state": "accepted",
        "p5_errors": p5_errors,
        "projection_rows": len(projection["rows"]),
        "independent_projection_errors": checker_errors,
        "persisted_projection_matches": True,
        "source_manifest_sha256": manifest.sha256,
        "human_acceptance": acceptance["decision"]["human_decision"]["status"],
        "agent_scope_status": acceptance["decision"]["agent_assessment"]["status"],
        "rights": stage_receipt["rights"],
        "publication": stage_receipt["publication"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(readback(), sort_keys=True))


if __name__ == "__main__":
    main()
