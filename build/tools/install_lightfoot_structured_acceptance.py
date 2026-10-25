"""Guarded Lightfoot replacement of the historical blocked master.

The default command only checks and prints the staged manifest. ``--apply``
performs a full-work directory swap with a retained old-generation backup.
This route is specific to the blocked PG 50857 acceptance: the generic accepted
work replacement path deliberately admits fixtures only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from build.tools import prepare_lightfoot_structured_acceptance as route
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path


CONTRACT = "ocd-lightfoot-structured-install-manifest-v1"
DEFAULT_MANIFEST = Path(
    "plans/2026-08-31-sample-first-library-verification/artifacts/"
    "2026-09-10-structural-audit/118-lightfoot-structured-install-stage-20260926.json"
)
WORK_ID = route.IDENTITY["work_id"]
MASTER = Path("forms/lightfoot-english/editions/pg50857/master.tei.xml")
ACCEPTANCE = MASTER.with_name("acceptance.json")
EVIDENCE = route.EVIDENCE.relative_to(route.WORK)


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def _old_is_the_blocked_generation(target: Path, before: Mapping[str, str]) -> None:
    if (before.get(ACCEPTANCE.as_posix()) != route.HISTORICAL_ACCEPTANCE_SHA
            or before.get(MASTER.as_posix()) != route.HISTORICAL_MASTER_SHA):
        raise PipelineError("Lightfoot historical blocked generation changed")
    record = json.loads(_io_path(target / ACCEPTANCE).read_text(encoding="utf-8"))
    if (record.get("identity") != route.IDENTITY
            or record.get("promotion", {}).get("status") != "pending"
            or record.get("decision", {}).get("agent_assessment", {}).get("status") != "blocked"
            or [item.get("id") for item in record.get("decision", {}).get("blockers", [])]
            != ["missing-source-structure"]):
        raise PipelineError("Lightfoot historical acceptance is no longer the expected blocked record")


def _changes_are_scoped(before: Mapping[str, str], after: Mapping[str, str]) -> None:
    expected_existing = {"state.json", MASTER.as_posix(), ACCEPTANCE.as_posix()}
    for path in set(before) | set(after):
        if path.startswith(EVIDENCE.as_posix() + "/"):
            if path in before:
                raise PipelineError("Lightfoot new evidence directory already exists")
            continue
        if path in expected_existing:
            if path not in before or path not in after:
                raise PipelineError(f"Lightfoot replacement loses control file: {path}")
            continue
        if before.get(path) != after.get(path):
            raise PipelineError(f"Lightfoot replacement changes unrelated file: {path}")
    if not any(path.startswith(EVIDENCE.as_posix() + "/") for path in after):
        raise PipelineError("Lightfoot replacement lacks versioned evidence")


def _promoted_is_valid(promoted: Path, after: Mapping[str, str]) -> None:
    target = promoted / route.WORK
    record = validate_acceptance(target / ACCEPTANCE, root=promoted)
    validate_state(target / "state.json", root=promoted)
    if (record["identity"] != route.IDENTITY
            or record["promotion"]["status"] != "promoted"
            or record["decision"]["agent_assessment"]["status"] != "accepted"
            or record["review"]["coverage"]["status"] != "partial"
            or record["review"]["coverage"]["unreviewed"] != [
                "complete-retained-electronic-witness/unsampled-source-text-outside-33-risk-loci"
            ]
            or after[MASTER.as_posix()] != record["promotion"]["master"]["sha256"]):
        raise PipelineError("Lightfoot promoted acceptance has unexpected scope or state")
    historical = target / EVIDENCE / "inputs"
    if (_sha(historical / "historical-acceptance.json") != route.HISTORICAL_ACCEPTANCE_SHA
            or _sha(historical / "historical-flat-master.tei.xml") != route.HISTORICAL_MASTER_SHA):
        raise PipelineError("Lightfoot versioned historical records changed")


def prepare_manifest(root: Path, promoted: Path, output: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    promoted = promoted.resolve(strict=True)
    if root == promoted or root in promoted.parents or promoted in root.parents:
        raise PipelineError("Lightfoot roots overlap")
    if output.exists():
        raise PipelineError("Lightfoot install manifest output must be fresh")
    target = root / route.WORK
    source = promoted / route.WORK
    before, after = _files(target), _files(source)
    _old_is_the_blocked_generation(target, before)
    _changes_are_scoped(before, after)
    _promoted_is_valid(promoted, after)
    record: dict[str, object] = {
        "contract": CONTRACT,
        "prepared_at": _now(),
        "canonical_root": root.as_posix(),
        "promoted_root": promoted.as_posix(),
        "work_id": WORK_ID,
        "before": before,
        "after": after,
        "changed_paths": sorted(path for path in set(before) | set(after)
                                if before.get(path) != after.get(path)),
        "historical_acceptance_sha256": route.HISTORICAL_ACCEPTANCE_SHA,
        "historical_master_sha256": route.HISTORICAL_MASTER_SHA,
        "status": "staged-only",
    }
    _write(output, record)
    return record


def preflight(manifest: Path) -> tuple[dict[str, object], Path, Path]:
    record = json.loads(manifest.read_text(encoding="utf-8"))
    if record.get("contract") != CONTRACT or record.get("work_id") != WORK_ID:
        raise PipelineError("Lightfoot install manifest contract or identity differs")
    root = Path(record["canonical_root"]).resolve(strict=True)
    promoted = Path(record["promoted_root"]).resolve(strict=True)
    if root.as_posix() != record["canonical_root"] or promoted.as_posix() != record["promoted_root"]:
        raise PipelineError("Lightfoot install root changed")
    if root == promoted or root in promoted.parents or promoted in root.parents:
        raise PipelineError("Lightfoot install roots overlap")
    before, after = _files(root / route.WORK), _files(promoted / route.WORK)
    if before != record.get("before") or after != record.get("after"):
        raise PipelineError("Lightfoot install manifest is stale")
    if record.get("changed_paths") != sorted(path for path in set(before) | set(after)
                                            if before.get(path) != after.get(path)):
        raise PipelineError("Lightfoot changed-path inventory differs")
    _old_is_the_blocked_generation(root / route.WORK, before)
    _changes_are_scoped(before, after)
    _promoted_is_valid(promoted, after)
    return record, root, promoted


def _copy_work_tree(source: Path, destination: Path) -> None:
    """Copy only verified ordinary files using Windows extended-length paths."""
    source_io, destination_io = _io_path(source), _io_path(destination)
    for relative in _files(source):
        target = destination_io / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_io / relative, target)


def install(manifest: Path, *, fail_at: Callable[[str], None] | None = None) -> dict[str, object]:
    record, root, promoted = preflight(manifest)
    target = root / route.WORK
    source = promoted / route.WORK
    operation = root / ".tmp_audit" / f"lightfoot-structured-install-{uuid.uuid4().hex}"
    lock_target = target
    with acquire_jsonl_lock(lock_target):
        if _files(target) != record["before"] or _files(source) != record["after"]:
            raise PipelineError("Lightfoot generation changed while acquiring lock")
        operation.mkdir(parents=True, exist_ok=False)
        incoming = operation / "incoming"
        old = operation / "old"
        failed_new = operation / "failed-new"
        swapped_old = False
        swapped_new = False
        try:
            _copy_work_tree(source, incoming)
            if _files(incoming) != record["after"]:
                raise PipelineError("Lightfoot copied incoming generation differs")
            if fail_at is not None:
                fail_at("after-copy")
            if _files(target) != record["before"]:
                raise PipelineError("Lightfoot canonical generation changed during copy")
            os.replace(target, old)
            swapped_old = True
            if fail_at is not None:
                fail_at("after-old-rename")
            os.replace(incoming, target)
            swapped_new = True
            if fail_at is not None:
                fail_at("after-new-rename")
            if _files(target) != record["after"]:
                raise PipelineError("Lightfoot installed generation differs")
            validate_acceptance(target / ACCEPTANCE, root=root)
            validate_state(target / "state.json", root=root)
            if fail_at is not None:
                fail_at("after-validation")
            result: dict[str, object] = {
                "status": "installed-and-validated",
                "operation": operation.as_posix(),
                "old_generation": old.as_posix(),
                "before_file_count": len(record["before"]),
                "after_file_count": len(record["after"]),
                "master_sha256": record["after"][MASTER.as_posix()],
                "acceptance_sha256": record["after"][ACCEPTANCE.as_posix()],
            }
            _write(operation / "result.json", result)
            return result
        except Exception:
            if swapped_new:
                if _files(target) == record["after"]:
                    os.replace(target, failed_new)
                else:
                    raise PipelineError(
                        "Lightfoot new generation changed after swap; old generation retained for recovery"
                    )
            if swapped_old and not target.exists():
                os.replace(old, target)
                if _files(target) != record["before"]:
                    raise PipelineError("Lightfoot rollback restored unexpected bytes")
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.manifest) if args.apply else {
        "status": "ready", "changed_paths": len(preflight(args.manifest)[0]["changed_paths"])
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
