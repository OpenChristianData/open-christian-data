"""Read-only by default; guardedly install the pinned On the Mysteries work generation."""

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

from build.tools import stage_npnf210_mysteries_acceptance as route
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable


ROOT = Path("\\\\?\\" + str(Path(__file__).resolve().parents[2]))
STAGE = Path("\\\\?\\D:\\Library\\Open Christian Data\\am26-mysteries-v5")
RECEIPT_SHA256 = "5f0bf7388291d1007e44644356de7aff13156671c59baa72d6311dc87a9bb0f5"
STAGE_WORK_GENERATION_SHA256 = "d8790779e9558752ab742e08bcd7ec535d6311954b542f9f605eff88a08c8831"
STAGE_ALL_GENERATION_SHA256 = "08b6a00c3d75e07d2faf9690b065ffd28d1f6dc92ba99ebbe156050423d4ec33"
FIXTURE_MARKER = ".ocd-npnf210-mysteries-install-fixture"
CONTRACT = "ocd-npnf210-mysteries-work-swap-v1"
WORK = route.WORK
EDITION = route.EDITION
EVIDENCE_PREFIX = route.EVIDENCE.relative_to(WORK).as_posix() + "/"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _files_sha(files: dict[str, str]) -> str:
    return hashlib.sha256((json.dumps(files, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _external_dependencies(root: Path, stage_files: dict[str, str], *, fixture: bool) -> None:
    prefix = WORK.as_posix() + "/"
    for relative, digest in stage_files.items():
        if relative == "stage-receipt.json" or relative.startswith(prefix):
            continue
        target = root / relative if fixture or not relative.startswith(("raw/", "reports/", "exports/")) else resolve_repo_path(root, relative)
        if not _io_path(target).is_file() or _sha(target) != digest:
            raise PipelineError(f"Ambrose outside dependency differs: {relative}")


def _checked_generation(root: Path, after: dict[str, str]) -> None:
    if _files(root / WORK) != after:
        raise PipelineError("Ambrose installed work generation differs")
    acceptance = root / EDITION / "acceptance.json"
    record = validate_acceptance(_io_path(acceptance), root=_io_path(root))
    if record["identity"] != route.IDENTITY or record["promotion"]["status"] != "promoted":
        raise PipelineError("Ambrose public accepted identity differs")
    state = validate_state(_io_path(root / WORK / "state.json"), root=_io_path(root))
    target = next((item for item in state["targets"] if item["target_id"] == route.IDENTITY["edition_id"]), None)
    if target is None or target["stage"] != "accepted":
        raise PipelineError("Ambrose accepted edition state differs")
    projection = project_accepted_prose(root, acceptance_path=_io_path(acceptance))
    errors = verify_accepted_prose(root, acceptance_path=_io_path(acceptance), rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 1 or projection["receipt"]["unsupported"]:
        raise PipelineError(f"Ambrose actual-master prose checker failed: {errors[:3]}")


def preflight(*, root_override: Path | None = None) -> dict[str, object]:
    """Recheck every pinned stage file, target preimage, and outside dependency."""
    stage = STAGE.resolve(strict=True)
    root = root_override.resolve(strict=True) if root_override is not None else ROOT.resolve(strict=True)
    fixture = root_override is not None
    if fixture and not _io_path(root / FIXTURE_MARKER).is_file():
        raise PipelineError("Ambrose root override requires the exact fixture marker")
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("Ambrose stage and target roots overlap")
    if stage.parent != Path("\\\\?\\D:\\Library\\Open Christian Data").resolve(strict=True):
        raise PipelineError("Ambrose stage left the pinned durable library")
    if _sha(stage / "stage-receipt.json") != RECEIPT_SHA256:
        raise PipelineError("Ambrose stage receipt differs from pin")
    receipt = _read_json(stage / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-npnf210-mysteries-acceptance-stage-v1"
            or receipt.get("status") != "staged-only" or receipt.get("canonical_install") is not False
            or Path(str(receipt.get("stage"))).resolve() != stage
            or receipt.get("public_validate_acceptance") != "pass"
            or receipt.get("public_validate_state") != "pass"
            or receipt.get("projection_rows") != 1 or receipt.get("projection_unsupported") != []
            or receipt.get("independent_projection_errors") != []):
        raise PipelineError("Ambrose staged receipt contract or postchecks differ")
    stage_files = _files(stage)
    staged = _files(stage / WORK)
    if _files_sha(stage_files) != STAGE_ALL_GENERATION_SHA256 or _files_sha(staged) != STAGE_WORK_GENERATION_SHA256:
        raise PipelineError("Ambrose staged generation differs from complete file pin")
    before = _files(root / WORK)
    expected_before = {}
    for path, preimage in receipt["preimages"].items():
        target = root / path
        if target.is_file() != preimage["exists"]:
            raise PipelineError(f"Ambrose canonical existence preimage differs: {path}")
        if preimage["exists"] and _sha(target) != preimage["sha256"]:
            raise PipelineError(f"Ambrose canonical byte preimage differs: {path}")
        if path.startswith(WORK.as_posix() + "/") and preimage["exists"]:
            expected_before[path.removeprefix(WORK.as_posix() + "/")] = preimage["sha256"]
    if before != expected_before:
        raise PipelineError("Ambrose canonical work contains undeclared files or differs from acquired preimages")
    for path, digest in receipt["after"].items():
        if not path.startswith(WORK.as_posix() + "/") or staged.get(path.removeprefix(WORK.as_posix() + "/")) != digest:
            raise PipelineError(f"Ambrose stage after binding differs: {path}")
    if (staged.get(route.ACQUISITION.relative_to(WORK).as_posix()) != before.get(route.ACQUISITION.relative_to(WORK).as_posix())
            or any(path not in before and not path.startswith(EVIDENCE_PREFIX) and path not in {
                (EDITION / "master.tei.xml").relative_to(WORK).as_posix(),
                (EDITION / "acceptance.json").relative_to(WORK).as_posix(),
            } for path in staged)):
        raise PipelineError("Ambrose staged generation exceeds one work acceptance")
    old_work = _read_json(root / WORK / "work.json")
    proposed_work = _read_json(stage / WORK / "work.json")
    expected_work = json.loads(json.dumps(old_work))
    expected_work["creators"] = [{"name": "Ambrose of Milan", "role": "author", "evidence": ["raw/ccel/npnf2/npnf210.xml#i-p15", "raw/ccel/npnf2/npnf210.xml#iv.v"]}]
    expected_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    if proposed_work != expected_work or expected_work["textual_forms"][0]["language"] != "en" or expected_work["textual_forms"][0]["editions"][0]["language"] != "en":
        raise PipelineError("Ambrose staged metadata delta exceeds source-supported category and creator")
    old_state = _read_json(root / WORK / "state.json")
    proposed_state = _read_json(stage / WORK / "state.json")
    expected_state = json.loads(json.dumps(old_state))
    old_target = next(item for item in old_state["targets"] if item["target_id"] == route.IDENTITY["edition_id"])
    new_target = next(item for item in proposed_state["targets"] if item["target_id"] == route.IDENTITY["edition_id"])
    expected_target = next(item for item in expected_state["targets"] if item["target_id"] == route.IDENTITY["edition_id"])
    if (old_target["stage"] != "acquired" or new_target["stage"] != "accepted"
            or new_target["reason"] != PROMOTED_MASTER_REASON
            or new_target["evidence"] != old_target["evidence"] + [(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()]):
        raise PipelineError("Ambrose staged edition state transition differs")
    for key in ("stage", "reason", "updated_at", "evidence"):
        expected_target[key] = new_target[key]
    if proposed_state != expected_state:
        raise PipelineError("Ambrose staged state changed another target")
    _external_dependencies(root, stage_files, fixture=fixture)
    _checked_generation(stage, staged)
    return {"contract": "ocd-npnf210-mysteries-install-preflight-v1", "status": "pass-read-only", "canonical_action": "none", "stage_receipt_sha256": RECEIPT_SHA256, "stage_root": stage.as_posix(), "target_root": root.as_posix(), "before": before, "after": staged, "before_count": len(before), "after_count": len(staged), "master_sha256": receipt["after"][(EDITION / "master.tei.xml").as_posix()], "acceptance_sha256": receipt["after"][(EDITION / "acceptance.json").as_posix()], "projection_rows": 1}


def _copy_generation(source: Path, destination: Path, expected: dict[str, str]) -> None:
    if _io_path(destination).exists():
        raise PipelineError("Ambrose incoming generation already exists")
    _io_path(destination).mkdir(parents=True)
    for relative, digest in expected.items():
        original = _io_path(source / relative)
        target = _io_path(destination / relative)
        if not original.is_file() or _sha(original) != digest:
            raise PipelineError(f"Ambrose staged file changed during copy: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    if _files(destination) != expected:
        raise PipelineError("Ambrose copied generation differs")


def install(*, root_override: Path | None = None, fail_at: Callable[[str], None] | None = None) -> dict[str, object]:
    """Swap only the pinned work folder, with a durable journal and checked rollback."""
    check = preflight(root_override=root_override)
    root, stage = Path(check["target_root"]), Path(check["stage_root"])
    target = root / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        check = preflight(root_override=root_override)
        before, after = check["before"], check["after"]
        if _files(target) != before or _files(stage / WORK) != after:
            raise PipelineError("Ambrose generation changed after preflight")
        operation = root / "library/.sidecar-operations" / ("npnf210-mysteries-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ("incoming", "previous", "failed-new"))
        journal_path = operation / "operation.json"
        journal: dict[str, object] = {"contract": CONTRACT, "work_id": route.WORK_ID, "phase": "created", "stage": stage.as_posix(), "receipt_sha256": RECEIPT_SHA256, "before": before, "after": after, "updated_at": _now()}
        _write_json_durable(journal_path, journal)
        moved = live = False
        try:
            _copy_generation(stage / WORK, incoming, after)
            if _files(target) != before:
                raise PipelineError("Ambrose acquired generation changed during copy")
            journal.update(phase="prepared", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-copy")
            refreshed = preflight(root_override=root_override)
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
            _checked_generation(root, after)
            if fail_at:
                fail_at("after-postcheck")
            _external_dependencies(root, _files(stage), fixture=root_override is not None)
            journal.update(phase="complete", updated_at=_now())
            _write_json_durable(journal_path, journal)
            return {"status": "installed-and-validated", "operation": operation.as_posix(), "before_count": len(before), "after_count": len(after), "master_sha256": check["master_sha256"], "projection_rows": 1}
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="guardedly install the exact pinned work generation")
    args = parser.parse_args()
    result = install() if args.apply else preflight()
    if not args.apply:
        result = {key: value for key, value in result.items() if key not in {"before", "after"}}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
