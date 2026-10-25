"""Preflight and guardedly install Hodge Vol. II's complete accepted work generation.

Default is read-only. --apply swaps only the Hodge work directory under a lock,
with a journal and checked rollback. This route permits the exact staged
acquisition scope correction that the generic additive installer refuses.
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

from build.tools import prepare_hodge_vol2_electronic_acceptance as route
from build.tools import prepare_hodge_vol2_complete as complete_route
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, io_path, load_json
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import (PROMOTED_MASTER_REASON, validate_acceptance,
    _validate_acceptance_for_work, make_file_binding, write_acceptance)
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable

CONTRACT = "ocd-hodge-vol2-complete-generation-install-v1"
WORK = route.WORK
EDITION = route.EDITION
ACQUISITION = route.ACQUISITION
EDITION_REL = EDITION.relative_to(WORK)
ACQUISITION_REL = ACQUISITION.relative_to(WORK)
ACCEPTANCE_REL = EDITION_REL / "acceptance.json"
MASTER_REL = EDITION_REL / "master.tei.xml"
EVIDENCE_REL = route.EVIDENCE.relative_to(WORK)
DEFAULT_RECEIPT = route.ROOT / "plans/2026-09-22-source-preflight/hodge-vol2-electronic-acceptance-install-stage-20260926.json"
COMPLETE_CONTRACT = "ocd-hodge-vol2-five-root-install-v1"
COMPLETE_REVISION = "hodge-vol2-complete-electronic-v1"
COMPLETE_EVIDENCE = Path("integration/hodge-vol2-complete-electronic-v1")
COMPLETE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/37c-204-hodge-systematic-theology-vol-2-20260917-v3")
COMPLETE_PENDING = COMPLETE_HOME / "complete-volume-20261008-pending-v3"
COMPLETE_PENDING_SHA = "b8bb44dcec0409c0a6a1949d6b0b1b082635f8b60d8cc628e833ae57ceb3e094"
COMPLETE_MASTER_SHA = "f766c4e047e37f86d503c58b5c646d0d0d4ebd146288603c96685da755759e10"
OLD_MASTER_SHA = "c7bdfec7101c041bc135b56b28083b6eafe848fa504889bd1982baa914efacd7"
OLD_ACCEPTANCE_SHA = "5634d799e4e66d8a4e80800dde559ab4c7a49b89494a437edc04032196afb053"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def copy_tree(source: Path, dest: Path) -> dict[str, str]:
    if _io_path(dest).exists():
        raise PipelineError(f"Hodge destination must be fresh: {dest}")
    files = _files(source)
    if not files:
        raise PipelineError("Hodge input generation is empty")
    _io_path(dest).mkdir(parents=True)
    for relative in files:
        target = _io_path(dest / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(source / relative), target)
    if _files(dest) != files:
        raise PipelineError("Hodge copied generation differs")
    return files


def roots(root: Path, pending: Path, promoted: Path) -> tuple[Path, Path, Path]:
    root, pending, promoted = (item.resolve(strict=True) for item in (root, pending, promoted))
    for left, right in ((root, pending), (root, promoted), (pending, promoted)):
        if left == right or left in right.parents or right in left.parents:
            raise PipelineError("Hodge canonical, pending, and promoted roots overlap")
    return root, pending, promoted


def outside_dependencies(root: Path, promoted: Path, *, complete: bool = False) -> dict[str, str]:
    prefix = WORK.as_posix() + "/"
    result = {}
    for relative, expected in _files(promoted).items():
        if relative.startswith(prefix):
            continue
        first = Path(relative).parts[0]
        source = resolve_repo_path(root, relative) if first in {"raw", "reports", "exports"} else root / relative
        if not _io_path(source).is_file() or digest(source) != expected:
            raise PipelineError(f"Hodge outside evidence differs: {relative}")
        result[relative] = expected
    manifest = load_json(io_path(root / (complete_route.MANIFEST if complete else route.MANIFEST)))
    producer = root / manifest["converter"]["implementation_path"]
    oracle = root / manifest["validator"]["implementation_path"]
    if (digest(producer) != manifest["converter"]["implementation_sha256"]
            or digest(oracle) != manifest["validator"]["implementation_sha256"]):
        raise PipelineError("Hodge versioned converter or independent oracle differs")
    return result


def complete_scoped(root: Path, promoted: Path, before: Mapping[str, str], after: Mapping[str, str]) -> None:
    """Permit only this frozen accepted-parts to complete-volume correction."""
    if (before.get(MASTER_REL.as_posix()) != OLD_MASTER_SHA
            or before.get(ACCEPTANCE_REL.as_posix()) != OLD_ACCEPTANCE_SHA
            or before.get("work.json") != after.get("work.json")):
        raise PipelineError("Hodge complete-volume accepted preimage or work identity differs")
    prefix = COMPLETE_EVIDENCE.as_posix() + "/"
    allowed = {"state.json", ACQUISITION_REL.as_posix(), MASTER_REL.as_posix(), ACCEPTANCE_REL.as_posix()}
    for path in set(before) | set(after):
        if path.startswith(prefix):
            if path in before or path not in after:
                raise PipelineError("Hodge complete-volume evidence is not fresh")
        elif path not in allowed and before.get(path) != after.get(path):
            raise PipelineError(f"Hodge complete-volume unrelated authority differs: {path}")
    if (after.get(MASTER_REL.as_posix()) != COMPLETE_MASTER_SHA
            or after.get((COMPLETE_EVIDENCE / "candidate.tei.xml").as_posix()) != COMPLETE_MASTER_SHA
            or after.get((COMPLETE_EVIDENCE / "previous-master.tei.xml").as_posix()) != OLD_MASTER_SHA
            or after.get((COMPLETE_EVIDENCE / "previous-acceptance.json").as_posix()) != OLD_ACCEPTANCE_SHA
            or after.get((COMPLETE_EVIDENCE / "previous-acquisition.json").as_posix()) != before.get(ACQUISITION_REL.as_posix())):
        raise PipelineError("Hodge complete-volume new or preserved authority binding differs")
    old_acq = load_json(io_path(root / ACQUISITION))
    expected_acq = json.loads(json.dumps(old_acq))
    expected_acq["source_scope"] = complete_route.SCOPE
    expected_acq["retained_files"][0]["scope"] = complete_route.SCOPE
    if load_json(io_path(promoted / ACQUISITION)) != expected_acq:
        raise PipelineError("Hodge complete-volume acquisition exceeds two scope descriptions")
    old_state = load_json(io_path(root / WORK / "state.json"))
    new_state = load_json(io_path(promoted / WORK / "state.json"))
    expected_state = json.loads(json.dumps(old_state))
    old_edition = next(t for t in expected_state["targets"] if t["target_id"] == route.IDENTITY["edition_id"])
    new_edition = next(t for t in new_state["targets"] if t["target_id"] == route.IDENTITY["edition_id"])
    if old_edition["stage"] != "accepted" or not new_edition.get("updated_at"):
        raise PipelineError("Hodge complete-volume edition transition differs")
    old_edition.update(reason=PROMOTED_MASTER_REASON, updated_at=new_edition["updated_at"])
    if new_state != expected_state:
        raise PipelineError("Hodge complete-volume state exceeds accepted edition timestamp/reason")


def complete_promoted(promoted: Path, after: Mapping[str, str]) -> None:
    record = _validate_acceptance_for_work(promoted / EDITION / "acceptance.json", root=promoted, work_id=route.WORK_ID)
    if (record["identity"] != route.IDENTITY or record["promotion"]["status"] != "promoted"
            or record["representation_revision"]["id"] != COMPLETE_REVISION
            or record["scope"]["declared"] != complete_route.SCOPE
            or record["decision"]["agent_assessment"]["status"] != "accepted"
            or record["decision"]["human_decision"]["status"] != "not-recorded"
            or record["promotion"]["master"]["sha256"] != COMPLETE_MASTER_SHA
            or after.get(MASTER_REL.as_posix()) != COMPLETE_MASTER_SHA):
        raise PipelineError("Hodge complete-volume promoted acceptance differs")


def prepare_complete(root: Path, pending: Path, promoted: Path, output: Path) -> dict[str, object]:
    """Promote the existing frozen handoff externally, then freeze its install map."""
    root, pending = root.resolve(strict=True), pending.resolve(strict=True)
    promoted = promoted.absolute()
    if (pending != COMPLETE_PENDING.resolve(strict=True) or promoted.parent.resolve(strict=True) != COMPLETE_HOME.resolve(strict=True)
            or not promoted.name.startswith("complete-volume-") or promoted.exists() or output.exists()
            or digest(pending / "stage-receipt.json") != COMPLETE_PENDING_SHA):
        raise PipelineError("Hodge complete-volume frozen pending handoff or destination differs")
    handoff = load_json(io_path(pending / "stage-receipt.json"))
    before, pending_files = _files(root / WORK), _files(pending / WORK)
    if before != handoff["before"] or pending_files != handoff["pending_files"]:
        raise PipelineError("Hodge complete-volume pending or canonical generation is stale")
    record = validate_acceptance(pending / EDITION / "acceptance.json", root=pending)
    if record["promotion"]["status"] != "pending" or record["technical"]["candidate"]["sha256"] != COMPLETE_MASTER_SHA:
        raise PipelineError("Hodge complete-volume pending acceptance differs")
    # Reuse the frozen handoff; only promotion controls change in this external tree.
    for relative in _files(pending):
        if relative in {"stage-receipt.json", "closeout.json"}:
            continue
        target = _io_path(promoted / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(pending / relative), target)
    master = promoted / EDITION / "master.tei.xml"
    shutil.copy2(_io_path(promoted / Path(record["technical"]["candidate"]["path"])), _io_path(master))
    record["promotion"].update(status="promoted", promoted_at=now(), master=make_file_binding(promoted, master))
    write_acceptance(promoted / EDITION / "acceptance.json", record)
    state_path = promoted / WORK / "state.json"
    state = load_json(io_path(state_path))
    edition_target = next(t for t in state["targets"] if t["target_id"] == route.IDENTITY["edition_id"])
    edition_target.update(reason=PROMOTED_MASTER_REASON, updated_at=now())
    _write_json_durable(state_path, state)
    after = _files(promoted / WORK)
    complete_scoped(root, promoted, before, after)
    complete_promoted(promoted, after)
    dependencies = outside_dependencies(root, promoted, complete=True)
    result = {"contract": COMPLETE_CONTRACT, "status": "staged-only", "prepared_at": now(),
        "canonical_root": root.as_posix(), "pending_root": pending.as_posix(), "promoted_root": promoted.as_posix(),
        "work_id": route.WORK_ID, "before": before, "pending": pending_files, "after": after,
        "changed_paths": sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p)),
        "external_dependencies": dependencies, "pending_receipt_sha256": COMPLETE_PENDING_SHA,
        "installer_sha256": digest(Path(__file__)), "source_path": route.SOURCE.as_posix(), "source_sha256": route.SOURCE_SHA,
        "source_selection": ["i", "ii", "iii", "iv", "v"], "category": "prose",
        "limits": ["Complete retained electronic Volume II only", "Human/visual/print verification separate", "CCEL formatting rights not cleared; publication not authorized"]}
    if _files(root / WORK) != before:
        raise PipelineError("Hodge complete-volume canonical generation changed during preparation")
    _write_json_durable(output, result)
    return result


def scoped(root: Path, promoted: Path, before: Mapping[str, str], after: Mapping[str, str]) -> None:
    old_work = load_work(root / WORK / "work.json")
    new_work = load_work(promoted / WORK / "work.json")
    expected_work = json.loads(json.dumps(old_work))
    if expected_work["textual_forms"][0]["editions"][0].get("category") is not None:
        raise PipelineError("Hodge canonical edition category was already classified")
    expected_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    if new_work != expected_work or before.get("work.json") == after.get("work.json"):
        raise PipelineError("Hodge staged work.json differs beyond the prose edition category")
    if before.get("state.json") is None or after.get("state.json") is None or before.get(ACQUISITION_REL.as_posix()) is None:
        raise PipelineError("Hodge existing work authority is incomplete")
    if any(path in before for path in (MASTER_REL.as_posix(), ACCEPTANCE_REL.as_posix())):
        raise PipelineError("Hodge work already contains acceptance or master")
    allowed_changes = {"work.json", "state.json", ACQUISITION_REL.as_posix(), MASTER_REL.as_posix(), ACCEPTANCE_REL.as_posix()}
    evidence_prefix = EVIDENCE_REL.as_posix() + "/"
    for path in set(before) | set(after):
        if path.startswith(evidence_prefix):
            if path in before or path not in after:
                raise PipelineError("Hodge versioned evidence was overwritten or removed")
        elif path not in allowed_changes and before.get(path) != after.get(path):
            raise PipelineError(f"Hodge unrelated work authority differs: {path}")
    if not all(path in after for path in (MASTER_REL.as_posix(), ACCEPTANCE_REL.as_posix())) or not any(path.startswith(evidence_prefix) for path in after):
        raise PipelineError("Hodge promoted authority or evidence is missing")
    old_acq = load_json(io_path(root / ACQUISITION))
    new_acq = load_json(io_path(promoted / ACQUISITION))
    for key in set(old_acq) | set(new_acq):
        if key not in {"source_path", "source_sha256", "source_bytes", "source_scope", "route", "retained_files", "warnings"} and old_acq.get(key) != new_acq.get(key):
            raise PipelineError(f"Hodge acquisition changed identity/provider authority: {key}")
    if (new_acq.get("source_path") != route.SOURCE.as_posix() or new_acq.get("source_sha256") != route.SOURCE_SHA
            or new_acq.get("source_bytes") != route.SOURCE_BYTES or new_acq.get("source_scope") != route.SCOPE
            or new_acq.get("route") != "born-digital" or len(new_acq.get("retained_files", [])) != 1):
        raise PipelineError("Hodge acquisition selection differs")
    old_member, new_member = old_acq["retained_files"][0], new_acq["retained_files"][0]
    if {key: value for key, value in old_member.items() if key != "scope"} != {key: value for key, value in new_member.items() if key != "scope"}:
        raise PipelineError("Hodge retained XML identity changed")
    if (new_member.get("path") != route.SOURCE.as_posix() or new_member.get("sha256") != route.SOURCE_SHA
            or new_member.get("bytes") != route.SOURCE_BYTES or "roots iii and iv" not in new_member.get("scope", "")):
        raise PipelineError("Hodge retained member scope differs")
    if len(new_acq.get("warnings", [])) != 1 or "rights" not in new_acq["warnings"][0]:
        raise PipelineError("Hodge acquisition caveat differs")
    old_state = load_json(io_path(root / WORK / "state.json"))
    new_state = load_json(io_path(promoted / WORK / "state.json"))
    if old_state.get("work_id") != route.WORK_ID or new_state.get("work_id") != route.WORK_ID or len(old_state["targets"]) != len(new_state["targets"]):
        raise PipelineError("Hodge state identity or target count differs")
    old_by_id = {item["target_id"]: item for item in old_state["targets"]}
    new_by_id = {item["target_id"]: item for item in new_state["targets"]}
    if set(old_by_id) != set(new_by_id) or old_by_id[route.IDENTITY["acquisition_id"]] != new_by_id[route.IDENTITY["acquisition_id"]]:
        raise PipelineError("Hodge acquisition state changed")
    old_edition = old_by_id[route.IDENTITY["edition_id"]]
    new_edition = new_by_id[route.IDENTITY["edition_id"]]
    expected_evidence = list(old_edition["evidence"])
    for ref in ((EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()):
        if ref not in expected_evidence:
            expected_evidence.append(ref)
    if ({k:v for k,v in old_edition.items() if k not in {"stage", "reason", "updated_at", "evidence"}}
            != {k:v for k,v in new_edition.items() if k not in {"stage", "reason", "updated_at", "evidence"}}
            or new_edition["stage"] != "accepted" or new_edition["reason"] != PROMOTED_MASTER_REASON
            or new_edition["evidence"] != expected_evidence):
        raise PipelineError("Hodge edition state transition differs")
    if after[MASTER_REL.as_posix()] != after[(EVIDENCE_REL / "candidate.tei.xml").as_posix()]:
        raise PipelineError("Hodge master differs from accepted candidate")


def valid_promoted(promoted: Path, after: Mapping[str, str]) -> None:
    acceptance = validate_acceptance(promoted / EDITION / "acceptance.json", root=promoted)
    acquisition = validate_acquisition(promoted / ACQUISITION, root=promoted)
    validate_state(promoted / WORK / "state.json", root=promoted)
    if (acceptance["identity"] != route.IDENTITY or acceptance["promotion"]["status"] != "promoted"
            or acceptance["decision"]["agent_assessment"]["status"] != "accepted"
            or acceptance["decision"]["human_decision"]["status"] != "not-recorded"
            or acceptance["scope"]["kind"] != "selection" or acceptance["scope"]["declared"] != route.SCOPE
            or acceptance["promotion"]["master"]["sha256"] != after[MASTER_REL.as_posix()]
            or acquisition["source_path"] != route.SOURCE.as_posix()):
        raise PipelineError("Hodge promoted acceptance differs from bounded electronic selection")


def prepare_manifest(root: Path, pending: Path, promoted: Path, output: Path) -> dict[str, object]:
    root, pending, promoted = roots(root, pending, promoted)
    if output.exists():
        raise PipelineError("Hodge stage receipt must be fresh")
    before, pending_files, after = _files(root / WORK), _files(pending / WORK), _files(promoted / WORK)
    scoped(root, promoted, before, after)
    valid_promoted(promoted, after)
    if (pending_files.get("work.json") != after.get("work.json")
            or pending_files.get(ACQUISITION_REL.as_posix()) != after.get(ACQUISITION_REL.as_posix())
            or pending_files.get(ACCEPTANCE_REL.as_posix()) is None or MASTER_REL.as_posix() in pending_files):
        raise PipelineError("Hodge promoted generation is detached from pending stage")
    dependencies = outside_dependencies(root, promoted)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    record: dict[str, object] = {
        "contract": CONTRACT, "status": "staged-only", "prepared_at": now(),
        "canonical_root": root.as_posix(), "pending_root": pending.as_posix(), "promoted_root": promoted.as_posix(),
        "work_id": route.WORK_ID, "before": before, "pending": pending_files, "after": after,
        "changed_paths": changed, "external_dependencies": dependencies,
        "source_path": route.SOURCE.as_posix(), "source_sha256": route.SOURCE_SHA,
        "source_selection": ["iii", "iv"], "category": "prose", "accounted_unaccepted_roots": ["i", "ii", "v"],
        "limits": ["Part II and III CCEL electronic selection only", "11-locus historical visual sample", "print edition identity, rights and publication separate"],
    }
    _write_json_durable(output, record)
    return record


def preflight(manifest: Path) -> tuple[dict[str, object], Path, Path]:
    record = load_json(io_path(manifest.resolve(strict=True)))
    complete = record.get("contract") == COMPLETE_CONTRACT
    if record.get("contract") not in {CONTRACT, COMPLETE_CONTRACT} or record.get("work_id") != route.WORK_ID:
        raise PipelineError("Hodge install receipt contract differs")
    root, pending, promoted = roots(Path(record["canonical_root"]), Path(record["pending_root"]), Path(record["promoted_root"]))
    before, pending_files, after = _files(root / WORK), _files(pending / WORK), _files(promoted / WORK)
    if (before != record.get("before") or pending_files != record.get("pending") or after != record.get("after")):
        raise PipelineError("Hodge complete-generation receipt is stale")
    if complete:
        if (record.get("installer_sha256") != digest(Path(__file__))
                or record.get("pending_receipt_sha256") != COMPLETE_PENDING_SHA
                or digest(pending / "stage-receipt.json") != COMPLETE_PENDING_SHA
                or record.get("source_selection") != ["i", "ii", "iii", "iv", "v"]
                or record.get("source_sha256") != route.SOURCE_SHA):
            raise PipelineError("Hodge complete-volume frozen installer or handoff differs")
        handoff = load_json(io_path(pending / "stage-receipt.json"))
        if before != handoff["before"] or pending_files != handoff["pending_files"]:
            raise PipelineError("Hodge complete-volume accepted preimage differs from frozen handoff")
        complete_scoped(root, promoted, before, after)
        complete_promoted(promoted, after)
    else:
        scoped(root, promoted, before, after)
        valid_promoted(promoted, after)
    if outside_dependencies(root, promoted, complete=complete) != record.get("external_dependencies"):
        raise PipelineError("Hodge external evidence differs")
    if sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path)) != record.get("changed_paths"):
        raise PipelineError("Hodge changed-file inventory differs")
    return record, root, promoted


def install(manifest: Path, *, fail_at: Callable[[str], None] | None = None) -> dict[str, object]:
    record, root, promoted = preflight(manifest)
    complete = record["contract"] == COMPLETE_CONTRACT
    target, source = root / WORK, promoted / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != record["before"] or _files(source) != record["after"]:
            raise PipelineError("Hodge generation changed while acquiring lock")
        if outside_dependencies(root, promoted, complete=complete) != record["external_dependencies"]:
            raise PipelineError("Hodge external evidence changed while acquiring lock")
        operation = root / "library/.sidecar-operations" / ("h204-" + uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in ("incoming", "previous", "failed-new"))
        journal_path = operation / "operation.json"
        journal: dict[str, object] = {"contract": "ocd-hodge-vol2-work-swap-operation-v1", "work_id": route.WORK_ID,
            "manifest": manifest.resolve().as_posix(), "before": record["before"], "after": record["after"],
            "phase": "created", "updated_at": now()}
        _write_json_durable(journal_path, journal)
        moved = live = False
        try:
            copy_tree(source, incoming)
            if _files(incoming) != record["after"] or _files(target) != record["before"]:
                raise PipelineError("Hodge incoming generation differs")
            journal["phase"], journal["updated_at"] = "prepared", now()
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-copy")
            if outside_dependencies(root, promoted, complete=complete) != record["external_dependencies"]:
                raise PipelineError("Hodge external evidence changed during copy")
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            journal["phase"], journal["updated_at"] = "previous-moved", now()
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-old-rename")
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            journal["phase"], journal["updated_at"] = "new-live", now()
            _write_json_durable(journal_path, journal)
            if fail_at:
                fail_at("after-new-rename")
            if _files(target) != record["after"]:
                raise PipelineError("Hodge installed generation differs")
            _validate_acceptance_for_work(_io_path(target / ACCEPTANCE_REL), root=_io_path(root), work_id=route.WORK_ID)
            validate_state(_io_path(target / "state.json"), root=_io_path(root))
            if fail_at:
                fail_at("after-validation")
            journal["phase"], journal["updated_at"] = "complete", now()
            _write_json_durable(journal_path, journal)
            return {"status": "installed-and-validated", "operation": operation.as_posix(),
                "before_count": len(record["before"]), "after_count": len(record["after"]),
                "master_sha256": record["after"][MASTER_REL.as_posix()], "acceptance_sha256": record["after"][ACCEPTANCE_REL.as_posix()]}
        except BaseException:
            try:
                if live:
                    if _files(target) != record["after"]:
                        raise PipelineError("Hodge live generation changed after swap")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != record["before"]:
                        raise PipelineError("Hodge previous generation differs before rollback")
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != record["before"]:
                        raise PipelineError("Hodge rollback restored unexpected bytes")
                journal["phase"], journal["updated_at"] = ("rolled-back" if moved else "failed-before-swap"), now()
                _write_json_durable(journal_path, journal)
            except BaseException as rollback_error:
                journal["phase"], journal["rollback_error"], journal["updated_at"] = "recovery-required", str(rollback_error), now()
                _write_json_durable(journal_path, journal)
                raise PipelineError(f"Hodge rollback needs recovery: {operation}") from rollback_error
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=route.ROOT)
    parser.add_argument("--pending", type=Path, default=Path("C:/Scratch/h204b"))
    parser.add_argument("--promoted", type=Path, default=Path("C:/Scratch/h204p"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--complete-volume", action="store_true", help="Prepare only the frozen five-root Volume II replacement")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.prepare and args.apply:
        parser.error("--prepare and --apply are mutually exclusive")
    if args.complete_volume and not args.prepare:
        parser.error("--complete-volume is only used with --prepare")
    if args.prepare:
        result = (prepare_complete if args.complete_volume else prepare_manifest)(args.root, args.pending, args.promoted, args.manifest)
    elif args.apply:
        result = install(args.manifest)
    else:
        record, _root, _promoted = preflight(args.manifest)
        result = {"status": "ready", "changed_paths": len(record["changed_paths"]), "before_count": len(record["before"]), "after_count": len(record["after"])}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
