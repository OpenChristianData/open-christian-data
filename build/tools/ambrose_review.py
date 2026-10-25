"""Shared operations for existing review commands."""

from __future__ import annotations

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
import os
import uuid
from collections.abc import Callable
from pathlib import Path


def install(work_id: str, *, root_override: Path | None=None, fail_at: Callable[[str], None] | None=None, CONTRACT, PINS, _checked_generation, _copy_generation, _external_dependencies, _now, _read_json, preflight) -> dict[str, object]:
    """Atomically swap one work generation, retaining identity-checked rollback."""
    check = preflight(work_id, root_override=root_override)
    root, stage = Path(check["target_root"]), Path(check["stage"])
    work = Path("library/works") / work_id
    target = root / work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        check = preflight(work_id, root_override=root_override)
        before, after = check["before"], check["after"]
        if _files(target) != before or _files(stage / work) != after:
            raise PipelineError("Ambrose generation changed after preflight")
        operation = root / "library/.sidecar-operations" / ("npnf210-" + work_id.removeprefix("ambrose-of-milan-") + "-" + uuid.uuid4().hex[:12])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ("incoming", "previous", "failed-new"))
        journal_path = operation / "operation.json"
        journal: dict[str, object] = {"contract": CONTRACT, "work_id": work_id, "phase": "created", "stage": stage.as_posix(), "receipt_sha256": PINS[work_id]["receipt"], "before": before, "after": after, "updated_at": _now()}
        _write_json_durable(journal_path, journal)
        moved = live = False
        try:
            _copy_generation(stage / work, incoming, after)
            if _files(target) != before:
                raise PipelineError("Ambrose acquired generation changed during copy")
            journal.update(phase="prepared", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-copy")
            refreshed = preflight(work_id, root_override=root_override)
            if refreshed["before"] != before or refreshed["after"] != after:
                raise PipelineError("Ambrose evidence changed before swap")
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            journal.update(phase="previous-moved", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-old-rename")
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            journal.update(phase="new-live", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-new-rename")
            form = _read_json(target / "work.json")["textual_forms"][0]
            edition_record = form["editions"][0]
            edition = work / "forms" / form["textual_form_id"] / "editions" / edition_record["edition_id"]
            identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"], "edition_id": edition_record["edition_id"], "acquisition_id": edition_record["acquisition_ids"][0]}
            _checked_generation(root, work=work, edition=edition, identity=identity, after=after)
            if fail_at:
                fail_at("after-postcheck")
            _external_dependencies(root, _files(stage), work=work, fixture=root_override is not None)
            journal.update(phase="complete", updated_at=_now())
            _write_json_durable(journal_path, journal)
            return {"status": "installed-and-validated", "work_id": work_id, "operation": operation.as_posix(), "before_count": len(before), "after_count": len(after), "projection_rows": 1}
        except BaseException:
            try:
                if live:
                    if _files(target) != after:
                        raise PipelineError("Ambrose live generation differs during rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != before:
                        raise PipelineError("Ambrose previous generation differs during rollback")
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != before:
                        raise PipelineError("Ambrose rollback restored wrong bytes")
                journal.update(phase="rolled-back" if moved else "failed-before-swap", updated_at=_now())
                _write_json_durable(journal_path, journal)
            except BaseException as rollback_error:
                journal.update(phase="recovery-required", rollback_error=str(rollback_error), updated_at=_now())
                _write_json_durable(journal_path, journal)
                raise PipelineError(f"Ambrose rollback requires recovery: {operation}") from rollback_error
            raise
