"""Guard the two accepted commentary edition category corrections.

Default is a read-only preflight. --apply replaces only the two pinned work.json
files, validates both public acceptance closures, and rolls back on an orderly
failure or interrupt. The accepted masters and state records are never edited.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, load_json
from ocd_kernel.library.identities import load_work
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable

ROOT = Path(__file__).resolve().parents[2]
STAGE = Path("C:/Scratch/Open Christian Data/cat")
MANIFEST = ROOT / "plans/2026-09-22-source-preflight/two-commentary-category-stage-20260926.json"
CONTRACT = "ocd-two-accepted-commentary-categories-v1"
WORK_IDS = ("barnes-nt-notes", "robertson-word-pictures-vol1")
SOURCE_MEMBERS = (
    "raw/sword_modules/Barnes/modules/comments/zcom/barnes/nt.czs",
    "raw/sword_modules/Barnes/modules/comments/zcom/barnes/nt.czv",
    "raw/sword_modules/Barnes/modules/comments/zcom/barnes/nt.czz",
    "raw/ccel/robertson-word-pictures/robertson_at_wp_matt.xml",
    "raw/ccel/robertson-word-pictures/robertson_at_wp_mark.xml",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _work(root: Path, work_id: str) -> Path:
    return root / "library" / "works" / work_id


def _acceptance(work: Path) -> Path:
    paths = list(_io_path(work).glob("forms/*/editions/*/acceptance.json"))
    if len(paths) != 1:
        raise PipelineError(f"expected exactly one accepted edition: {work}")
    return paths[0]


def _category_only(root: Path, stage: Path, work_id: str) -> tuple[dict[str, str], dict[str, str]]:
    canonical = _work(root, work_id)
    proposed = _work(stage, work_id)
    before, after = _files(canonical), _files(proposed)
    if set(before) != set(after) or {p for p in before if before[p] != after[p]} != {"work.json"}:
        raise PipelineError(f"{work_id}: expected only work.json to differ")
    old = load_work(canonical / "work.json")
    new = load_work(proposed / "work.json")
    if old["work_id"] != work_id or len(old["textual_forms"]) != 1 or len(old["textual_forms"][0]["editions"]) != 1:
        raise PipelineError(f"{work_id}: canonical edition shape differs")
    if any("category" in item for item in (old, old["textual_forms"][0], old["textual_forms"][0]["editions"][0])):
        raise PipelineError(f"{work_id}: canonical category is already assigned")
    expected = copy.deepcopy(old)
    expected["textual_forms"][0]["editions"][0]["category"] = "commentary"
    if new != expected:
        raise PipelineError(f"{work_id}: proposed metadata is not an edition-only commentary category")
    validate_acceptance(_io_path(_acceptance(proposed)), root=_io_path(stage))
    return before, after


def prepare(root: Path = ROOT, stage: Path = STAGE, manifest: Path = MANIFEST) -> dict:
    root, stage = root.resolve(strict=True), stage.resolve(strict=True)
    if manifest.exists():
        raise PipelineError(f"category receipt already exists: {manifest}")
    works = {}
    for work_id in WORK_IDS:
        before, after = _category_only(root, stage, work_id)
        works[work_id] = {"before": before, "after": after}
    sources = {}
    for relative in SOURCE_MEMBERS:
        original = resolve_repo_path(root, relative)
        staged = stage / relative
        if _sha(original) != _sha(staged):
            raise PipelineError(f"category fixture retained source differs: {relative}")
        sources[relative] = _sha(original)
    record = {
        "contract": CONTRACT, "status": "staged-only", "prepared_at": _now(),
        "canonical_root": root.as_posix(), "stage_root": stage.as_posix(),
        "works": works, "source_members": sources,
        "scope": "Add edition.category=commentary only to Barnes NT Notes and Robertson Vol I",
        "limits": ["canonical library unchanged", "actual-master projection still rejects source-specific structures",
                   "no human acceptance, rights clearance, or publication decision"],
    }
    _write_json_durable(manifest, record)
    return record


def preflight(manifest: Path = MANIFEST) -> tuple[dict, Path, Path]:
    record = load_json(manifest)
    if record.get("contract") != CONTRACT or record.get("status") != "staged-only":
        raise PipelineError("commentary category receipt contract differs")
    root, stage = Path(record["canonical_root"]).resolve(strict=True), Path(record["stage_root"]).resolve(strict=True)
    if root != ROOT.resolve(strict=True) or root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("commentary category roots differ or overlap")
    if set(record["works"]) != set(WORK_IDS):
        raise PipelineError("commentary category work list differs")
    for work_id in WORK_IDS:
        before, after = _category_only(root, stage, work_id)
        if {"before": before, "after": after} != record["works"][work_id]:
            raise PipelineError(f"{work_id}: category receipt is stale")
    for relative, digest in record["source_members"].items():
        if relative not in SOURCE_MEMBERS or _sha(resolve_repo_path(root, relative)) != digest or _sha(stage / relative) != digest:
            raise PipelineError(f"category retained source changed: {relative}")
    if set(record["source_members"]) != set(SOURCE_MEMBERS):
        raise PipelineError("commentary retained member list differs")
    return record, root, stage


def apply(manifest: Path = MANIFEST) -> dict:
    record, root, stage = preflight(manifest)
    with ExitStack() as locks:
        for work_id in WORK_IDS:
            locks.enter_context(acquire_jsonl_lock(_work(root, work_id), acquire_timeout=30.0))
        for work_id in WORK_IDS:
            if _files(_work(root, work_id)) != record["works"][work_id]["before"]:
                raise PipelineError(f"{work_id}: canonical work changed before category swap")
        operation = root / "library/.sidecar-operations" / ("categories-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        journal_path = operation / "operation.json"
        journal = {"contract": "ocd-two-commentary-category-swap-v1", "manifest": manifest.resolve().as_posix(),
                   "works": record["works"], "phase": "prepared", "updated_at": _now()}
        _write_json_durable(journal_path, journal)
        for work_id in WORK_IDS:
            original = _io_path(_work(root, work_id) / "work.json").read_bytes()
            before_path = operation / f"{work_id}.before.json"
            _io_path(before_path).write_bytes(original)
            if _sha(before_path) != record["works"][work_id]["before"]["work.json"]:
                raise PipelineError(f"{work_id}: original work snapshot differs")
        replaced: list[str] = []
        try:
            for work_id in WORK_IDS:
                destination = _work(root, work_id) / "work.json"
                candidate = operation / f"{work_id}.work.json"
                _io_path(candidate).write_bytes(_io_path(_work(stage, work_id) / "work.json").read_bytes())
                if _sha(candidate) != record["works"][work_id]["after"]["work.json"]:
                    raise PipelineError(f"{work_id}: staged category bytes changed during copy")
                os.replace(_io_path(candidate), _io_path(destination))
                replaced.append(work_id)
                journal["phase"], journal["replaced"], journal["updated_at"] = "partially-installed", list(replaced), _now()
                _write_json_durable(journal_path, journal)
            for work_id in WORK_IDS:
                if _files(_work(root, work_id)) != record["works"][work_id]["after"]:
                    raise PipelineError(f"{work_id}: installed work tree differs")
                validate_acceptance(_io_path(_acceptance(_work(root, work_id))), root=_io_path(root))
            journal["phase"], journal["updated_at"] = "complete", _now()
            _write_json_durable(journal_path, journal)
            return {"status": "installed-and-acceptance-validated", "operation": operation.as_posix()}
        except BaseException:
            try:
                for work_id in reversed(replaced):
                    destination = _work(root, work_id) / "work.json"
                    if _sha(destination) != record["works"][work_id]["after"]["work.json"]:
                        raise PipelineError(f"{work_id}: live category bytes changed; manual recovery required")
                    original = record["works"][work_id]["before"]["work.json"]
                    before_path = operation / f"{work_id}.before.json"
                    if not _io_path(before_path).is_file() or _sha(before_path) != original:
                        raise PipelineError(f"{work_id}: original work snapshot missing; manual recovery required")
                    os.replace(_io_path(before_path), _io_path(destination))
                journal["phase"], journal["updated_at"] = "rolled-back", _now()
                _write_json_durable(journal_path, journal)
            except BaseException as exc:
                journal["phase"], journal["rollback_error"], journal["updated_at"] = "recovery-required", str(exc), _now()
                _write_json_durable(journal_path, journal)
                raise PipelineError(f"category rollback requires recovery: {operation}") from exc
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    if args.prepare and args.apply:
        parser.error("--prepare and --apply are mutually exclusive")
    if args.prepare:
        result = prepare(manifest=args.manifest)
    elif args.apply:
        result = apply(args.manifest)
    else:
        record, _root, _stage = preflight(args.manifest)
        result = {"status": "ready", "works": list(record["works"]),
                  "changed_files": 2}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
