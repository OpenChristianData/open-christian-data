"""Exercise a bounded Torrey fixture rollback after the new generation goes live."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from ocd_kernel.tei.install_accepted import _files, install_accepted_work


ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/torreys-topical-textbook")
STAGE = ROOT / ".t"
FIXTURE = ROOT / ".u"
OUT = ROOT / "reports/_logs/torrey-current-reconciliation-20261002-v1/install-rollback-proof.json"
STAGE_RECEIPT = ROOT / "reports/_logs/torrey-current-reconciliation-20261002-v1/staged-acceptance.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if FIXTURE.exists():
        raise FileExistsError("Torrey rollback fixture exists; inspect instead of overwriting")
    stage_receipt = json.loads(STAGE_RECEIPT.read_text(encoding="utf-8"))
    before = _files(ROOT / WORK)
    after = _files(STAGE / WORK)
    if before != stage_receipt["current_work_before"] or after != stage_receipt["staged_work_after"]:
        raise ValueError("Torrey stage/canonical preimage drifted before rollback proof")
    FIXTURE.mkdir()
    prefix = WORK.parts
    for source in STAGE.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(STAGE)
        if relative.parts[: len(prefix)] == prefix:
            continue
        target = FIXTURE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha(source) != sha(target):
            raise ValueError(f"Torrey fixture support copy differs: {relative}")
    shutil.copytree(ROOT / WORK, FIXTURE / WORK)
    if _files(FIXTURE / WORK) != before:
        raise ValueError("Torrey fixture work preimage differs")

    def fail_at(phase: str) -> None:
        if phase == "after-new-live":
            raise RuntimeError("torrey-simulated-after-new-live")

    try:
        install_accepted_work(FIXTURE, STAGE, work_id="torreys-topical-textbook", fail_at=fail_at)
    except RuntimeError as exc:
        if str(exc) != "torrey-simulated-after-new-live":
            raise
    else:
        raise ValueError("Torrey simulated failure did not fire")
    if _files(FIXTURE / WORK) != before or _files(STAGE / WORK) != after or _files(ROOT / WORK) != before:
        raise ValueError("Torrey rollback did not restore exact generation")
    journals = list((FIXTURE / ".tmp_audit").glob("accepted-install-*/operation.json"))
    if len(journals) != 1:
        raise ValueError("Torrey rollback journal count differs")
    journal = json.loads(journals[0].read_text(encoding="utf-8"))
    if journal.get("phase") != "rolled-back" or journal.get("before") != before or journal.get("after") != after:
        raise ValueError("Torrey rollback journal differs")
    result = {
        "contract": "ocd-torrey-install-rollback-proof-v1",
        "status": "pass",
        "checkpoint": "after-new-live",
        "caught_error": "torrey-simulated-after-new-live",
        "fixture_root": str(FIXTURE),
        "journal_path": str(journals[0]),
        "journal_sha256": sha(journals[0]),
        "journal_phase": journal["phase"],
        "before": before,
        "after": after,
        "fixture_work_restored": True,
        "promoted_stage_unchanged": True,
        "canonical_work_unchanged": True,
        "canonical_install_performed": False,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": "pass", "journal_phase": journal["phase"], "journal_sha256": result["journal_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
