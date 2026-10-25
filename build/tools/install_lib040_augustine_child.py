"""Read-only preflight or guarded install for six source-bound LIB-040 children.

Each work has an exact pinned stage receipt. Only a child with an independently
checked category projection can pass the apply gate; all other routes remain
read-only holds. A successful swap retains the previous complete work folder.
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
from ocd_kernel.projection.categories.commentary import project_accepted_commentary, verify_accepted_commentary
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.projection.categories.sermons import project_accepted_sermons, verify_accepted_sermons
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _write_json_durable

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_MARKER = ".ocd-lib040-child-install-fixture"
OPERATION_CONTRACT = "ocd-lib040-augustine-child-work-swap-v1"
RECEIPT_SHA256 = {
    "augustine-soliloquies": "13588c83e98bb0eb42712a61122528bf606a51b39483e6f00b5eecf5bdba68aa",
    "augustine-sermon-on-the-mount": "e44a021d6d577b08c9bed091e6177742faf30b15b1762bf7f08c60df665fb6de",
    "augustine-tractates-on-john": "f5c91062518ad6bd03bcbace84768d14de625f01973fe64d70e488f1fe20e516",
    "augustine-letters-part-1": "9244cf46d51e5311bb17a9bb4b4ae3a1327cb57b89592f787d25dfb85d4c6a08",
    "augustine-sermons-selected-lessons": "bcf66a2003f162c13f0ab5e0138a31384e0f5486ce909f855ab09de44403f16a",
    "augustine-homilies-on-first-john": "fb3b930d35f4220f8013b75c8ccb753bf3054070f1b973ecc7e8c5c56de36d82",
}
SELECTED_WORKS = {"augustine-letters-part-1", "augustine-sermons-selected-lessons", "augustine-homilies-on-first-john"}


def _sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _receipt(work_id: str) -> dict:
    if work_id not in RECEIPT_SHA256:
        raise PipelineError(f"LIB-040 child installer does not own {work_id}")
    suffix = "selected-acceptance-stage" if work_id in SELECTED_WORKS else "acceptance-stage"
    path = ROOT / "plans/2026-09-22-source-preflight" / f"lib040-{work_id}-{suffix}-20260926.json"
    if _sha(path) != RECEIPT_SHA256[work_id]:
        raise PipelineError("LIB-040 child stage receipt differs from installer pin")
    value = json.loads(io_path(path).read_bytes())
    if value.get("contract") != "ocd-lib040-augustine-child-stage-v1" or value.get("status") != "staged-only" or value.get("work_id") != work_id or value.get("canonical_apply") != "not performed":
        raise PipelineError("LIB-040 child receipt identity or status differs")
    return value


def _project_checked(root: Path, acceptance: Path, receipt: dict) -> None:
    projection = receipt["projection"]
    if projection["status"] != "pass":
        raise PipelineError("LIB-040 child projection remains a documented hold")
    category = receipt["category"]
    if category == "sermons" and receipt["work_id"] in SELECTED_WORKS:
        project, verify = project_accepted_sermons, verify_accepted_sermons
    elif category == "prose":
        project, verify = project_accepted_prose, verify_accepted_prose
    elif category == "commentary":
        project, verify = project_accepted_commentary, verify_accepted_commentary
    else:
        raise PipelineError("LIB-040 child has no supported accepted category projection")
    result = project(root, acceptance_path=acceptance)
    errors = verify(root, acceptance_path=acceptance, rows=result["rows"], receipt=result["receipt"])
    if errors or len(result["rows"]) != projection["row_count"] or result["receipt"].get("unsupported"):
        raise PipelineError(f"LIB-040 child actual-master projection differs: {errors[:3]}")
    if [hashlib.sha256(row["text"].encode()).hexdigest() for row in result["rows"]] != projection["row_text_sha256"]:
        raise PipelineError("LIB-040 child row text hashes differ")
    receipt_bytes = json.dumps(result["receipt"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    if hashlib.sha256(receipt_bytes).hexdigest() != projection["receipt_sha256"]:
        raise PipelineError("LIB-040 child projection receipt differs")
    if result["receipt"].get("source_division_binding") != projection["source_division_binding"]:
        raise PipelineError("LIB-040 child source-division binding differs")


def _accepted_generation(root: Path, work: Path, receipt: dict, expected: dict[str, str], *, require_projection: bool) -> None:
    if _files(root / work) != expected:
        raise PipelineError("LIB-040 child accepted generation differs")
    work_record = json.loads(io_path(root / work / "work.json").read_bytes())
    form = work_record["textual_forms"][0]
    edition = form["editions"][0]
    edition_root = root / work / "forms" / form["textual_form_id"] / "editions" / edition["edition_id"]
    acceptance = io_path(edition_root / "acceptance.json")
    master = io_path(edition_root / "master.tei.xml")
    if _sha(acceptance) != receipt["acceptance_sha256"] or _sha(master) != receipt["master_sha256"]:
        raise PipelineError("LIB-040 child accepted master/record differs")
    accepted = validate_acceptance(io_path(acceptance), root=io_path(root))
    if accepted["promotion"]["status"] != "promoted" or accepted["identity"]["work_id"] != receipt["work_id"]:
        raise PipelineError("LIB-040 child public acceptance differs")
    state = validate_state(io_path(root / work / "state.json"), root=io_path(root))
    targets = [item for item in state["targets"] if item["target_id"] == accepted["identity"]["edition_id"]]
    if len(targets) != 1 or targets[0]["stage"] != "accepted":
        raise PipelineError("LIB-040 child edition state differs")
    if require_projection:
        _project_checked(root, edition_root / "acceptance.json", receipt)


def _external_evidence(root: Path, stage: Path, receipt: dict, *, fixture: bool) -> None:
    for relative, expected in receipt["external"].items():
        path = root / relative if fixture or not relative.startswith(("raw/", "reports/", "exports/")) else resolve_repo_path(root, relative)
        if not io_path(path).is_file() or _sha(path) != expected or _sha(stage / relative) != expected:
            raise PipelineError(f"LIB-040 child external source or evidence differs: {relative}")


def preflight(work_id: str, *, root_override: Path | None = None) -> dict:
    """Read exact source, work, state, accepted TEI, and projection evidence."""
    receipt = _receipt(work_id)
    work = Path("library/works") / work_id
    stage = Path(receipt["stage_root"]).resolve(strict=True)
    root = root_override.resolve(strict=True) if root_override is not None else ROOT.resolve(strict=True)
    fixture = root_override is not None
    if fixture and not io_path(root / FIXTURE_MARKER).is_file():
        raise PipelineError("LIB-040 child root override requires a marked fixture")
    if root == stage or root in stage.parents or stage in root.parents or stage.parent.resolve() != Path("C:/Scratch").resolve():
        raise PipelineError("LIB-040 child stage/target route differs")
    if len(receipt["before"]) != 4 or len(receipt["staged_work"]) != 16 or len(receipt["after_preserving_handoff"]) != 17 or len(receipt["external"]) != 5:
        raise PipelineError("LIB-040 child complete-generation counts differ")
    if (_files(root / work) != receipt["before"] or _files(stage / work) != receipt["staged_work"]
            or _files(stage) != receipt["staged_all"]):
        raise PipelineError("LIB-040 child canonical or staged generation differs")
    handoff = receipt["work_local_handoff"]
    relative_handoff = Path(handoff).relative_to(work).as_posix()
    if (_sha(root / handoff) != receipt["work_local_handoff_sha256"]
            or receipt["before"].get(relative_handoff) != receipt["work_local_handoff_sha256"]
            or receipt["after_preserving_handoff"] != {**receipt["staged_work"], relative_handoff: receipt["work_local_handoff_sha256"]}):
        raise PipelineError("LIB-040 child preserved work-local handoff differs")
    old_work = json.loads(io_path(root / work / "work.json").read_bytes())
    new_work = json.loads(io_path(stage / work / "work.json").read_bytes())
    expected_work = json.loads(json.dumps(old_work))
    edition = expected_work["textual_forms"][0]["editions"][0]
    if edition.get("category") is not None or edition.get("language") != "en":
        raise PipelineError("LIB-040 child canonical category/language baseline differs")
    edition["category"] = receipt["category"]
    if new_work != expected_work:
        raise PipelineError("LIB-040 child work metadata differs beyond category rebind")
    old_state = json.loads(io_path(root / work / "state.json").read_bytes())
    new_state = json.loads(io_path(stage / work / "state.json").read_bytes())
    expected_state = json.loads(json.dumps(old_state))
    target = next(item for item in expected_state["targets"] if item["target_id"] == edition["edition_id"])
    accepted_target = next(item for item in new_state["targets"] if item["target_id"] == edition["edition_id"])
    if target["stage"] != "acquired" or accepted_target["stage"] != "accepted" or accepted_target["reason"] != PROMOTED_MASTER_REASON:
        raise PipelineError("LIB-040 child state transition differs")
    if accepted_target["evidence"] != target["evidence"] + [(work / "forms" / expected_work["textual_forms"][0]["textual_form_id"] / "editions" / edition["edition_id"] / name).as_posix() for name in ("master.tei.xml", "acceptance.json")]:
        raise PipelineError("LIB-040 child state evidence differs")
    for key in ("stage", "reason", "evidence", "updated_at"):
        target[key] = accepted_target[key]
    if expected_state != new_state:
        raise PipelineError("LIB-040 child staged state differs beyond one edition")
    acquisition = next(key for key in receipt["before"] if key.endswith(".json") and "/acquisitions/" in key.replace("\\", "/"))
    if receipt["before"][acquisition] != receipt["staged_work"].get(acquisition):
        raise PipelineError("LIB-040 child acquisition changed")
    for relative, digest in receipt["code_sha256"].items():
        if _sha(ROOT / relative) != digest:
            raise PipelineError(f"LIB-040 child stage/projection implementation differs: {relative}")
    _external_evidence(root, stage, receipt, fixture=fixture)
    _accepted_generation(stage, work, receipt, receipt["staged_work"], require_projection=receipt["projection"]["status"] == "pass")
    return {"contract": "ocd-lib040-augustine-child-install-preflight-v1", "status": "pass-read-only" if receipt["projection"]["status"] == "pass" else "held-read-only", "canonical_action": "none", "work_id": work_id, "root": root.as_posix(), "stage": stage.as_posix(), "receipt_sha256": RECEIPT_SHA256[work_id], "before": receipt["before"], "after": receipt["after_preserving_handoff"], "external_count": len(receipt["external"]), "projection": receipt["projection"], "master_sha256": receipt["master_sha256"], "acceptance_sha256": receipt["acceptance_sha256"], "preserved_handoff": handoff}


def _copy_generation(stage_work: Path, current_work: Path, destination: Path, expected: dict[str, str], preserved_relative: str) -> None:
    if io_path(destination).exists():
        raise PipelineError("LIB-040 child incoming generation already exists")
    io_path(destination).mkdir(parents=True)
    for relative, digest in expected.items():
        origin = io_path(current_work / relative) if relative == preserved_relative else io_path(stage_work / relative)
        target = io_path(destination / relative)
        if not origin.is_file() or _sha(origin) != digest:
            raise PipelineError(f"LIB-040 child incoming source differs: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    if _files(destination) != expected:
        raise PipelineError("LIB-040 child copied generation differs")


def install(work_id: str, *, root_override: Path | None = None, fail_at: Callable[[str], None] | None = None) -> dict:
    checked = preflight(work_id, root_override=root_override)
    if checked["status"] != "pass-read-only":
        raise PipelineError("LIB-040 child has no independently checked category projection")
    root = Path(checked["root"])
    stage = Path(checked["stage"])
    work = Path("library/works") / work_id
    target = root / work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        checked = preflight(work_id, root_override=root_override)
        before, after = checked["before"], checked["after"]
        operation = root / "library/.sidecar-operations" / ("lib040-" + work_id.removeprefix("augustine-")[:18] + "-" + uuid.uuid4().hex[:12])
        io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ("incoming", "previous", "failed-new"))
        journal_path = operation / "operation.json"
        journal: dict[str, object] = {"contract": OPERATION_CONTRACT, "work_id": work_id, "phase": "created", "receipt_sha256": RECEIPT_SHA256[work_id], "stage": stage.as_posix(), "before": before, "after": after, "updated_at": _now()}
        _write_json_durable(journal_path, journal)
        moved = live = False
        try:
            preserved = Path(checked["preserved_handoff"]).relative_to(work).as_posix()
            _copy_generation(stage / work, target, incoming, after, preserved)
            if _files(target) != before:
                raise PipelineError("LIB-040 child canonical work changed during copy")
            journal.update(phase="prepared", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-copy")
            refreshed = preflight(work_id, root_override=root_override)
            if refreshed["before"] != before or refreshed["after"] != after:
                raise PipelineError("LIB-040 child generation changed before swap")
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
            receipt = _receipt(work_id)
            _accepted_generation(root, work, receipt, after, require_projection=True)
            if fail_at:
                fail_at("after-postcheck")
            _external_evidence(root, stage, receipt, fixture=root_override is not None)
            journal.update(phase="complete", updated_at=_now())
            _write_json_durable(journal_path, journal)
            return {"status": "installed-and-validated", "work_id": work_id, "operation": operation.as_posix(), "before_count": len(before), "after_count": len(after), "projection_rows": receipt["projection"]["row_count"], "master_sha256": receipt["master_sha256"]}
        except BaseException:
            try:
                if live:
                    if _files(target) != after:
                        raise PipelineError("LIB-040 child live generation differs during rollback")
                    os.replace(io_path(target), io_path(failed_new))
                if moved:
                    if io_path(target).exists() or _files(previous) != before:
                        raise PipelineError("LIB-040 child prior generation differs during rollback")
                    os.replace(io_path(previous), io_path(target))
                    if _files(target) != before:
                        raise PipelineError("LIB-040 child rollback restored wrong bytes")
                journal.update(phase="rolled-back" if moved else "failed-before-swap", updated_at=_now())
                _write_json_durable(journal_path, journal)
            except BaseException as rollback_error:
                journal.update(phase="recovery-required", rollback_error=str(rollback_error), updated_at=_now())
                _write_json_durable(journal_path, journal)
                raise PipelineError(f"LIB-040 child rollback requires recovery: {operation}") from rollback_error
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", choices=sorted(RECEIPT_SHA256), required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.work) if args.apply else {key: value for key, value in preflight(args.work).items() if key not in {"before", "after", "projection"}}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
