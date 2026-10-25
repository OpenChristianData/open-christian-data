"""Guarded complete-generation install for two accepted Creeds.json rebinds.

The default command is a read-only preflight. ``--apply`` performs one work
transaction using the shared durable journal and rollback machinery. A live
doctrinal projection and its independent checker run before journal completion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Callable

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.doctrinal_documents import (
    project_accepted_doctrinal_documents,
    verify_accepted_doctrinal_documents,
)
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path

from build.tools.stage_creeds_json_metadata_rebind import CONTRACT, PROJECTION_PROFILE, ROOT


STAGE_PARENT = Path("D:/Library/Open Christian Data/reports/runs/creeds-json-metadata-rebind-stage-20260926-v2")
STAGE_RECEIPTS = {
    "belgic-confession-of-faith": "66e4cc35d197c1a1afe15a358f5e6caeda82bfe81ff0d436f71ea7ff3c2c029f",
    "chalcedonian-definition": "10d10018e17204196befbecb06527aacba7eea899a076fd68be54d6c2dcc0df0",
}
REHEARSAL_MARKER = ".ocd-creeds-metadata-rebind-rehearsal"
REHEARSAL_CONTENT = "ocd-creeds-metadata-rebind-rehearsal-v1\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _paths(root: Path, work_id: str) -> tuple[Path, Path, Path]:
    work = root / "library/works" / work_id
    acceptance = work / "forms" / f"{work_id}-retained-electronic" / "editions" / f"{work_id}-creeds-json" / "acceptance.json"
    accounting = work / "integration/creeds-json-electronic-v1/source-accounting.json"
    return work, acceptance, accounting


def _project_check(root: Path, acceptance: Path) -> int:
    output = project_accepted_doctrinal_documents(_io_path(root), acceptance_path=_io_path(acceptance))
    rows, receipt = output["rows"], output["receipt"]
    errors = verify_accepted_doctrinal_documents(
        _io_path(root), acceptance_path=_io_path(acceptance), rows=rows, receipt=receipt,
    )
    if errors:
        raise PipelineError(f"Creeds.json independent doctrinal checker rejected rows: {errors[:3]}")
    if receipt.get("profile") != PROJECTION_PROFILE or not rows:
        raise PipelineError("Creeds.json live projection profile or rows differ")
    return len(rows)


def preflight(work_id: str, *, root: Path = ROOT) -> tuple[Path, Path, dict[str, object]]:
    if work_id not in STAGE_RECEIPTS:
        raise PipelineError("metadata rebind installer is limited to two exact works")
    root = root.resolve(strict=True)
    canonical = ROOT.resolve(strict=True)
    if root != canonical and _io_path(root / REHEARSAL_MARKER).read_text(encoding="utf-8") != REHEARSAL_CONTENT:
        raise PipelineError("noncanonical install root requires the exact rehearsal marker")
    stage = (STAGE_PARENT / work_id).resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("stage and install root overlap")
    receipt_path = stage / "stage-receipt.json"
    if _sha(receipt_path) != STAGE_RECEIPTS[work_id]:
        raise PipelineError("pinned metadata rebind stage receipt differs")
    record = json.loads(_io_path(receipt_path).read_text(encoding="utf-8"))
    if (record.get("contract") != CONTRACT or record.get("status") != "staged-only"
            or record.get("work_id") != work_id or record.get("canonical_root") != canonical.as_posix()
            or record.get("stage_root") != stage.as_posix()):
        raise PipelineError("metadata rebind stage contract, root, or identity differs")
    work, acceptance, accounting = _paths(root, work_id)
    staged_work, staged_acceptance, staged_accounting = _paths(stage, work_id)
    before, after = record["before"], record["after"]
    if _files(work) != before or _files(staged_work) != after:
        raise PipelineError("canonical before or staged after complete generation differs")
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    if changed != set(record["changed_paths"]) or len(changed) != 4:
        raise PipelineError("metadata rebind changed path set differs")
    old = validate_acceptance(_io_path(acceptance), root=_io_path(root))
    new = validate_acceptance(_io_path(staged_acceptance), root=_io_path(stage))
    validate_state(_io_path(root / "library/works" / work_id / "state.json"), root=_io_path(root))
    validate_state(_io_path(stage / "library/works" / work_id / "state.json"), root=_io_path(stage))
    if (old["identity"] != new["identity"] or old["decision"] != new["decision"]
            or old["promotion"] != new["promotion"]):
        raise PipelineError("accepted identity, decision, or promotion changed")
    master_rel = staged_acceptance.parent.relative_to(staged_work) / "master.tei.xml"
    if before.get(master_rel.as_posix()) != after.get(master_rel.as_posix()) or _sha(staged_acceptance.parent / "master.tei.xml") != record["master_sha256"]:
        raise PipelineError("accepted master changed")
    source_accounting = json.loads(_io_path(staged_accounting).read_text(encoding="utf-8"))
    if source_accounting.get("projection_profile") != PROJECTION_PROFILE:
        raise PipelineError("staged source accounting lacks the exact projection profile")
    _project_check(stage, staged_acceptance)
    return root, stage, record


def install(
    work_id: str, *, root: Path = ROOT, after_live_check: Callable[[], None] | None = None,
) -> dict[str, object]:
    root, stage, record = preflight(work_id, root=root)
    target, acceptance, _ = _paths(root, work_id)
    source, _, _ = _paths(stage, work_id)

    def checkpoint(phase: str) -> None:
        if phase == "after-validated":
            _project_check(root, acceptance)
            if after_live_check is not None:
                after_live_check()

    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != record["before"] or _files(source) != record["after"]:
            raise PipelineError("work changed after Creeds.json preflight")
        result = _commit_generation(
            root, target, source, work_id=work_id,
            before=record["before"], after=record["after"],
            existed=True, replacement=True,
            operation_kind="creeds-json-metadata-rebind-v1",
            result_status="creeds-json-metadata-rebound",
            accepted_editions=1, fail_at=checkpoint,
        )
    result["stage_receipt_sha256"] = STAGE_RECEIPTS[work_id]
    result["live_adapter_verified"] = True
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, choices=sorted(STAGE_RECEIPTS))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = install(args.work, root=args.root)
    else:
        _, _, record = preflight(args.work, root=args.root)
        result = {
            "status": "ready-stage-only", "work_id": args.work,
            "stage_receipt_sha256": STAGE_RECEIPTS[args.work],
            "before_file_count": len(record["before"]),
            "after_file_count": len(record["after"]),
            "before_manifest_sha256": hashlib.sha256(
                json.dumps(record["before"], sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "after_manifest_sha256": hashlib.sha256(
                json.dumps(record["after"], sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "changed_paths": record["changed_paths"], "stage_adapter_verified": True,
        }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
