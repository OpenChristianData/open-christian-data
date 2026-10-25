"""Read-only by default; install the pinned Satyrus title v3 generation."""

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

from build.tools.stage_npnf210_satyrus_v3_acceptance import CONFIG
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
from build.tools.ambrose_review import install as _shared_install


ROOT = Path("\\\\?\\" + str(Path(__file__).resolve().parents[2]))
LIBRARY = Path("\\\\?\\D:\\Library\\Open Christian Data")
FIXTURE_MARKER = ".ocd-npnf210-satyrus-v3-install-fixture"
CONTRACT = "ocd-npnf210-satyrus-title-v3-work-swap-v1"
PINS = {
    "ambrose-of-milan-on-satyrus": {
        "receipt": "7e7d3ca50ab81ffe71bb1f1a8e0b7825a9c4c865d37f87003f8e68228105b7f5",
        "all": "0cc374009f37b1d260da859330dec9cb7fa028e02b14aa34711fd6317fdefa52",
        "work": "07ad2a5ff6ffe96e3648e7cb5d970b8f77da969735662359d798ac48cdc5c08c",
    },
}


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


def _external_dependencies(root: Path, stage_files: dict[str, str], *, work: Path, fixture: bool) -> None:
    prefix = work.as_posix() + "/"
    for relative, digest in stage_files.items():
        if relative == "stage-receipt.json" or relative.startswith(prefix):
            continue
        target = root / relative if fixture or not relative.startswith(("raw/", "reports/", "exports/")) else resolve_repo_path(root, relative)
        if not _io_path(target).is_file() or _sha(target) != digest:
            raise PipelineError(f"Ambrose outside dependency differs: {relative}")


def _checked_generation(root: Path, *, work: Path, edition: Path, identity: dict[str, str], after: dict[str, str]) -> None:
    if _files(root / work) != after:
        raise PipelineError("Ambrose installed work generation differs")
    acceptance = root / edition / "acceptance.json"
    record = validate_acceptance(_io_path(acceptance), root=_io_path(root))
    if record["identity"] != identity or record["promotion"]["status"] != "promoted":
        raise PipelineError("Ambrose public acceptance identity differs")
    state = validate_state(_io_path(root / work / "state.json"), root=_io_path(root))
    target = next((item for item in state["targets"] if item["target_id"] == identity["edition_id"]), None)
    if target is None or target["stage"] != "accepted":
        raise PipelineError("Ambrose accepted edition state differs")
    projection = project_accepted_prose(root, acceptance_path=_io_path(acceptance))
    errors = verify_accepted_prose(root, acceptance_path=_io_path(acceptance), rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 1 or projection["receipt"]["unsupported"]:
        raise PipelineError(f"Ambrose actual-master prose checker failed: {errors[:3]}")


def preflight(work_id: str, *, root_override: Path | None = None) -> dict[str, object]:
    """Check stage pins, every canonical preimage, and public stage postchecks."""
    if work_id not in PINS:
        raise PipelineError(f"work is outside pinned Satyrus v3 install: {work_id}")
    pin = PINS[work_id]
    stage = (LIBRARY / CONFIG[work_id]["stage_name"]).resolve(strict=True)
    root = root_override.resolve(strict=True) if root_override is not None else ROOT.resolve(strict=True)
    fixture = root_override is not None
    if fixture and not _io_path(root / FIXTURE_MARKER).is_file():
        raise PipelineError("root override requires exact Ambrose fixture marker")
    if root == stage or root in stage.parents or stage in root.parents or stage.parent != LIBRARY.resolve(strict=True):
        raise PipelineError("stage and target roots overlap or stage left durable library")
    if _sha(stage / "stage-receipt.json") != pin["receipt"]:
        raise PipelineError("Ambrose stage receipt differs from exact pin")
    receipt = _read_json(stage / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-npnf210-satyrus-title-v3-acceptance-stage-v1"
            or receipt.get("status") != "staged-only" or receipt.get("canonical_install") is not False
            or receipt.get("work_id") != work_id or receipt.get("source_root_id") != CONFIG[work_id]["root_id"]
            or Path(str(receipt.get("stage"))).resolve() != stage
            or receipt.get("public_validate_acceptance") != "pass" or receipt.get("public_validate_state") != "pass"
            or receipt.get("projection_rows") != 1 or receipt.get("projection_unsupported") != []
            or receipt.get("independent_projection_errors") != []):
        raise PipelineError("Ambrose stage receipt contract differs")
    work = Path("library/works") / work_id
    stage_files, staged = _files(stage), _files(stage / work)
    if _files_sha(stage_files) != pin["all"] or _files_sha(staged) != pin["work"]:
        raise PipelineError("Ambrose complete staged file map differs")
    before = _files(root / work)
    expected_before = {}
    for path, preimage in receipt["preimages"].items():
        target = root / path
        if _io_path(target).is_file() != preimage["exists"]:
            raise PipelineError(f"Ambrose canonical existence preimage differs: {path}")
        if preimage["exists"] and _sha(target) != preimage["sha256"]:
            raise PipelineError(f"Ambrose canonical byte preimage differs: {path}")
        if path.startswith(work.as_posix() + "/") and preimage["exists"]:
            expected_before[path.removeprefix(work.as_posix() + "/")] = preimage["sha256"]
    if before != expected_before:
        raise PipelineError("Ambrose canonical work contains undeclared or changed files")
    for path, digest in receipt["after"].items():
        if not path.startswith(work.as_posix() + "/") or staged.get(path.removeprefix(work.as_posix() + "/")) != digest:
            raise PipelineError(f"Ambrose staged after binding differs: {path}")
    old_work = _read_json(root / work / "work.json")
    proposed_work = _read_json(stage / work / "work.json")
    form = old_work["textual_forms"][0]
    edition_record = form["editions"][0]
    identity = {"work_id": work_id, "textual_form_id": form["textual_form_id"], "edition_id": edition_record["edition_id"], "acquisition_id": edition_record["acquisition_ids"][0]}
    edition = work / "forms" / identity["textual_form_id"] / "editions" / identity["edition_id"]
    acquisition_rel = (edition / "acquisitions" / f"{identity['acquisition_id']}.json").relative_to(work).as_posix()
    if (staged.get(acquisition_rel) != before.get(acquisition_rel)
            or any(path not in before and not path.startswith("integration/npnf210-satyrus-title-v3/") and path not in {
                (edition / "master.tei.xml").relative_to(work).as_posix(),
                (edition / "acceptance.json").relative_to(work).as_posix(),
            } for path in staged)):
        raise PipelineError("Ambrose staged generation exceeds one-work acceptance")
    expected_work = json.loads(json.dumps(old_work))
    source = "raw/ccel/npnf2/npnf210.xml"
    expected_work["creators"] = [{"name": "Ambrose of Milan", "role": "author", "evidence": [f"{source}#i-p15", f"{source}#{CONFIG[work_id]['root_id']}"]}]
    expected_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    if proposed_work != expected_work or form["language"] != "en" or edition_record["language"] != "en":
        raise PipelineError("Ambrose metadata delta exceeds source-backed creator/category")
    old_state = _read_json(root / work / "state.json")
    proposed_state = _read_json(stage / work / "state.json")
    expected_state = json.loads(json.dumps(old_state))
    old_target = next(item for item in old_state["targets"] if item["target_id"] == identity["edition_id"])
    new_target = next(item for item in proposed_state["targets"] if item["target_id"] == identity["edition_id"])
    expected_target = next(item for item in expected_state["targets"] if item["target_id"] == identity["edition_id"])
    if (old_target["stage"] != "acquired" or new_target["stage"] != "accepted"
            or new_target["reason"] != PROMOTED_MASTER_REASON
            or new_target["evidence"] != old_target["evidence"] + [(edition / "master.tei.xml").as_posix(), (edition / "acceptance.json").as_posix()]):
        raise PipelineError("Ambrose staged edition state transition differs")
    for key in ("stage", "reason", "updated_at", "evidence"):
        expected_target[key] = new_target[key]
    if proposed_state != expected_state:
        raise PipelineError("Ambrose staged state changed another target")
    _external_dependencies(root, stage_files, work=work, fixture=fixture)
    _checked_generation(stage, work=work, edition=edition, identity=identity, after=staged)
    return {"status": "pass-read-only", "canonical_action": "none", "work_id": work_id, "stage": stage.as_posix(), "target_root": root.as_posix(), "receipt_sha256": pin["receipt"], "before": before, "after": staged, "before_count": len(before), "after_count": len(staged), "projection_rows": 1}


def _copy_generation(source: Path, destination: Path, expected: dict[str, str]) -> None:
    if _io_path(destination).exists():
        raise PipelineError("Ambrose incoming generation already exists")
    _io_path(destination).mkdir(parents=True)
    for relative, digest in expected.items():
        original, target = _io_path(source / relative), _io_path(destination / relative)
        if not original.is_file() or _sha(original) != digest:
            raise PipelineError(f"Ambrose staged file changed during copy: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    if _files(destination) != expected:
        raise PipelineError("Ambrose copied generation differs")


def install(work_id: str, *, root_override: Path | None=None, fail_at: Callable[[str], None] | None=None) -> dict[str, object]:
    return _shared_install(work_id, root_override=root_override, fail_at=fail_at,
        CONTRACT=CONTRACT, PINS=PINS, _checked_generation=_checked_generation,
        _copy_generation=_copy_generation, _external_dependencies=_external_dependencies,
        _now=_now, _read_json=_read_json, preflight=preflight)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", required=True, choices=sorted(PINS))
    parser.add_argument("--apply", action="store_true", help="guardedly install this exact pinned work generation")
    args = parser.parse_args()
    result = install(args.work_id) if args.apply else preflight(args.work_id)
    if not args.apply:
        result = {key: value for key, value in result.items() if key not in {"before", "after"}}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
