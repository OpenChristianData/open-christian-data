"""Read-only preflight by default for the pinned NPNF204 work-local stages.

An explicit single-work apply uses the shared journaled work-generation swap.
This module is not invoked with --apply by the staging workflow.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
from collections.abc import Callable

from build.tei.athanasius_table_reconstruction import ASSIGNED, SOURCE_SHA256
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path, _resolve_work_paths, _validate_state_transition


ROOT = Path(__file__).resolve().parents[2]
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/athanasius-npnf204-acceptance-stage-20260926-v1")
RECEIPT_SHA256 = "00c7aa4adfcc7a31e9a4e8e739d32e138781f5b6697424595e266eea895e6eed"
CHILD_RECEIPT_SHA256 = "8d072d4e497e07a2388956b8dbe73857372960e74d4b7b444b06936fb5260242"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"Athanasius JSON object required: {path}")
    return value


def preflight(work_id: str | None = None) -> dict[str, object]:
    """Recheck stage, exact canonical preimages, and public postconditions."""
    if _sha(STAGE / "stage-receipt.json") != RECEIPT_SHA256:
        raise PipelineError("Athanasius acceptance receipt differs from exact pin")
    receipt = _read_json(STAGE / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-athanasius-npnf204-acceptance-stage-v1"
            or receipt.get("status") != "staged-only" or receipt.get("canonical_install") is not False
            or receipt.get("work_count") != 20 or receipt.get("source_sha256") != SOURCE_SHA256
            or receipt.get("child_stage_receipt_sha256") != CHILD_RECEIPT_SHA256
            or len(receipt.get("works", [])) != 20
            or [(row["source_root_id"], row["work_id"]) for row in receipt["works"]] != list(ASSIGNED)):
        raise PipelineError("Athanasius staged cohort or source binding differs")
    if _sha(STAGE / "raw/ccel/npnf2/npnf204.xml") != SOURCE_SHA256 or _sha(ROOT / "raw/ccel/npnf2/npnf204.xml") != SOURCE_SHA256:
        raise PipelineError("Athanasius retained source differs")
    selected = receipt["works"] if work_id is None else [row for row in receipt["works"] if row["work_id"] == work_id]
    if not selected:
        raise PipelineError(f"work is outside pinned Athanasius cohort: {work_id}")
    results = []
    for row in selected:
        current = row["work_id"]
        work = Path("library/works") / current
        before, after = _files(ROOT / work), _files(STAGE / work)
        if before != row["before"] or after != row["after"]:
            raise PipelineError(f"Athanasius preimage or staged generation differs: {current}")
        if any(name not in after for name in before):
            raise PipelineError(f"Athanasius staged generation removes acquired work authority: {current}")
        old = _read_json(ROOT / work / "work.json")
        new = _read_json(STAGE / work / "work.json")
        expected = json.loads(json.dumps(old))
        expected["creators"] = [{"name": "Eusebius of Caesarea" if row["source_root_id"] == "ix" else "Athanasius of Alexandria", "role": "author", "evidence": [f"raw/ccel/npnf2/npnf204.xml#{row['source_root_id']}"]}]
        expected["textual_forms"][0]["editions"][0]["category"] = "prose"
        if new != expected:
            raise PipelineError(f"Athanasius proposed creator/category delta differs: {current}")
        original_state = _read_json(ROOT / work / "state.json")
        proposed_state = _read_json(STAGE / work / "state.json")
        expected_state = json.loads(json.dumps(original_state))
        old_target = next(item for item in original_state["targets"] if item["target_id"] == row["identity"]["edition_id"])
        target = next(item for item in proposed_state["targets"] if item["target_id"] == row["identity"]["edition_id"])
        expected_target = next(item for item in expected_state["targets"] if item["target_id"] == row["identity"]["edition_id"])
        if old_target["stage"] != "acquired" or target["stage"] != "accepted" or target["reason"] != PROMOTED_MASTER_REASON:
            raise PipelineError(f"Athanasius edition state transition differs: {current}")
        for key in ("stage", "reason", "updated_at", "evidence"):
            expected_target[key] = target[key]
        if proposed_state != expected_state:
            raise PipelineError(f"Athanasius stage changed another state target: {current}")
        edition = work / "forms" / row["identity"]["textual_form_id"] / "editions" / row["identity"]["edition_id"]
        acceptance = STAGE / edition / "acceptance.json"
        record = validate_acceptance(_io_path(acceptance), root=_io_path(STAGE))
        validate_state(_io_path(STAGE / work / "state.json"), root=_io_path(STAGE))
        if record["identity"] != row["identity"] or record["promotion"]["status"] != "promoted":
            raise PipelineError(f"Athanasius accepted identity or promotion differs: {current}")
        projection = project_accepted_prose(STAGE, acceptance_path=acceptance)
        errors = verify_accepted_prose(STAGE, acceptance_path=acceptance, rows=projection["rows"], receipt=projection["receipt"])
        if len(projection["rows"]) != 1 or projection["receipt"].get("unsupported") or errors:
            raise PipelineError(f"Athanasius accepted prose row check failed: {current}: {errors[:2]}")
        results.append({"work_id": current, "before_count": len(before), "after_count": len(after), "projection_rows": 1})
    return {"status": "pass-read-only", "canonical_action": "none", "receipt_sha256": RECEIPT_SHA256, "works": results}


def install_one(work_id: str, *, fail_at: Callable[[str], None] | None = None) -> dict[str, object]:
    """Install one pinned generation under shared locks and a rollback journal."""
    preflight(work_id)
    root, stage, target, source = _resolve_work_paths(ROOT, STAGE, work_id)
    with ExitStack() as locks:
        for lock_target in sorted({target, source}, key=lambda path: path.as_posix()):
            locks.enter_context(acquire_jsonl_lock(lock_target, acquire_timeout=30.0))
        preflight(work_id)
        before, after = _files(target), _files(source)
        identity = next(row["identity"] for row in _read_json(stage / "stage-receipt.json")["works"] if row["work_id"] == work_id)
        edition = Path("library/works") / work_id / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
        _validate_state_transition(target, source, existed=True, replacement=False, accepted_evidence_by_edition={identity["edition_id"]: ((edition / "master.tei.xml").as_posix(), (edition / "acceptance.json").as_posix())})
        result = _commit_generation(root, target, source, work_id=work_id, before=before, after=after, existed=True, replacement=False, operation_kind="athanasius-npnf204-initial-install", result_status="installed-and-validated", accepted_editions=1, fail_at=fail_at)
        if _files(target) != after:
            raise PipelineError(f"Athanasius live work differs from pinned stage after install: {work_id}")
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", choices=[work for _, work in ASSIGNED])
    parser.add_argument("--apply", action="store_true", help="install one pinned work; omitted by default")
    parser.add_argument("--ack-receipt", help="exact acceptance-stage receipt SHA-256 required with --apply")
    args = parser.parse_args()
    if args.apply:
        if not args.work_id or args.ack_receipt != RECEIPT_SHA256:
            parser.error("--apply requires --work-id and exact --ack-receipt")
        result = install_one(args.work_id)
    else:
        result = preflight(args.work_id)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
