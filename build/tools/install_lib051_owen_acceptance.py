"""Preflight or guarded-install one exact LIB-051 electronic-witness stage.

The default command is read-only. ``--apply`` swaps only the named work folder
after rechecking its exact receipt and keeps a durable rollback generation.
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

from lxml import etree

from build.tools.stage_lib051_owen_acceptance import (
    CODE_PATHS, LIBRARY, ROOT, _work_row, _source_features, verify_original_source,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable

FIXTURE_MARKER = ".ocd-lib051-owen-install-fixture"
OPERATION_CONTRACT = "ocd-lib051-owen-work-swap-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _paths(work_id: str) -> tuple[Path, Path, Path, Path]:
    row = _work_row(work_id)
    work = Path("library/works") / work_id
    edition = work / "forms" / row["form_id"] / "editions" / row["edition_id"]
    acquisition = edition / "acquisitions" / (row["acquisition_id"] + ".json")
    source = Path(row["source"]["path"])
    return work, edition, acquisition, source


def _external_evidence(root: Path, stage: Path, receipt_sha256: str, work: Path, *, fixture: bool) -> None:
    if _sha(stage / "stage-receipt.json") != receipt_sha256:
        raise PipelineError("LIB-051 stage receipt changed")
    prefix = work.as_posix() + "/"
    for relative, expected in _files(stage).items():
        if relative == "stage-receipt.json" or relative.startswith(prefix):
            continue
        current = root / relative if fixture or not relative.startswith(("raw/", "reports/", "exports/")) else resolve_repo_path(root, relative)
        if not _io_path(current).is_file() or _sha(current) != expected or _sha(stage / relative) != expected:
            raise PipelineError(f"LIB-051 external dependency changed: {relative}")


def preflight(work_id: str, stage: Path, receipt_sha256: str, *, root_override: Path | None = None) -> dict[str, object]:
    row = _work_row(work_id)
    work, edition, acquisition, source = _paths(work_id)
    stage = stage.resolve(strict=True)
    root = root_override.resolve(strict=True) if root_override is not None else ROOT.resolve(strict=True)
    fixture = root_override is not None
    if fixture and not (root / FIXTURE_MARKER).is_file():
        raise PipelineError("LIB-051 root override requires an explicit fixture marker")
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("LIB-051 stage and target roots overlap")
    if (stage.parent != LIBRARY.resolve(strict=True) or not stage.name.startswith("l51-")
            or len(receipt_sha256) != 64 or any(character not in "0123456789abcdef" for character in receipt_sha256)):
        raise PipelineError("LIB-051 stage path or receipt pin is outside the declared route")
    if _sha(stage / "stage-receipt.json") != receipt_sha256:
        raise PipelineError("LIB-051 stage receipt differs from caller pin")
    receipt = _read(stage / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-lib051-owen-electronic-stage-v1"
            or receipt.get("status") != "staged-only" or receipt.get("work_id") != work_id
            or Path(str(receipt.get("stage_root"))).resolve() != stage
            or receipt.get("projection_category") != "prose"
            or receipt.get("projection_rows") != 1
            or receipt.get("projection_independent_verifier_errors") != []
            or receipt.get("source_sha256") != row["source"]["sha256"]):
        raise PipelineError("LIB-051 stage receipt identity or projection differs")
    current_code = {path: _sha(ROOT / path) for path in CODE_PATHS}
    if receipt.get("code_sha256") != current_code:
        raise PipelineError("LIB-051 stage code pins differ from current projector or installer")
    before = _files(root / work)
    after = _files(stage / work)
    acquisition_relative = acquisition.relative_to(work).as_posix()
    if (set(before) != {"work.json", "state.json", acquisition_relative}
            or before[acquisition_relative] != after.get(acquisition_relative)):
        raise PipelineError("canonical work is not the declared three-file acquired baseline")
    expected_new = {"work.json", "state.json", (edition / "master.tei.xml").relative_to(work).as_posix(),
                    (edition / "acceptance.json").relative_to(work).as_posix()}
    evidence_prefix = f"integration/lib051-{work_id}-electronic-v1/"
    for relative in set(before) | set(after):
        if before.get(relative) == after.get(relative) or relative in expected_new:
            continue
        if relative.startswith(evidence_prefix) and relative not in before:
            continue
        raise PipelineError(f"staged work change exceeds guarded generation: {relative}")
    current_work = _read(root / work / "work.json")
    staged_work = _read(stage / work / "work.json")
    source_tree = etree.fromstring((root / source).read_bytes(), etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True))
    source_author = source_tree.findtext(".//DC.Creator[@sub='Author']")
    if "Owen" not in (source_author or ""):
        raise PipelineError("retained Owen header no longer supports proposed creator")
    creator = "John Owen"
    expected_work = json.loads(json.dumps(current_work))
    if current_work.get("creators") or current_work["textual_forms"][0]["editions"][0].get("category") is not None:
        raise PipelineError("canonical work creator or category already changed")
    expected_work["creators"] = [{"name": creator, "role": "author", "evidence": [source.as_posix()]}]
    expected_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    if staged_work != expected_work:
        raise PipelineError("staged work metadata differs beyond source-backed creator and category")
    current_state = _read(root / work / "state.json")
    staged_state = _read(stage / work / "state.json")
    before_targets = [item for item in current_state["targets"] if item["target_id"] == row["edition_id"]]
    after_targets = [item for item in staged_state["targets"] if item["target_id"] == row["edition_id"]]
    if len(before_targets) != 1 or len(after_targets) != 1:
        raise PipelineError("one edition state target required")
    before_target, after_target = before_targets[0], after_targets[0]
    if (before_target["stage"] != "acquired" or after_target["stage"] != "accepted"
            or after_target["reason"] != PROMOTED_MASTER_REASON
            or after_target["evidence"] != before_target["evidence"] + [
                (edition / "master.tei.xml").as_posix(), (edition / "acceptance.json").as_posix()]):
        raise PipelineError("edition state transition differs")
    expected_state = json.loads(json.dumps(current_state))
    expected_target = next(item for item in expected_state["targets"] if item["target_id"] == row["edition_id"])
    for key in ("stage", "reason", "updated_at", "evidence"):
        expected_target[key] = after_target[key]
    if staged_state != expected_state:
        raise PipelineError("staged state differs beyond one-edition acceptance")
    _external_evidence(root, stage, receipt_sha256, work, fixture=fixture)
    acceptance = stage / edition / "acceptance.json"
    validated = validate_acceptance(acceptance, root=stage)
    accounting = _read(stage / validated["source"]["accounting"]["path"])
    original_ref = accounting["original_candidate"]
    original_path = stage / original_ref["path"]
    if (_sha(original_path) != original_ref["sha256"]
            or len(_io_path(original_path).read_bytes()) != original_ref["bytes"]):
        raise PipelineError("LIB-051 staged readable candidate differs")
    source_nodes = verify_original_source(
        work_id, _io_path(stage / source).read_bytes(), _io_path(original_path).read_bytes(),
        member_id=source.stem,
    )
    if source_nodes != _read(stage / work / evidence_prefix / "inputs/child-receipt.json")["source_nodes"]:
        raise PipelineError("LIB-051 staged direct source oracle node count differs")
    source_body = source_tree.find("ThML.body")
    original_tree = etree.fromstring(_io_path(original_path).read_bytes())
    if (source_body is None or _source_features(work_id, source_body, original_tree)
            != accounting.get("source_features")
            or hashlib.sha256(etree.tostring(source_body, method="c14n")).hexdigest()
               != accounting.get("source_body_c14n_sha256")
            or hashlib.sha256(etree.tostring(original_tree.find(
                "{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body"),
                method="c14n")).hexdigest() != accounting.get("readable_body_c14n_sha256")):
        raise PipelineError("LIB-051 staged feature or body boundary differs from retained source")
    validated_state = validate_state(stage / work / "state.json", root=stage)
    accepted_targets = [item for item in validated_state["targets"] if item["target_id"] == row["edition_id"]]
    if (_sha(acceptance) != receipt["acceptance_sha256"]
            or _sha(stage / edition / "master.tei.xml") != receipt["master_sha256"]
            or validated["promotion"]["status"] != "promoted"
            or validated["identity"]["work_id"] != work_id
            or len(accepted_targets) != 1 or accepted_targets[0]["stage"] != "accepted"):
        raise PipelineError("staged accepted master, record, or public state differs")
    projection = project_accepted_prose(stage, acceptance_path=acceptance)
    errors = verify_accepted_prose(stage, acceptance_path=acceptance, rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 1 or projection["receipt"]["unsupported"]:
        raise PipelineError(f"staged native prose projection differs: {errors[:3]}")
    return {"contract": "ocd-lib051-owen-install-preflight-v1", "status": "pass-read-only",
            "canonical_action": "none", "work_id": work_id, "stage_receipt_sha256": receipt_sha256,
            "stage_root": stage.as_posix(), "target_root": root.as_posix(),
            "current_work_files": len(before), "staged_work_files": len(after), "before": before, "after": after,
            "acceptance_sha256": receipt["acceptance_sha256"], "master_sha256": receipt["master_sha256"],
            "projection_rows": len(projection["rows"]), "projection_independent_verifier_errors": errors,
            "rights_clearance": receipt["rights_clearance"], "publication": receipt["publication"]}


def _copy_generation(source: Path, destination: Path, expected: dict[str, str]) -> None:
    if _io_path(destination).exists():
        raise PipelineError("LIB-051 incoming generation already exists")
    _io_path(destination).mkdir(parents=True)
    for relative, digest in expected.items():
        origin = _io_path(source / relative)
        target = _io_path(destination / relative)
        if not origin.is_file() or _sha(origin) != digest:
            raise PipelineError(f"staged file changed during copy: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    if _files(destination) != expected:
        raise PipelineError("copied LIB-051 work generation differs")


@cached_edition_lookups()
def _checked_generation(root: Path, work: Path, edition: Path, after: dict[str, str]) -> None:
    if _files(root / work) != after:
        raise PipelineError("installed LIB-051 generation differs")
    acceptance = _io_path(root / edition / "acceptance.json")
    validated = validate_acceptance(acceptance, root=_io_path(root))
    if validated["promotion"]["status"] != "promoted" or validated["identity"]["work_id"] != work.name:
        raise PipelineError("public acceptance differs after install")
    state = validate_state(_io_path(root / work / "state.json"), root=_io_path(root))
    targets = [item for item in state["targets"] if item["target_id"] == validated["identity"]["edition_id"]]
    if len(targets) != 1 or targets[0]["stage"] != "accepted":
        raise PipelineError("edition state differs after install")
    projection = project_accepted_prose(root, acceptance_path=acceptance)
    errors = verify_accepted_prose(root, acceptance_path=acceptance, rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 1 or projection["receipt"]["unsupported"]:
        raise PipelineError(f"actual-master native prose projection differs: {errors[:3]}")


def install(work_id: str, stage: Path, receipt_sha256: str, *, root_override: Path | None = None,
            fail_at: Callable[[str], None] | None = None) -> dict[str, object]:
    work, edition, _, _ = _paths(work_id)
    check = preflight(work_id, stage, receipt_sha256, root_override=root_override)
    stage = Path(check["stage_root"])
    root = Path(check["target_root"])
    target = root / work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        check = preflight(work_id, stage, receipt_sha256, root_override=root_override)
        before, after = check["before"], check["after"]
        if _files(target) != before or _files(stage / work) != after:
            raise PipelineError("LIB-051 work generation changed after preflight")
        operation = root / "library/.sidecar-operations" / ("lib051-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ("incoming", "previous", "failed-new"))
        journal_path = operation / "operation.json"
        journal: dict[str, object] = {"contract": OPERATION_CONTRACT, "work_id": work_id,
            "phase": "created", "stage": stage.as_posix(), "receipt_sha256": receipt_sha256,
            "before": before, "after": after, "updated_at": _now()}
        _write_json_durable(journal_path, journal)
        moved = live = False
        try:
            _copy_generation(stage / work, incoming, after)
            if _files(target) != before:
                raise PipelineError("canonical generation changed during copy")
            journal.update(phase="prepared", updated_at=_now())
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-copy")
            refreshed = preflight(work_id, stage, receipt_sha256, root_override=root_override)
            if refreshed["before"] != before or refreshed["after"] != after:
                raise PipelineError("staged or canonical generation changed before swap")
            _external_evidence(root, stage, receipt_sha256, work, fixture=root_override is not None)
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
            _checked_generation(root, work, edition, after)
            if fail_at:
                fail_at("after-postcheck")
            _external_evidence(root, stage, receipt_sha256, work, fixture=root_override is not None)
            journal.update(phase="complete", updated_at=_now())
            _write_json_durable(journal_path, journal)
            return {"status": "installed-and-validated", "work_id": work_id,
                    "operation": operation.as_posix(), "before_count": len(before),
                    "after_count": len(after), "master_sha256": check["master_sha256"],
                    "projection_rows": 1}
        except BaseException:
            try:
                if live:
                    if _files(target) != after:
                        raise PipelineError("live generation differs during rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != before:
                        raise PipelineError("prior generation differs during rollback")
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != before:
                        raise PipelineError("rollback restored wrong bytes")
                journal.update(phase="rolled-back" if moved else "failed-before-swap", updated_at=_now())
                _write_json_durable(journal_path, journal)
            except BaseException as rollback_error:
                journal.update(phase="recovery-required", rollback_error=str(rollback_error), updated_at=_now())
                _write_json_durable(journal_path, journal)
                raise PipelineError(f"LIB-051 rollback requires recovery: {operation}") from rollback_error
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = (install(args.work_id, args.stage, args.receipt_sha256) if args.apply
              else preflight(args.work_id, args.stage, args.receipt_sha256))
    print(json.dumps({key: value for key, value in result.items() if key not in {"before", "after"}}, sort_keys=True))


if __name__ == "__main__":
    main()
