"""Preflight or guardedly install the pinned LIB-040 Harmony electronic master.

The default command is read-only. Apply swaps only the complete Harmony work
generation, retaining the prior bytes and an operation journal for recovery.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _write_json_durable

ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/augustine-harmony-of-gospels")
EDITION = Path("forms/augustine-harmony-of-gospels-ccel-npnf106-retained-en/editions/augustine-harmony-of-gospels-ccel-npnf106-electronic")
STAGE = Path("C:/Scratch/h040s4")
RECEIPT = ROOT / "plans/2026-09-22-source-preflight/augustine-lib040-harmony-acceptance-stage-20260926.json"
RECEIPT_SHA256 = "97c36d88dcdb7a2f8953617b6fbf6d5ff77c6c3efe4b2aaf7779ac1220687d62"
PROFILE = "ocd-lib040-harmony-seven-source-divisions-v1"
UNITS = ["i", "ii", "iii", "I", "II", "III", "IV"]
CURRENT_PROJECTION_RECEIPT_SHA256 = "307ef32a88e1d88426e09b4b73fc08233740078845dbadd2fba18e638533abaa"
CURRENT_NATIVE_DOCUMENTS_SHA256 = "1b854764070c46257e16d0ced0e02392f69a9c6a9ed729e2c70d2043f3c4aa87"
CURRENT_NATIVE_CONTENT_SHA256 = "97c44a3b873d9c52307953015ef1e9edf276e616caaf55e36b16a7b8f6e58e00"
FIXTURE_MARKER = ".ocd-lib040-harmony-install-fixture"
OPERATION_CONTRACT = "ocd-lib040-harmony-work-swap-v1"


def _sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bound_projection(root: Path, receipt: dict) -> dict:
    acceptance = io_path(root / WORK / EDITION / "acceptance.json")
    projection = project_accepted_prose(root, acceptance_path=acceptance)
    problems = verify_accepted_prose(root, acceptance_path=acceptance, rows=projection["rows"], receipt=projection["receipt"])
    if problems or len(projection["rows"]) != 7 or projection["receipt"].get("unsupported"):
        raise PipelineError(f"Harmony seven-row prose projection differs: {problems[:3]}")
    binding = projection["receipt"].get("source_division_binding", {})
    if binding.get("profile") != PROFILE or binding.get("unit_numbers") != UNITS:
        raise PipelineError("Harmony source-attested projection profile differs")
    if [len(row["text"]) for row in projection["rows"]] != receipt["projection_unit_text_lengths"]:
        raise PipelineError("Harmony row lengths differ from stage receipt")
    if [hashlib.sha256(row["text"].encode()).hexdigest() for row in projection["rows"]] != receipt["projection_unit_text_sha256"]:
        raise PipelineError("Harmony row text hashes differ from stage receipt")
    receipt_bytes = json.dumps(projection["receipt"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    if hashlib.sha256(receipt_bytes).hexdigest() != CURRENT_PROJECTION_RECEIPT_SHA256:
        raise PipelineError("Harmony current native projection receipt differs from installer pin")
    return projection


def _accepted_generation(root: Path, receipt: dict, work_files: dict[str, str]) -> None:
    if _files(root / WORK) != work_files:
        raise PipelineError("Harmony accepted work generation differs")
    acceptance = io_path(root / WORK / EDITION / "acceptance.json")
    if _sha(acceptance) != receipt["acceptance_sha256"] or _sha(root / WORK / EDITION / "master.tei.xml") != receipt["master_sha256"]:
        raise PipelineError("Harmony accepted master or record hash differs")
    validated = validate_acceptance(acceptance, root=io_path(root))
    if validated["promotion"]["status"] != "promoted" or validated["identity"]["work_id"] != "augustine-harmony-of-gospels":
        raise PipelineError("Harmony public acceptance differs")
    state = validate_state(io_path(root / WORK / "state.json"), root=io_path(root))
    edition_id = validated["identity"]["edition_id"]
    targets = [item for item in state["targets"] if item["target_id"] == edition_id]
    if len(targets) != 1 or targets[0]["stage"] != "accepted":
        raise PipelineError("Harmony accepted edition state differs")
    _bound_projection(root, receipt)


def _external_evidence(root: Path, stage: Path, receipt: dict, *, fixture: bool) -> None:
    prefix = WORK.as_posix() + "/"
    for relative, expected in receipt["after"].items():
        if relative.startswith(prefix):
            continue
        current = root / relative if fixture or not relative.startswith(("raw/", "reports/", "exports/")) else resolve_repo_path(root, relative)
        if not io_path(current).is_file() or _sha(current) != expected or _sha(stage / relative) != expected:
            raise PipelineError(f"Harmony external source or evidence differs: {relative}")


def preflight(*, root_override: Path | None = None) -> dict:
    """Check the exact current/staged generations without changing either."""
    if _sha(RECEIPT) != RECEIPT_SHA256:
        raise PipelineError("Harmony stage receipt differs from installer pin")
    receipt = json.loads(io_path(RECEIPT).read_bytes())
    stage = STAGE.resolve(strict=True)
    root = root_override.resolve(strict=True) if root_override is not None else ROOT.resolve(strict=True)
    fixture = root_override is not None
    if fixture and not io_path(root / FIXTURE_MARKER).is_file():
        raise PipelineError("Harmony root override requires a marked fixture")
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("Harmony stage and target roots overlap")
    if (receipt.get("contract") != "ocd-lib040-harmony-electronic-acceptance-stage-v1"
            or receipt.get("status") != "staged-only" or receipt.get("work_id") != "augustine-harmony-of-gospels"
            or Path(receipt["stage_root"]).resolve(strict=True) != stage
            or receipt.get("projection_profile") != PROFILE or receipt.get("projection_unit_numbers") != UNITS
            or receipt.get("actual_master_projection_rows") != 7
            or receipt.get("independent_projection_errors") != []
            or receipt.get("canonical_install") != "not performed"):
        raise PipelineError("Harmony stage identity or projection route differs")
    before_all, after_all = receipt["before"], receipt["after"]
    prefix = WORK.as_posix() + "/"
    if set(before_all) - set(after_all) or any(not path.startswith(prefix) for path in before_all):
        raise PipelineError("Harmony receipt before-generation paths differ")
    before = {path[len(prefix):]: digest for path, digest in before_all.items() if digest is not None}
    staged_after = {path[len(prefix):]: digest for path, digest in after_all.items() if path.startswith(prefix)}
    handoff = receipt["work_local_handoff"]
    if not handoff.startswith(prefix) or handoff in after_all or handoff in before_all:
        raise PipelineError("Harmony preserved handoff path differs")
    handoff_relative = handoff[len(prefix):]
    handoff_sha256 = receipt["work_local_handoff_sha256"]
    if _sha(root / handoff) != handoff_sha256:
        raise PipelineError("Harmony canonical work-local handoff differs")
    before[handoff_relative] = handoff_sha256
    after = {**staged_after, handoff_relative: handoff_sha256}
    if len(before) != 4 or len(staged_after) != 16 or len(after_all) != 21:
        raise PipelineError("Harmony complete-generation counts differ")
    if _files(root / WORK) != before or _files(stage / WORK) != staged_after or _files(stage) != after_all:
        raise PipelineError("Harmony canonical or staged generation differs from exact receipt")
    work_before = json.loads(io_path(root / WORK / "work.json").read_bytes())
    work_after = json.loads(io_path(stage / WORK / "work.json").read_bytes())
    expected_work = json.loads(json.dumps(work_before))
    edition = expected_work["textual_forms"][0]["editions"][0]
    if edition.get("category") is not None or edition.get("language") != "en":
        raise PipelineError("Harmony canonical category or language baseline differs")
    edition["category"] = "prose"
    if work_after != expected_work:
        raise PipelineError("Harmony staged work differs beyond prose category rebind")
    state_before = json.loads(io_path(root / WORK / "state.json").read_bytes())
    state_after = json.loads(io_path(stage / WORK / "state.json").read_bytes())
    expected_state = json.loads(json.dumps(state_before))
    target = next(item for item in expected_state["targets"] if item["target_id"] == edition["edition_id"])
    accepted_target = next(item for item in state_after["targets"] if item["target_id"] == edition["edition_id"])
    if target["stage"] != "acquired" or accepted_target["stage"] != "accepted" or accepted_target["reason"] != PROMOTED_MASTER_REASON:
        raise PipelineError("Harmony accepted state transition differs")
    if accepted_target["evidence"] != target["evidence"] + [(WORK / EDITION / name).as_posix() for name in ("master.tei.xml", "acceptance.json")]:
        raise PipelineError("Harmony accepted state evidence differs")
    for key in ("stage", "reason", "evidence", "updated_at"):
        target[key] = accepted_target[key]
    if expected_state != state_after:
        raise PipelineError("Harmony staged state differs beyond one edition transition")
    acquisition = (EDITION / "acquisitions/augustine-harmony-of-gospels-ccel-npnf106-acquired.json").as_posix()
    if before.get(acquisition) != after.get(acquisition):
        raise PipelineError("Harmony acquisition sidecar differs")
    for relative, digest in receipt["projection_code_sha256"].items():
        if _sha(ROOT / relative) != digest:
            raise PipelineError(f"Harmony projection code differs from stage receipt: {relative}")
    if (_sha(ROOT / "ocd_kernel/projection/categories/native_documents.py") != CURRENT_NATIVE_DOCUMENTS_SHA256
            or _sha(ROOT / "ocd_kernel/projection/native_content.py") != CURRENT_NATIVE_CONTENT_SHA256):
        raise PipelineError("Harmony current native projector or content checker differs from installer pin")
    if _sha(ROOT / receipt["stage_tool"]) != receipt["stage_tool_sha256"] or _sha(ROOT / receipt["work_local_handoff"]) != receipt["work_local_handoff_sha256"]:
        raise PipelineError("Harmony staging tool or handoff differs from receipt")
    _external_evidence(root, stage, receipt, fixture=fixture)
    _accepted_generation(stage, receipt, staged_after)
    return {"contract": "ocd-lib040-harmony-install-preflight-v1", "status": "pass-read-only", "canonical_action": "none", "root": root.as_posix(), "stage": stage.as_posix(), "receipt_sha256": RECEIPT_SHA256, "before": before, "after": after, "staged_work_count": len(staged_after), "preserved_handoff": handoff, "external_count": len(after_all) - len(staged_after), "master_sha256": receipt["master_sha256"], "acceptance_sha256": receipt["acceptance_sha256"], "projection_rows": 7, "historical_projection_receipt_sha256": receipt["projection_receipt_sha256"], "current_projection_receipt_sha256": CURRENT_PROJECTION_RECEIPT_SHA256}


def _copy_generation(source: Path, destination: Path, expected: dict[str, str], *, preserved_source: Path, preserved_relative: str, preserved_sha256: str) -> None:
    if io_path(destination).exists():
        raise PipelineError("Harmony incoming generation already exists")
    if expected.get(preserved_relative) != preserved_sha256 or _sha(preserved_source) != preserved_sha256:
        raise PipelineError("Harmony preserved handoff changed before copy")
    io_path(destination).mkdir(parents=True)
    for relative, digest in expected.items():
        if relative == preserved_relative:
            origin = io_path(preserved_source)
        else:
            origin = io_path(source / relative)
        target = io_path(destination / relative)
        if not origin.is_file() or _sha(origin) != digest:
            raise PipelineError(f"Harmony staged file changed during copy: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    if _files(destination) != expected:
        raise PipelineError("Harmony incoming generation differs")


def install(*, root_override: Path | None = None, fail_at: Callable[[str], None] | None = None) -> dict:
    """Install only the pinned stage and restore the prior work on failure."""
    checked = preflight(root_override=root_override)
    root = Path(checked["root"])
    stage = Path(checked["stage"])
    target = root / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        checked = preflight(root_override=root_override)
        before, after = checked["before"], checked["after"]
        operation = root / "library/.sidecar-operations" / ("lib040-harmony-" + uuid.uuid4().hex[:16])
        io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ("incoming", "previous", "failed-new"))
        journal_path = operation / "operation.json"
        journal: dict[str, object] = {"contract": OPERATION_CONTRACT, "work_id": "augustine-harmony-of-gospels", "phase": "created", "receipt_sha256": RECEIPT_SHA256, "stage": stage.as_posix(), "before": before, "after": after, "updated_at": _now()}
        _write_json_durable(journal_path, journal)
        moved = live = False
        try:
            handoff_relative = Path(checked["preserved_handoff"]).relative_to(WORK).as_posix()
            _copy_generation(stage / WORK, incoming, after, preserved_source=root / checked["preserved_handoff"], preserved_relative=handoff_relative, preserved_sha256=before[handoff_relative])
            if _files(target) != before:
                raise PipelineError("Harmony canonical work changed during copy")
            journal.update(phase="prepared", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-copy")
            refreshed = preflight(root_override=root_override)
            if refreshed["before"] != before or refreshed["after"] != after:
                raise PipelineError("Harmony generation changed before swap")
            os.replace(io_path(target), io_path(previous))
            moved = True
            journal.update(phase="previous-moved", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-old-rename")
            os.replace(io_path(incoming), io_path(target))
            live = True
            journal.update(phase="new-live", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-new-rename")
            receipt = json.loads(io_path(RECEIPT).read_bytes())
            _accepted_generation(root, receipt, after)
            if fail_at:
                fail_at("after-postcheck")
            _external_evidence(root, stage, receipt, fixture=root_override is not None)
            journal.update(phase="complete", updated_at=_now())
            _write_json_durable(journal_path, journal)
            return {"status": "installed-and-validated", "operation": operation.as_posix(), "before_count": len(before), "after_count": len(after), "projection_rows": 7, "master_sha256": receipt["master_sha256"]}
        except BaseException:
            try:
                if live:
                    if _files(target) != after:
                        raise PipelineError("Harmony live generation differs during rollback")
                    os.replace(io_path(target), io_path(failed_new))
                if moved:
                    if io_path(target).exists() or _files(previous) != before:
                        raise PipelineError("Harmony prior generation differs during rollback")
                    os.replace(io_path(previous), io_path(target))
                    if _files(target) != before:
                        raise PipelineError("Harmony rollback restored wrong bytes")
                journal.update(phase="rolled-back" if moved else "failed-before-swap", updated_at=_now())
                _write_json_durable(journal_path, journal)
            except BaseException as rollback_error:
                journal.update(phase="recovery-required", rollback_error=str(rollback_error), updated_at=_now())
                _write_json_durable(journal_path, journal)
                raise PipelineError(f"Harmony rollback requires recovery: {operation}") from rollback_error
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="install the exact pinned Harmony work generation")
    args = parser.parse_args()
    result = install() if args.apply else {key: value for key, value in preflight().items() if key not in {"before", "after"}}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
