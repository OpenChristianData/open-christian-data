"""Read-only preflight or guardedly install the frozen Schaff complete-volume work stage.

The default command only checks bytes and authority. ``--apply`` swaps the one
work directory under a lock with a journal and byte-checked rollback.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import uuid

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "creeds-of-christendom-vol-1"
WORK = Path("library/works") / WORK_ID
EDITION = Path("forms/creeds-of-christendom-vol-1-english/editions/creeds-of-christendom-vol-1-retained-electronic-witness")
ACQUISITION = EDITION / "acquisitions/creeds-of-christendom-vol-1-retained-source.json"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
EVIDENCE = Path("integration/schaff-complete-electronic-v1")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/schaff-complete-electronic-acceptance-stage-20260927-v4")
RECEIPT = STAGE / "schaff-stage-receipt.json"
RECEIPT_SHA = "f4d1ee79479288047d1197cc612c03a00d7c45cfe0f8687c62b49bf9fee10307"
CONTRACT = "ocd-schaff-complete-electronic-stage-v1"
SOURCE_SHA = "450960af42f600534f15429546e0a00696a9fbfc4ea32df55545ef5a02c491e7"
MASTER_SHA = "3b25658cecda9c5c6f054d4caa4b21f4363da76cc28c4fca80f21fe9bcbffcbf"
FIXTURE_PARENT = Path("D:/Library/Open Christian Data/candidate-reviews")
FIXTURE_MARKER = ".ocd-schaff-complete-install-fixture"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _copy_generation(source: Path, target: Path, expected: dict[str, str]) -> None:
    if _io_path(target).exists():
        raise PipelineError("Schaff incoming generation already exists")
    _io_path(target).mkdir(parents=True)
    for relative, checksum in expected.items():
        original = _io_path(source / relative)
        destination = _io_path(target / relative)
        if not original.is_file() or _sha(original) != checksum:
            raise PipelineError(f"Schaff staged file changed: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
    if _files(target) != expected:
        raise PipelineError("Schaff incoming generation differs")


def _dependencies(stage: Path) -> None:
    prefix = WORK.as_posix() + "/"
    for relative, checksum in _files(stage).items():
        if relative.startswith(prefix) or relative == RECEIPT.name:
            continue
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise PipelineError(f"unsafe Schaff staged dependency: {relative}")
        source = resolve_repo_path(ROOT, relative) if path.parts[0] in {"raw", "reports", "exports"} else ROOT / path
        if not _io_path(source).is_file() or _sha(source) != checksum:
            raise PipelineError(f"Schaff source or authority changed: {relative}")


def _scope(root: Path, stage: Path, before: dict[str, str], after: dict[str, str]) -> None:
    if len(before) != 3 or len(after) != 25 or set(before) != {"work.json", "state.json", ACQUISITION.as_posix()}:
        raise PipelineError("Schaff complete work generation differs")
    if after.get(ACQUISITION.as_posix()) != before[ACQUISITION.as_posix()]:
        raise PipelineError("Schaff acquisition changed")
    allowed = {"work.json", "state.json", ACCEPTANCE.as_posix(), MASTER.as_posix()}
    prefix = EVIDENCE.as_posix() + "/"
    for path in set(before) | set(after):
        if before.get(path) == after.get(path):
            continue
        if path in allowed or path.startswith(prefix) and path not in before and path in after:
            continue
        raise PipelineError(f"Schaff unrelated work path differs: {path}")
    old_work = json.loads(_io_path(root / WORK / "work.json").read_bytes())
    new_work = json.loads(_io_path(stage / WORK / "work.json").read_bytes())
    expected = json.loads(json.dumps(old_work))
    edition = expected["textual_forms"][0]["editions"][0]
    if edition.get("category") is not None:
        raise PipelineError("Schaff edition is already categorized")
    edition["category"] = "prose"
    if expected != new_work:
        raise PipelineError("Schaff work metadata differs beyond prose category")
    old_state = json.loads(_io_path(root / WORK / "state.json").read_bytes())
    new_state = json.loads(_io_path(stage / WORK / "state.json").read_bytes())
    old_targets = {row["target_id"]: row for row in old_state["targets"]}
    new_targets = {row["target_id"]: row for row in new_state["targets"]}
    if old_targets.keys() != new_targets.keys():
        raise PipelineError("Schaff state target identities differ")
    for target_id, old in old_targets.items():
        new = new_targets[target_id]
        if target_id != EDITION.name:
            if new != old:
                raise PipelineError("Schaff acquisition state changed")
            continue
        additions = [(WORK / MASTER).as_posix(), (WORK / ACCEPTANCE).as_posix()]
        if (old["stage"] != "acquired" or new["stage"] != "accepted"
                or new["evidence"] != old["evidence"] + additions
                or any(old.get(key) != new.get(key) for key in old if key not in {"stage", "reason", "updated_at", "evidence"})):
            raise PipelineError("Schaff edition state transition differs")
    if after[MASTER.as_posix()] != after[(EVIDENCE / "candidate.tei.xml").as_posix()]:
        raise PipelineError("Schaff master differs from accepted candidate")
    acceptance = validate_acceptance(_io_path(stage / WORK / ACCEPTANCE), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if (acceptance["identity"]["work_id"] != WORK_ID
            or acceptance["promotion"]["status"] != "promoted"
            or acceptance["decision"]["human_decision"]["status"] != "not-recorded"
            or acceptance["promotion"]["master"]["sha256"] != after[MASTER.as_posix()]):
        raise PipelineError("Schaff staged acceptance differs")


def preflight(*, root_override: Path | None = None) -> tuple[dict, Path, Path, bool]:
    if not _io_path(RECEIPT).is_file() or _sha(RECEIPT) != RECEIPT_SHA:
        raise PipelineError("Schaff frozen stage receipt differs")
    record = json.loads(_io_path(RECEIPT).read_bytes())
    if (record.get("contract") != CONTRACT or record.get("status") != "staged-only"
            or record.get("work_id") != WORK_ID or record.get("installation") != "not-performed"
            or Path(record.get("stage_root", "")).resolve(strict=True) != STAGE.resolve(strict=True)
            or Path(record.get("canonical_root", "")).resolve(strict=True) != ROOT.resolve(strict=True)):
        raise PipelineError("Schaff stage receipt contract or roots differ")
    stage = STAGE.resolve(strict=True)
    fixture = root_override is not None
    root = root_override.resolve(strict=True) if fixture else ROOT.resolve(strict=True)
    if fixture:
        parent = FIXTURE_PARENT.resolve(strict=True)
        if parent not in root.parents or not _io_path(root / FIXTURE_MARKER).is_file():
            raise PipelineError("Schaff override requires a marked candidate-review fixture")
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("Schaff install roots overlap")
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != record["before"] or after != record["after"]:
        raise PipelineError("Schaff complete-generation receipt is stale")
    _scope(root, stage, before, after)
    _dependencies(stage)
    if (record["source_sha256"] != SOURCE_SHA or record["accepted_master_sha256"] != MASTER_SHA
            or after[MASTER.as_posix()] != MASTER_SHA or record["projection_rows"] != 5):
        raise PipelineError("Schaff source, master, or projection pins differ")
    return record, root, stage, fixture


def install(*, root_override: Path | None = None, fail_at: Callable[[str], None] | None = None) -> dict:
    record, root, stage, fixture = preflight(root_override=root_override)
    target, source = root / WORK, stage / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != record["before"] or _files(source) != record["after"]:
            raise PipelineError("Schaff work changed while acquiring lock")
        _dependencies(stage)
        operation = root / "library/.sidecar-operations" / ("schaff-complete-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ("incoming", "previous", "failed-new"))
        journal = dict(contract="ocd-schaff-complete-work-swap-v1", work_id=WORK_ID, phase="created",
                       before=record["before"], after=record["after"], receipt=RECEIPT.as_posix(), updated_at=_now())
        _write_json_durable(operation / "operation.json", journal)
        moved = live = False
        try:
            _copy_generation(source, incoming, record["after"])
            if _files(target) != record["before"]:
                raise PipelineError("Schaff work changed during incoming copy")
            journal.update(phase="prepared", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            if fail_at:
                fail_at("after-copy")
            _dependencies(stage)
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            journal.update(phase="previous-moved", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            if fail_at:
                fail_at("after-old-rename")
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            journal.update(phase="new-live", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            if fail_at:
                fail_at("after-new-rename")
            if _files(target) != record["after"]:
                raise PipelineError("Schaff installed generation differs")
            validate_acceptance(_io_path((stage if fixture else root) / WORK / ACCEPTANCE), root=_io_path(stage if fixture else root))
            if fail_at:
                fail_at("after-validation")
            journal.update(phase="complete", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            return dict(status="installed-and-validated", operation=operation.as_posix(),
                        before_count=len(record["before"]), after_count=len(record["after"]),
                        master_sha256=record["accepted_master_sha256"])
        except BaseException:
            try:
                if live:
                    if _files(target) != record["after"]:
                        raise PipelineError("Schaff live generation differs during rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != record["before"]:
                        raise PipelineError("Schaff previous generation differs during rollback")
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != record["before"]:
                        raise PipelineError("Schaff rollback restored wrong bytes")
                journal.update(phase="rolled-back" if moved else "failed-before-swap", updated_at=_now())
                _write_json_durable(operation / "operation.json", journal)
            except BaseException as exc:
                journal.update(phase="recovery-required", rollback_error=str(exc), updated_at=_now())
                _write_json_durable(operation / "operation.json", journal)
                raise PipelineError(f"Schaff rollback requires recovery: {operation}") from exc
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = install()
    else:
        record, _, _, _ = preflight()
        result = dict(status="ready-for-review", before_count=len(record["before"]), after_count=len(record["after"]))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
