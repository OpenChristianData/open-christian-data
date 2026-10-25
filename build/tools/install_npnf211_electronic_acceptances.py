"""Preflight, then optionally install one pinned NPNF211 electronic edition.

The default command is read-only. ``--apply`` uses the shared guarded work swap.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import (
    _commit_generation, _files, _io_path, _resolve_work_paths,
    _validate_promoted_tree, _validate_state_transition,
)


ROOT = Path(__file__).resolve().parents[2]
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/npnf211-electronic-acceptance-stage-20260926-e")
RECEIPT_SHA256 = "6c0f5221dcd6957cab15c5c8ccc765f20f745a9366e8b40fbfa34a5d2ab8ed56"
WORKS = {
    "sulpitius-severus-selected-works",
    "vincent-of-lerins-commonitory",
    "john-cassian-selected-works",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, object]:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _category_only(before: Path, after: Path, *, work_id: str) -> None:
    old, new = _json(before), _json(after)
    if old["work_id"] != work_id or new["work_id"] != work_id:
        raise PipelineError("NPNF211 work identity changed")
    if len(new["textual_forms"]) != 1 or len(new["textual_forms"][0]["editions"]) != 1:
        raise PipelineError("NPNF211 edition shape changed")
    edition = new["textual_forms"][0]["editions"][0]
    if edition.pop("category", None) != "prose" or new != old:
        raise PipelineError("NPNF211 stage changes more than edition prose category")


def preflight(work_id: str, *, root: Path = ROOT) -> dict[str, object]:
    if work_id not in WORKS:
        raise PipelineError("work outside pinned NPNF211 tranche")
    root, stage, target, source = _resolve_work_paths(root, STAGE, work_id)
    if _sha(stage / "stage-receipt.json") != RECEIPT_SHA256:
        raise PipelineError("NPNF211 stage receipt differs from exact pin")
    receipt = _json(stage / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-npnf211-electronic-acceptance-stage-v1"
            or receipt.get("status") != "staged-only" or receipt.get("canonical_install") is not False
            or receipt.get("work_count") != 3
            or {row["work_id"] for row in receipt["works"]} != WORKS):
        raise PipelineError("NPNF211 stage contract differs")
    row = next(row for row in receipt["works"] if row["work_id"] == work_id)
    before, after = _files(target), _files(source)
    if before != row["before"] or after != row["after"]:
        raise PipelineError("NPNF211 canonical preimage or staged generation changed")
    for path, digest in before.items():
        if path in {"work.json", "state.json"}:
            continue
        if after.get(path) != digest:
            raise PipelineError(f"NPNF211 stage changes inherited authority: {path}")
    _category_only(target / "work.json", source / "work.json", work_id=work_id)
    records = _validate_promoted_tree(stage, source, work_id=work_id)
    if len(records) != 1 or records[0]["identity"] != row["identity"]:
        raise PipelineError("NPNF211 staged acceptance identity differs")
    master = records[0]["promotion"]["master"]["path"]
    evidence = {row["identity"]["edition_id"]: (master, Path(master).with_name("acceptance.json").as_posix())}
    _validate_state_transition(target, source, existed=True, replacement=False,
                               accepted_evidence_by_edition=evidence)
    validate_state(_io_path(source / "state.json"), root=_io_path(stage))
    acceptance = stage / Path(master).with_name("acceptance.json")
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    projection = project_accepted_prose(stage, acceptance_path=_io_path(acceptance))
    errors = verify_accepted_prose(stage, acceptance_path=_io_path(acceptance),
                                   rows=projection["rows"], receipt=projection["receipt"])
    if len(projection["rows"]) != row["projection_rows"] or projection["receipt"].get("unsupported") or errors:
        raise PipelineError(f"NPNF211 actual-master prose projection differs: {errors[:2]}")
    for path in _io_path(stage).rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(_io_path(stage))
        if relative.parts[:2] == ("library", "works") or relative.as_posix() == "stage-receipt.json":
            continue
        live = root / relative
        if not _io_path(live).is_file() or _sha(live) != _sha(path):
            raise PipelineError(f"NPNF211 external dependency changed: {relative}")
    return {"work_id": work_id, "source_root_id": row["source_root_id"],
            "before": before, "after": after, "projection_rows": len(projection["rows"]),
            "stage_receipt_sha256": RECEIPT_SHA256, "status": "preflight-pass"}


def install(work_id: str, *, fail_at: Callable[[str], None] | None = None) -> dict[str, object]:
    root, stage, target, source = _resolve_work_paths(ROOT, STAGE, work_id)
    with ExitStack() as locks:
        for path in sorted({target, source}, key=lambda item: item.as_posix()):
            locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        checked = preflight(work_id, root=root)
        return _commit_generation(root, target, source, work_id=work_id,
                                  before=checked["before"], after=checked["after"],
                                  existed=True, replacement=False,
                                  operation_kind="initial-install", result_status="installed-and-validated",
                                  accepted_editions=1, fail_at=fail_at)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", choices=sorted(WORKS), required=True)
    parser.add_argument("--apply", action="store_true", help="Install after exact read-only preflight")
    args = parser.parse_args()
    result = install(args.work_id) if args.apply else preflight(args.work_id)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
