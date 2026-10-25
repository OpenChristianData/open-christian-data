"""Guarded whole-work install for the staged Confessions electronic witness.

Default is read-only. Apply replaces only the complete Confessions work folder
after exact before/after and external-source checks, retaining rollback bytes.
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
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable

ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/augustine-confessions")
EDITION = Path("forms/augustine-confessions-ccel-npnf101-retained-en/editions/augustine-confessions-ccel-npnf101-electronic")
RECEIPT = ROOT / "plans/2026-09-22-source-preflight/augustine-confessions-electronic-acceptance-stage-20260926.json"
CONTRACT = "ocd-confessions-electronic-child-acceptance-stage-v1"
FIXTURE_MARKER = ".ocd-confessions-install-fixture"


def digest(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def copy_files(source: Path, destination: Path, expected: dict[str, str]) -> None:
    if _io_path(destination).exists():
        raise PipelineError(f"Confessions copy destination exists: {destination}")
    _io_path(destination).mkdir(parents=True)
    for relative, checksum in expected.items():
        source_path = _io_path(source / relative)
        target = _io_path(destination / relative)
        if not source_path.is_file() or digest(source_path) != checksum:
            raise PipelineError(f"Confessions copy source differs: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
    if _files(destination) != expected:
        raise PipelineError("Confessions copied file generation differs")


def dependencies(root: Path, stage: Path, *, fixture: bool) -> dict[str, str]:
    prefix = WORK.as_posix() + "/"
    result = {}
    for relative, expected in _files(stage).items():
        if relative.startswith(prefix):
            continue
        parts = Path(relative).parts
        if not parts or ".." in parts:
            raise PipelineError(f"Confessions unsafe external dependency: {relative}")
        path = (
            root / relative
            if fixture or parts[0] not in {"raw", "reports", "exports"}
            else resolve_repo_path(root, relative)
        )
        if not _io_path(path).is_file() or digest(path) != expected:
            raise PipelineError(f"Confessions external evidence differs: {relative}")
        result[relative] = expected
    return result


def scoped(root: Path, stage: Path, before: dict[str, str], after: dict[str, str]) -> None:
    if len(before) != 3 or len(after) != 16:
        raise PipelineError("Confessions complete-generation file counts differ")
    acquisition = (EDITION / "acquisitions/augustine-confessions-ccel-npnf101-acquired.json").as_posix()
    acceptance = (EDITION / "acceptance.json").as_posix()
    master = (EDITION / "master.tei.xml").as_posix()
    if any(path not in before for path in ("work.json", "state.json", acquisition)):
        raise PipelineError("Confessions current three-file work generation differs")
    if after.get(acquisition) != before[acquisition]:
        raise PipelineError("Confessions acquisition was changed")
    allowed = {"work.json", "state.json", acceptance, master}
    evidence_prefix = "integration/confessions-npnf101-electronic-v1/"
    for path in set(before) | set(after):
        if before.get(path) == after.get(path):
            continue
        if path in allowed:
            continue
        if path.startswith(evidence_prefix) and path not in before and path in after:
            continue
        raise PipelineError(f"Confessions unrelated work path differs: {path}")
    old_work = json.loads(_io_path(root / WORK / "work.json").read_bytes())
    new_work = json.loads(_io_path(stage / WORK / "work.json").read_bytes())
    expected_work = json.loads(json.dumps(old_work))
    edition = expected_work["textual_forms"][0]["editions"][0]
    if "category" in edition:
        raise PipelineError("Confessions edition is already categorized")
    edition["category"] = "prose"
    if expected_work != new_work:
        raise PipelineError("Confessions work identity differs beyond prose category")
    old_state = json.loads(_io_path(root / WORK / "state.json").read_bytes())
    new_state = json.loads(_io_path(stage / WORK / "state.json").read_bytes())
    old_targets = {target["target_id"]: target for target in old_state["targets"]}
    new_targets = {target["target_id"]: target for target in new_state["targets"]}
    if set(old_targets) != set(new_targets) or old_state.get("work_id") != new_state.get("work_id"):
        raise PipelineError("Confessions state target identity differs")
    for target_id, old in old_targets.items():
        new = new_targets[target_id]
        if target_id.endswith("-acquired"):
            if new != old:
                raise PipelineError("Confessions acquisition state changed")
            continue
        expected_evidence = old["evidence"] + [(WORK / EDITION / name).as_posix() for name in ("master.tei.xml", "acceptance.json")]
        if old["stage"] != "acquired" or new["stage"] != "accepted" or new["evidence"] != expected_evidence:
            raise PipelineError("Confessions edition state transition differs")
        if any(old.get(key) != new.get(key) for key in old if key not in {"stage", "reason", "updated_at", "evidence"}):
            raise PipelineError("Confessions edition state identity changed")
    if after[master] != after[(Path(evidence_prefix) / "candidate.tei.xml").as_posix()]:
        raise PipelineError("Confessions master differs from accepted candidate")
    record = validate_acceptance(_io_path(stage / WORK / acceptance), root=_io_path(stage))
    if record["promotion"]["status"] != "promoted" or record["identity"]["work_id"] != "augustine-confessions" or record["scope"]["kind"] != "selection":
        raise PipelineError("Confessions staged acceptance scope differs")


def preflight(receipt: Path = RECEIPT, *, root_override: Path | None = None) -> tuple[dict, Path, Path, bool]:
    receipt = receipt.resolve(strict=True)
    record = json.loads(_io_path(receipt).read_bytes())
    if record.get("contract") != CONTRACT or record.get("status") != "staged-only" or record.get("work_id") != "augustine-confessions":
        raise PipelineError("Confessions stage receipt differs")
    if Path(record["canonical_root"]).resolve(strict=True) != ROOT.resolve(strict=True):
        raise PipelineError("Confessions receipt targets another canonical repository")
    stage = Path(record["stage_root"]).resolve(strict=True)
    fixture = root_override is not None
    root = root_override.resolve(strict=True) if fixture else ROOT.resolve(strict=True)
    if fixture:
        scratch = Path("C:/Scratch").resolve(strict=True)
        if root.parent != scratch or not _io_path(root / FIXTURE_MARKER).is_file():
            raise PipelineError("Confessions root override requires a marked direct C:/Scratch fixture")
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("Confessions install roots overlap")
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != record["before"] or after != record["after"]:
        raise PipelineError("Confessions complete-generation receipt is stale")
    if sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path)) != record["changed_paths"]:
        raise PipelineError("Confessions changed-path inventory differs")
    scoped(root, stage, before, after)
    dependencies(root, stage, fixture=fixture)
    if digest(ROOT / "build/tools/stage_augustine_confessions_electronic_acceptance.py") != record["external_dependencies"]["build/tools/stage_augustine_confessions_electronic_acceptance.py"]:
        raise PipelineError("Confessions staging implementation changed")
    return record, root, stage, fixture


def install(receipt: Path = RECEIPT, *, root_override: Path | None = None, fail_at: Callable[[str], None] | None = None) -> dict[str, object]:
    record, root, stage, fixture = preflight(receipt, root_override=root_override)
    target, source = root / WORK, stage / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != record["before"] or _files(source) != record["after"]:
            raise PipelineError("Confessions generation changed while acquiring lock")
        dependencies(root, stage, fixture=fixture)
        operation = root / "library/.sidecar-operations" / ("ac032-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ("incoming", "previous", "failed-new"))
        journal_path = operation / "operation.json"
        journal: dict[str, object] = dict(contract="ocd-confessions-work-swap-v1", work_id="augustine-confessions", phase="created", before=record["before"], after=record["after"], receipt=receipt.resolve().as_posix(), updated_at=now())
        _write_json_durable(journal_path, journal)
        moved = live = False
        try:
            copy_files(source, incoming, record["after"])
            if _files(target) != record["before"]:
                raise PipelineError("Confessions current work changed during incoming copy")
            journal.update(phase="prepared", updated_at=now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-copy")
            dependencies(root, stage, fixture=fixture)
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            journal.update(phase="previous-moved", updated_at=now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-old-rename")
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            journal.update(phase="new-live", updated_at=now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-new-rename")
            if _files(target) != record["after"]:
                raise PipelineError("Confessions installed generation differs")
            validate_acceptance(_io_path(target / EDITION / "acceptance.json"), root=_io_path(root))
            if fail_at:
                fail_at("after-validation")
            journal.update(phase="complete", updated_at=now())
            _write_json_durable(journal_path, journal)
            return dict(status="installed-and-validated", operation=operation.as_posix(), before_count=len(record["before"]), after_count=len(record["after"]), master_sha256=record["after"][(EDITION / "master.tei.xml").as_posix()])
        except BaseException:
            try:
                if live:
                    if _files(target) != record["after"]:
                        raise PipelineError("Confessions live generation differs during rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != record["before"]:
                        raise PipelineError("Confessions rollback previous generation differs")
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != record["before"]:
                        raise PipelineError("Confessions rollback restored wrong bytes")
                journal.update(phase="rolled-back" if moved else "failed-before-swap", updated_at=now())
                _write_json_durable(journal_path, journal)
            except BaseException as rollback_error:
                journal.update(phase="recovery-required", rollback_error=str(rollback_error), updated_at=now())
                _write_json_durable(journal_path, journal)
                raise PipelineError(f"Confessions rollback requires recovery: {operation}") from rollback_error
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, default=RECEIPT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = install(args.receipt)
    else:
        record, _root, _stage, _fixture = preflight(args.receipt)
        result = dict(status="ready", before_count=len(record["before"]), after_count=len(record["after"]), changed_paths=len(record["changed_paths"]))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
