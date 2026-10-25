"""Preflight or guardedly install Barnes' validated extracted-member master.

Default CLI mode is read-only. Apply swaps one verified work directory and
retains its old generation for rollback; a source or state drift fails closed.
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

from build.tools import prepare_barnes_member_set_acceptance as route
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path


CONTRACT = "ocd-barnes-member-set-install-manifest-v1"
DEFAULT_MANIFEST = Path("plans/2026-09-22-source-preflight/barnes-member-set-acceptance-install-stage-20260926.json")
MASTER = Path("forms/barnes-english/editions/crosswire-sword-v1.1/master.tei.xml")
ACCEPTANCE = MASTER.with_name("acceptance.json")
EVIDENCE = route.EVIDENCE.relative_to(route.WORK)
EXTERNAL_MANIFEST = route.MANIFEST.as_posix()
EXTERNAL_HANDOFF = route.HANDOFF.as_posix()
GAP_REASON = "166 unrepresentable source bytes as explicit byte-provenance gaps across 136 carriers"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def _safe_roots(root: Path, promoted: Path) -> tuple[Path, Path]:
    root = root.resolve(strict=True)
    promoted = promoted.resolve(strict=True)
    if root == promoted or root in promoted.parents or promoted in root.parents:
        raise PipelineError("Barnes install roots overlap")
    return root, promoted


def _dependencies(root: Path, promoted: Path) -> dict[str, str]:
    state = json.loads(_io_path(promoted / route.WORK / "state.json").read_text(encoding="utf-8"))
    references = {EXTERNAL_MANIFEST, EXTERNAL_HANDOFF}
    for target in state["targets"]:
        references.update(ref for ref in target["evidence"] if ref.startswith(("raw/", "sources/")))
    result = {}
    for ref in sorted(references):
        relative = Path(ref)
        if relative.is_absolute() or ".." in relative.parts:
            raise PipelineError(f"Barnes dependency path is unsafe: {ref}")
        canonical = resolve_repo_path(root, ref) if relative.parts[0] == "raw" else root / relative
        staged = promoted / relative
        if not _io_path(canonical).is_file() or not _io_path(staged).is_file():
            raise PipelineError(f"Barnes dependency is missing: {ref}")
        canonical_sha, staged_sha = _sha(canonical), _sha(staged)
        if canonical_sha != staged_sha:
            raise PipelineError(f"Barnes dependency differs between canonical and promoted roots: {ref}")
        result[ref] = canonical_sha
    return result


def _scoped(before: Mapping[str, str], after: Mapping[str, str]) -> None:
    if MASTER.as_posix() in before or ACCEPTANCE.as_posix() in before:
        raise PipelineError("Barnes canonical master or acceptance already exists")
    if MASTER.as_posix() not in after or ACCEPTANCE.as_posix() not in after:
        raise PipelineError("Barnes promoted master or acceptance is missing")
    if any(path.startswith(EVIDENCE.as_posix() + "/") for path in before):
        raise PipelineError("Barnes versioned evidence directory already exists")
    permitted = {"state.json", MASTER.as_posix(), ACCEPTANCE.as_posix()}
    for path in set(before) | set(after):
        if path.startswith(EVIDENCE.as_posix() + "/"):
            if path in before:
                raise PipelineError("Barnes existing evidence would be overwritten")
        elif path in permitted:
            if path == "state.json" and (path not in before or path not in after):
                raise PipelineError("Barnes state sidecar is missing")
        elif before.get(path) != after.get(path):
            raise PipelineError(f"Barnes install changes unrelated work file: {path}")
    if not any(path.startswith(EVIDENCE.as_posix() + "/") for path in after):
        raise PipelineError("Barnes promoted evidence directory is empty")


def _valid_promoted(promoted: Path, after: Mapping[str, str]) -> None:
    record = validate_acceptance(promoted / route.WORK / ACCEPTANCE, root=promoted)
    state = validate_state(promoted / route.WORK / "state.json", root=promoted)
    edition = next((item for item in state["targets"] if item["target_id"] == route.IDENTITY["edition_id"]), None)
    if (record["identity"] != route.IDENTITY
            or record["promotion"]["status"] != "promoted"
            or record["decision"]["agent_assessment"]["status"] != "accepted"
            or record["review"]["coverage"]["status"] != "partial"
            or not isinstance(edition, dict)
            or edition["stage"] != "accepted"
            or GAP_REASON not in edition.get("reason", "")
            or after[MASTER.as_posix()] != record["promotion"]["master"]["sha256"]):
        raise PipelineError("Barnes promoted scope, gap reason, or master differs")
    decision = record["decision"]["agent_assessment"]
    if "complete readable transcription" not in decision["unassessed_stronger_claims"]:
        raise PipelineError("Barnes acceptance lost its readable-text limitation")


def prepare_manifest(root: Path, promoted: Path, output: Path) -> dict[str, object]:
    root, promoted = _safe_roots(root, promoted)
    if output.exists():
        raise PipelineError("Barnes install manifest output must be fresh")
    before, after = _files(root / route.WORK), _files(promoted / route.WORK)
    _scoped(before, after)
    _valid_promoted(promoted, after)
    dependencies = _dependencies(root, promoted)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    record: dict[str, object] = {
        "contract": CONTRACT, "prepared_at": _now(), "status": "staged-only",
        "canonical_root": root.as_posix(), "promoted_root": promoted.as_posix(),
        "work_id": route.IDENTITY["work_id"],
        "before": before, "after": after, "changed_paths": changed,
        "external_dependencies": dependencies,
        "acceptance_limit": "complete extracted electronic source member set with 166 explicit gaps; no complete readable transcription",
    }
    _write(output, record)
    return record


def preflight(manifest: Path) -> tuple[dict[str, object], Path, Path]:
    record = json.loads(manifest.read_text(encoding="utf-8"))
    if record.get("contract") != CONTRACT or record.get("work_id") != route.IDENTITY["work_id"]:
        raise PipelineError("Barnes install manifest contract or work identity differs")
    root, promoted = _safe_roots(Path(record["canonical_root"]), Path(record["promoted_root"]))
    if root.as_posix() != record["canonical_root"] or promoted.as_posix() != record["promoted_root"]:
        raise PipelineError("Barnes install root changed")
    before, after = _files(root / route.WORK), _files(promoted / route.WORK)
    if before != record.get("before") or after != record.get("after"):
        raise PipelineError("Barnes install manifest is stale")
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    if changed != record.get("changed_paths"):
        raise PipelineError("Barnes changed-path inventory differs")
    _scoped(before, after)
    _valid_promoted(promoted, after)
    if _dependencies(root, promoted) != record.get("external_dependencies"):
        raise PipelineError("Barnes external source/package evidence changed")
    return record, root, promoted


def _copy_work_tree(source: Path, destination: Path) -> None:
    source_io, destination_io = _io_path(source), _io_path(destination)
    for relative in _files(source):
        target = destination_io / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_io / relative, target)


def install(manifest: Path, *, fail_at: Callable[[str], None] | None = None) -> dict[str, object]:
    record, root, promoted = preflight(manifest)
    target = root / route.WORK
    source = promoted / route.WORK
    operation = root / ".tmp_audit" / f"barnes-member-set-install-{uuid.uuid4().hex}"
    with acquire_jsonl_lock(target):
        if _files(target) != record["before"] or _files(source) != record["after"]:
            raise PipelineError("Barnes work generation changed while acquiring lock")
        if _dependencies(root, promoted) != record["external_dependencies"]:
            raise PipelineError("Barnes source/package evidence changed while acquiring lock")
        operation.mkdir(parents=True, exist_ok=False)
        incoming, old, failed_new = (operation / name for name in ("incoming", "old", "failed-new"))
        swapped_old = swapped_new = False
        try:
            _copy_work_tree(source, incoming)
            if _files(incoming) != record["after"]:
                raise PipelineError("Barnes copied incoming generation differs")
            if fail_at is not None:
                fail_at("after-copy")
            if _files(target) != record["before"]:
                raise PipelineError("Barnes canonical generation changed during copy")
            if _dependencies(root, promoted) != record["external_dependencies"]:
                raise PipelineError("Barnes source/package evidence changed during copy")
            os.replace(target, old)
            swapped_old = True
            if fail_at is not None:
                fail_at("after-old-rename")
            os.replace(incoming, target)
            swapped_new = True
            if fail_at is not None:
                fail_at("after-new-rename")
            if _files(target) != record["after"]:
                raise PipelineError("Barnes installed generation differs")
            validate_acceptance(target / ACCEPTANCE, root=root)
            validate_state(target / "state.json", root=root)
            if fail_at is not None:
                fail_at("after-validation")
            result: dict[str, object] = {
                "status": "installed-and-validated", "operation": operation.as_posix(),
                "old_generation": old.as_posix(), "before_file_count": len(record["before"]),
                "after_file_count": len(record["after"]),
                "master_sha256": record["after"][MASTER.as_posix()],
                "acceptance_sha256": record["after"][ACCEPTANCE.as_posix()],
            }
            _write(operation / "result.json", result)
            return result
        except Exception:
            if swapped_new:
                if _files(target) == record["after"]:
                    os.replace(target, failed_new)
                else:
                    raise PipelineError("Barnes new generation changed after swap; old generation retained for recovery")
            if swapped_old and not target.exists():
                os.replace(old, target)
                if _files(target) != record["before"]:
                    raise PipelineError("Barnes rollback restored unexpected bytes")
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--root", type=Path, default=route.ROOT)
    parser.add_argument("--promoted", type=Path, default=Path("C:/Scratch/barnes-member-set-agent-promoted-20260926-v2"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.prepare and args.apply:
        parser.error("--prepare and --apply are mutually exclusive")
    if args.prepare:
        result = prepare_manifest(args.root, args.promoted, args.manifest)
    elif args.apply:
        result = install(args.manifest)
    else:
        manifest, _root, _promoted = preflight(args.manifest)
        result = {"status": "ready", "changed_paths": len(manifest["changed_paths"])}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
