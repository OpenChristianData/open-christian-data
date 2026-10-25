"""Prepare, preflight, or guardedly install Robertson's complete accepted work.

The existing Matthew and Mark acquisition records stay byte-identical.  The
replacement work generation adds their coordinated source set, accepted TEI,
acceptance, and evidence together.  The default command is read-only.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from build.tools import prepare_robertson_electronic_acceptance as route
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, io_path, load_json, write_json
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import (
    PROMOTED_MASTER_REASON,
    make_file_binding,
    validate_acceptance,
    write_acceptance,
)
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable


CONTRACT = "ocd-robertson-complete-generation-install-v1"
DEFAULT_PENDING = Path("C:/Scratch/Open Christian Data/t")
DEFAULT_PROMOTED = Path("C:/Scratch/Open Christian Data/p")
DEFAULT_RECEIPT = route.ROOT / "plans/2026-09-22-source-preflight/robertson-electronic-acceptance-install-stage-20260926.json"
WORK = route.WORK
EDITION = route.EDITION
WORK_ID = route.IDENTITY["work_id"]
EDITION_REL = EDITION.relative_to(WORK)
ACQUISITION_REL = route.ACQUISITION.relative_to(WORK)
MEMBER_SET_REL = route.MEMBER_SET.relative_to(WORK)
ACCEPTANCE_REL = EDITION_REL / "acceptance.json"
MASTER_REL = EDITION_REL / "master.tei.xml"
EVIDENCE_REL = route.EVIDENCE.relative_to(WORK)
ORIGINAL_IDS = tuple(item[0] for item in route.SOURCES)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _copy_tree(source: Path, destination: Path) -> dict[str, str]:
    if _io_path(destination).exists():
        raise PipelineError(f"Robertson destination must be fresh: {destination}")
    paths = _files(source)
    if not paths:
        raise PipelineError(f"Robertson input tree is empty: {source}")
    _io_path(destination).mkdir(parents=True)
    for relative in paths:
        target = _io_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(source / relative), target)
    if _files(destination) != paths:
        raise PipelineError("Robertson copied tree differs from input")
    return paths


def _roots(root: Path, pending: Path, promoted: Path) -> tuple[Path, Path, Path]:
    root, pending, promoted = root.resolve(strict=True), pending.resolve(strict=True), promoted.resolve(strict=True)
    for left, right in ((root, pending), (root, promoted), (pending, promoted)):
        if left == right or left in right.parents or right in left.parents:
            raise PipelineError("Robertson canonical, pending, and promoted roots overlap")
    return root, pending, promoted


def prepare_promoted(pending: Path, destination: Path) -> Path:
    pending = pending.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or not destination.parent.is_dir() or destination.parent.is_symlink():
        raise PipelineError("Robertson promoted destination must be fresh under an ordinary parent")
    if destination == pending or pending in destination.parents or destination in pending.parents:
        raise PipelineError("Robertson promotion roots overlap")
    pending_record = validate_acceptance(pending / EDITION / "acceptance.json", root=pending)
    if pending_record["identity"] != route.IDENTITY or pending_record["promotion"]["status"] != "pending":
        raise PipelineError("Robertson input is not the exact pending acceptance")
    _copy_tree(pending, destination)
    acceptance_path = destination / EDITION / "acceptance.json"
    record = load_json(io_path(acceptance_path))
    candidate = destination / record["technical"]["candidate"]["path"]
    master = destination / EDITION / "master.tei.xml"
    _io_path(master.parent).mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(candidate), _io_path(master))
    if _sha(master) != record["technical"]["candidate"]["sha256"]:
        raise PipelineError("Robertson promoted master differs from reviewed candidate")
    record["promotion"] = dict(record["promotion"])
    record["promotion"]["status"] = "promoted"
    record["promotion"]["promoted_at"] = _now()
    record["promotion"]["master"] = make_file_binding(destination, master)
    write_acceptance(acceptance_path, record)
    state_path = destination / WORK / "state.json"
    state = load_json(io_path(state_path))
    edition = next((item for item in state["targets"] if item["target_id"] == route.IDENTITY["edition_id"]), None)
    if edition is None or edition["target_type"] != "edition" or edition["stage"] != "acquired":
        raise PipelineError("Robertson pending edition state changed")
    edition["stage"] = "accepted"
    edition["reason"] = PROMOTED_MASTER_REASON
    edition["updated_at"] = _now()
    for reference in ((EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()):
        if reference not in edition["evidence"]:
            edition["evidence"].append(reference)
    write_json(io_path(state_path), state)
    validate_acceptance(acceptance_path, root=destination)
    validate_state(state_path, root=destination)
    return destination


def _outside_dependencies(root: Path, promoted: Path) -> dict[str, str]:
    prefix = WORK.as_posix() + "/"
    result = {}
    for relative, digest in _files(promoted).items():
        if relative.startswith(prefix):
            continue
        part = Path(relative)
        source = resolve_repo_path(root, relative) if part.parts[0] in {"raw", "reports", "exports"} else root / part
        if not _io_path(source).is_file() or _sha(source) != digest:
            raise PipelineError(f"Robertson external evidence differs from canonical: {relative}")
        result[relative] = digest
    for source_name, _, digest in route.SOURCES:
        acquisition = root / EDITION / "acquisitions" / f"{source_name}.json"
        if not _io_path(acquisition).is_file():
            raise PipelineError(f"Robertson original acquisition missing: {source_name}")
        old = load_json(io_path(acquisition))
        if old["retained_files"][0]["sha256"] != digest:
            raise PipelineError(f"Robertson original source hash changed: {source_name}")
    return result


def _scoped(root: Path, promoted: Path, before: Mapping[str, str], after: Mapping[str, str]) -> None:
    if not {"work.json", "state.json"} <= set(before) or not {"work.json", "state.json"} <= set(after):
        raise PipelineError("Robertson work/state sidecars are missing")
    if any(path in before for path in (MASTER_REL.as_posix(), ACCEPTANCE_REL.as_posix(), ACQUISITION_REL.as_posix(), MEMBER_SET_REL.as_posix())):
        raise PipelineError("Robertson acceptance or coordinated source already exists")
    new_allowed = {MASTER_REL.as_posix(), ACCEPTANCE_REL.as_posix(), ACQUISITION_REL.as_posix(), MEMBER_SET_REL.as_posix()}
    evidence_prefix = EVIDENCE_REL.as_posix() + "/"
    for path in set(before) | set(after):
        if path in {"work.json", "state.json"}:
            continue
        if path.startswith(evidence_prefix):
            if path in before or path not in after:
                raise PipelineError("Robertson versioned evidence was overwritten or removed")
        elif path in new_allowed:
            if path in before or path not in after:
                raise PipelineError(f"Robertson new authority is not solely additive: {path}")
        elif before.get(path) != after.get(path):
            raise PipelineError(f"Robertson unrelated work file differs: {path}")
    if not any(path.startswith(evidence_prefix) for path in after):
        raise PipelineError("Robertson promoted evidence is empty")

    old_work = load_work(root / WORK / "work.json")
    new_work = load_work(promoted / WORK / "work.json")
    expected_work = json.loads(json.dumps(old_work))
    ids = expected_work["textual_forms"][0]["editions"][0]["acquisition_ids"]
    if ids != list(ORIGINAL_IDS):
        raise PipelineError("Robertson original acquisition order differs")
    ids.append(route.ACQUISITION_ID)
    for reference in (route.ACQUISITION.as_posix(), route.MEMBER_SET.as_posix()):
        if reference not in expected_work["evidence"]:
            expected_work["evidence"].append(reference)
    if new_work != expected_work:
        raise PipelineError("Robertson promoted work sidecar changes more than the source-set acquisition")

    old_state = load_json(io_path(root / WORK / "state.json"))
    new_state = load_json(io_path(promoted / WORK / "state.json"))
    if old_state["work_id"] != WORK_ID or new_state["work_id"] != WORK_ID:
        raise PipelineError("Robertson state work identity differs")
    old_targets, new_targets = old_state["targets"], new_state["targets"]
    if len(old_targets) != 3 or len(new_targets) != 4:
        raise PipelineError("Robertson state target count changed")
    for old_target, new_target in zip(old_targets, new_targets[:3], strict=True):
        if old_target["target_id"] in ORIGINAL_IDS:
            if old_target != new_target:
                raise PipelineError("Robertson original acquisition state changed")
            continue
        if old_target["target_id"] != route.IDENTITY["edition_id"]:
            raise PipelineError("Robertson existing edition target differs")
        expected_edition = {k: v for k, v in old_target.items() if k not in {"stage", "reason", "updated_at", "evidence"}}
        proposed_edition = {k: v for k, v in new_target.items() if k not in {"stage", "reason", "updated_at", "evidence"}}
        expected_evidence = list(old_target["evidence"])
        for reference in ((EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()):
            if reference not in expected_evidence:
                expected_evidence.append(reference)
        if (expected_edition != proposed_edition or new_target["stage"] != "accepted"
                or new_target["reason"] != PROMOTED_MASTER_REASON or new_target["evidence"] != expected_evidence):
            raise PipelineError("Robertson edition state transition differs")
    added = new_targets[3]
    if added["target_id"] != route.ACQUISITION_ID or added["target_type"] != "acquisition" or added["stage"] != "acquired":
        raise PipelineError("Robertson coordinated acquisition state differs")
    expected_sources = [route.ACQUISITION.as_posix(), route.MEMBER_SET.as_posix()]
    expected_sources.extend((EDITION / "acquisitions" / f"{aid}.json").as_posix() for aid in ORIGINAL_IDS)
    if added["evidence"] != expected_sources:
        raise PipelineError("Robertson coordinated acquisition evidence differs")
    if after[MASTER_REL.as_posix()] != after[(EVIDENCE_REL / "candidate.tei.xml").as_posix()]:
        raise PipelineError("Robertson master differs from reviewed candidate")


def _valid_promoted(promoted: Path, after: Mapping[str, str]) -> None:
    record = validate_acceptance(promoted / EDITION / "acceptance.json", root=promoted)
    acquisition = validate_acquisition(promoted / route.ACQUISITION, root=promoted)
    validate_state(promoted / WORK / "state.json", root=promoted)
    if (record["source"]["source_kind"] != "retained-member-set"
            or record["source"]["source_path"] != route.MEMBER_SET.as_posix()
            or acquisition["source_kind"] != "retained-member-set"
            or [item["path"] for item in acquisition["retained_files"]]
            != [f"raw/ccel/robertson-word-pictures/robertson_at_wp_{member}.xml" for member in ("matt", "mark")]):
        raise PipelineError("Robertson acceptance must bind the two actual retained XML members")
    if (record["identity"] != route.IDENTITY or record["promotion"]["status"] != "promoted"
            or record["decision"]["agent_assessment"]["status"] != "accepted"
            or record["decision"]["human_decision"]["status"] != "not-recorded"
            or record["promotion"]["master"]["sha256"] != after[MASTER_REL.as_posix()]):
        raise PipelineError("Robertson promoted acceptance identity or scope differs")
    if "complete print Vol. I identity" not in record["decision"]["agent_assessment"]["unassessed_stronger_claims"]:
        raise PipelineError("Robertson print-volume limitation was lost")


def prepare_manifest(root: Path, pending: Path, promoted: Path, output: Path) -> dict[str, object]:
    root, pending, promoted = _roots(root, pending, promoted)
    if output.exists():
        raise PipelineError("Robertson install receipt must be fresh")
    before, pending_files, after = _files(root / WORK), _files(pending / WORK), _files(promoted / WORK)
    _scoped(root, promoted, before, after)
    _valid_promoted(promoted, after)
    if pending_files.get("work.json") != after.get("work.json") or not _io_path(pending / EDITION / "acceptance.json").is_file():
        raise PipelineError("Robertson promoted generation is detached from pending acceptance")
    dependencies = _outside_dependencies(root, promoted)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    record: dict[str, object] = {
        "contract": CONTRACT, "status": "staged-only", "prepared_at": _now(),
        "canonical_root": root.as_posix(), "pending_root": pending.as_posix(), "promoted_root": promoted.as_posix(),
        "work_id": WORK_ID, "before": before, "pending": pending_files, "after": after,
        "changed_paths": changed, "external_dependencies": dependencies,
        "source_members": [{"member": member, "sha256": digest, "original_acquisition_id": aid}
                           for aid, member, digest in route.SOURCES],
        "original_acquisition_urls": [load_json(io_path(root / EDITION / "acquisitions" / f"{aid}.json"))["url"] for aid in ORIGINAL_IDS],
        "limits": ["assigned Matthew then Mark CCEL electronic witness only", "print-volume identity unresolved", "rights and publication separate"],
    }
    _write_json_durable(output, record)
    return record


def preflight(manifest: Path) -> tuple[dict[str, object], Path, Path]:
    manifest = manifest.resolve(strict=True)
    record = load_json(io_path(manifest))
    if record.get("contract") != CONTRACT or record.get("work_id") != WORK_ID:
        raise PipelineError("Robertson install receipt contract differs")
    root, pending, promoted = _roots(Path(record["canonical_root"]), Path(record["pending_root"]), Path(record["promoted_root"]))
    if (root.as_posix(), pending.as_posix(), promoted.as_posix()) != (record["canonical_root"], record["pending_root"], record["promoted_root"]):
        raise PipelineError("Robertson install roots changed")
    before, pending_files, after = _files(root / WORK), _files(pending / WORK), _files(promoted / WORK)
    if (before != record.get("before") or pending_files != record.get("pending") or after != record.get("after")):
        raise PipelineError("Robertson complete-generation receipt is stale")
    _scoped(root, promoted, before, after)
    _valid_promoted(promoted, after)
    if _outside_dependencies(root, promoted) != record.get("external_dependencies"):
        raise PipelineError("Robertson external source or review evidence changed")
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    if changed != record.get("changed_paths"):
        raise PipelineError("Robertson changed-file inventory differs")
    urls = [load_json(io_path(root / EDITION / "acquisitions" / f"{aid}.json"))["url"] for aid in ORIGINAL_IDS]
    if urls != record.get("original_acquisition_urls"):
        raise PipelineError("Robertson original CCEL acquisition URLs changed")
    return record, root, promoted


def install(manifest: Path, *, fail_at: Callable[[str], None] | None = None) -> dict[str, object]:
    record, root, promoted = preflight(manifest)
    target = root / WORK
    source = promoted / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != record["before"] or _files(source) != record["after"]:
            raise PipelineError("Robertson generation changed while acquiring lock")
        if _outside_dependencies(root, promoted) != record["external_dependencies"]:
            raise PipelineError("Robertson dependencies changed while acquiring lock")
        operation = root / "library/.sidecar-operations" / ("rwp-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ("incoming", "previous", "failed-new"))
        journal_path = operation / "operation.json"
        journal: dict[str, object] = {
            "contract": "ocd-robertson-work-swap-operation-v1", "work_id": WORK_ID,
            "manifest": manifest.resolve().as_posix(), "before": record["before"], "after": record["after"],
            "phase": "created", "updated_at": _now(),
        }
        _write_json_durable(journal_path, journal)
        moved = live = False
        try:
            _copy_tree(source, incoming)
            if _files(incoming) != record["after"] or _files(target) != record["before"]:
                raise PipelineError("Robertson incoming work generation differs")
            journal["phase"], journal["updated_at"] = "prepared", _now()
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-copy")
            if _outside_dependencies(root, promoted) != record["external_dependencies"]:
                raise PipelineError("Robertson source evidence changed during copy")
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            journal["phase"], journal["updated_at"] = "previous-moved", _now()
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-old-rename")
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            journal["phase"], journal["updated_at"] = "new-live", _now()
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-new-rename")
            if _files(target) != record["after"]:
                raise PipelineError("Robertson installed work generation differs")
            validate_acceptance(_io_path(target / ACCEPTANCE_REL), root=_io_path(root))
            validate_state(_io_path(target / "state.json"), root=_io_path(root))
            if fail_at:
                fail_at("after-validation")
            journal["phase"], journal["updated_at"] = "complete", _now()
            _write_json_durable(journal_path, journal)
            return {"status": "installed-and-validated", "operation": operation.as_posix(),
                    "before_count": len(record["before"]), "after_count": len(record["after"]),
                    "master_sha256": record["after"][MASTER_REL.as_posix()],
                    "acceptance_sha256": record["after"][ACCEPTANCE_REL.as_posix()]}
        except BaseException:
            try:
                if live:
                    if _files(target) != record["after"]:
                        raise PipelineError("Robertson live generation changed after swap")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != record["before"]:
                        raise PipelineError("Robertson rollback previous generation differs")
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != record["before"]:
                        raise PipelineError("Robertson rollback restored unexpected bytes")
                journal["phase"] = "rolled-back" if moved else "failed-before-swap"
                journal["updated_at"] = _now()
                _write_json_durable(journal_path, journal)
            except BaseException as rollback_error:
                journal["phase"], journal["rollback_error"], journal["updated_at"] = "recovery-required", str(rollback_error), _now()
                _write_json_durable(journal_path, journal)
                raise PipelineError(f"Robertson rollback needs recovery: {operation}") from rollback_error
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=route.ROOT)
    parser.add_argument("--pending", type=Path, default=DEFAULT_PENDING)
    parser.add_argument("--promoted", type=Path, default=DEFAULT_PROMOTED)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.prepare and args.apply:
        parser.error("--prepare and --apply are mutually exclusive")
    if args.prepare:
        prepare_promoted(args.pending, args.promoted)
        result = prepare_manifest(args.root, args.pending, args.promoted, args.manifest)
    elif args.apply:
        result = install(args.manifest)
    else:
        record, _root, _promoted = preflight(args.manifest)
        result = {"status": "ready", "changed_paths": len(record["changed_paths"]),
                  "before_count": len(record["before"]), "after_count": len(record["after"])}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
