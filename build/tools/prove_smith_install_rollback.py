"""Prove exact Smith initial-install rollback in an isolated local root."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from ocd_kernel.tei.install_accepted import _files, install_accepted_work


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/smiths-bible-dictionary")
PROMOTED = ROOT / ".sm"
FIXTURE = ROOT / ".sr"
OUT = ROOT / "reports/_logs/smiths-bible-dictionary-current-reconciliation-20261002-v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if FIXTURE.exists():
        raise FileExistsError("Smith rollback root exists; preserve prior proof")
    stage_report = json.loads((OUT / "staged-acceptance.json").read_text(encoding="utf-8"))
    if stage_report["status"] != "staged-only" or stage_report["stage_root"] != str(PROMOTED):
        raise ValueError("Smith promoted stage report differs")
    before = _files(ROOT / WORK)
    after = _files(PROMOTED / WORK)
    if before != stage_report["current_work_before"] or after != stage_report["staged_work_after"]:
        raise ValueError("Smith canonical preimage or staged generation drifted")
    FIXTURE.mkdir()
    for child in PROMOTED.iterdir():
        if child.name == "library":
            continue
        if child.is_dir():
            shutil.copytree(child, FIXTURE / child.name)
        else:
            shutil.copy2(child, FIXTURE / child.name)
    (FIXTURE / WORK).parent.mkdir(parents=True)
    shutil.copytree(ROOT / WORK, FIXTURE / WORK)
    if _files(FIXTURE / WORK) != before:
        raise ValueError("Smith rollback fixture preimage differs")
    marker = "smith-simulated-after-new-live"

    def fail_at(checkpoint: str) -> None:
        if checkpoint == "after-new-live":
            raise RuntimeError(marker)

    try:
        install_accepted_work(FIXTURE, PROMOTED, work_id="smiths-bible-dictionary", fail_at=fail_at)
    except RuntimeError as exc:
        if str(exc) != marker:
            raise
    else:
        raise ValueError("Smith rollback fault did not fire")
    if _files(FIXTURE / WORK) != before or _files(PROMOTED / WORK) != after:
        raise ValueError("Smith rollback did not restore exact preimage")
    journals = list((FIXTURE / ".tmp_audit").glob("accepted-install-*/operation.json"))
    if len(journals) != 1:
        raise ValueError("Smith rollback has no unique journal")
    journal = json.loads(journals[0].read_text(encoding="utf-8"))
    if journal.get("phase") not in {"rolled-back", "rollback-complete"} or journal.get("before") != before or journal.get("after") != after:
        raise ValueError("Smith rollback journal differs")
    result = {"contract": "ocd-smith-install-rollback-proof-v1", "status": "pass", "fixture_root": str(FIXTURE), "promoted_root": str(PROMOTED), "checkpoint": "after-new-live", "caught_error": marker, "journal_path": str(journals[0]), "journal_sha256": digest(journals[0]), "journal_phase": journal["phase"], "canonical_work_unchanged": _files(ROOT / WORK) == before, "fixture_work_restored": True, "promoted_stage_unchanged": True, "before": before, "after": after, "canonical_install_performed": False}
    target = OUT / "install-rollback-proof.json"
    with target.open("xb") as stream:
        stream.write((json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    print(json.dumps({"status": "pass", "journal_phase": journal["phase"], "proof_sha256": digest(target)}, sort_keys=True))


if __name__ == "__main__":
    main()
