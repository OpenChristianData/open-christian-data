"""Stage and atomically apply Brenton's ordered source-member rebind.

The retained USFM members already have exact byte bindings.  This writer only
reorders the acquisition ``retained_files`` by the numeric source filename
prefix, refreshes their one-based positions, and regenerates the dependent
source-member-set with the maintained kernel writer.  Staging is read-only;
apply is guarded by complete before/after work-tree hashes and rolls back a
failed directory swap.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import uuid
from collections.abc import Callable
from typing import Any

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import (
    PipelineError,
    canonical_bytes,
    io_path,
    load_json,
    sha256_file,
    write_json,
)
from ocd_kernel.library.acquisitions import (
    source_member_set_bytes,
    validate_acquisition,
)
from ocd_kernel.library.identities import load_work, validate_record
from ocd_kernel.library.state import validate_state


CONTRACT = "ocd-brenton-source-member-rebind-stage-v1"
WRITER_IDENTITY = "ocd-brenton-source-member-rebind-v1"
WORK_ID = "brenton-septuagint"
FORM_ID = "brenton-septuagint-retained-en"
EDITION_ID = "brenton-septuagint-electronic"
ACQUISITION_ID = "brenton-septuagint-acquired"
WORK_REL = Path("library/works") / WORK_ID
EDITION_REL = WORK_REL / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION_REL = EDITION_REL / "acquisitions" / f"{ACQUISITION_ID}.json"
MEMBER_SET_REL = EDITION_REL / "source-member-set.json"
SOURCE_PREFIX = (
    "raw/clean-ready-acquisition-to-tei/master-3/21/"
    "brenton-septuagint/source/usfm/"
)
MEMBER_NAME = re.compile(r"^(?P<number>[0-9]+)-(?P<id>[0-9A-Z]+)eng-Brenton[.]usfm$")
EXPECTED_PREIMAGES = {
    ACQUISITION_REL.as_posix(): "4e0e6f859cb0d3200f0fd5749632f5b5f1b378d81aff23b4916e1d25a22d27a8",
    MEMBER_SET_REL.as_posix(): "c4534255dd47532077fa480651cd981931bef7ac55f9b5911d5ee667019815b5",
}


def _tree(directory: Path) -> dict[str, str]:
    directory = io_path(directory)
    if not directory.is_dir():
        raise PipelineError(f"Brenton work generation is missing: {directory}")
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    }


def _sha_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _member_order(item: dict[str, Any]) -> tuple[int, str]:
    path = item.get("path")
    if not isinstance(path, str) or not path.startswith(SOURCE_PREFIX):
        raise PipelineError(f"Brenton retained member is outside the exact USFM root: {path!r}")
    name = PurePosixPath(path).name
    match = MEMBER_NAME.fullmatch(name)
    if match is None:
        raise PipelineError(f"Brenton retained member lacks a numeric source prefix: {path}")
    return int(match.group("number")), name


def _source_id(root: Path, item: dict[str, Any]) -> str:
    path = resolve_repo_path(root, item["path"])
    content = io_path(path).read_bytes()
    if len(content) != item.get("bytes") or _sha_bytes(content) != item.get("sha256"):
        raise PipelineError(f"Brenton retained member changed: {item['path']}")
    try:
        first = content.decode("utf-8").split("\n", 1)[0]
    except UnicodeDecodeError as exc:
        raise PipelineError(f"Brenton retained member is not UTF-8: {item['path']}") from exc
    if not first.startswith("\\id "):
        raise PipelineError(f"Brenton retained member lacks an opening USFM id: {item['path']}")
    source_id = first[4:].split(maxsplit=1)[0]
    match = MEMBER_NAME.fullmatch(PurePosixPath(item["path"]).name)
    if match is None or source_id != match.group("id"):
        raise PipelineError(f"Brenton filename and USFM id differ: {item['path']}")
    return source_id


def _proposal(
    root: Path,
    *,
    expected_preimages: dict[str, str] | None = EXPECTED_PREIMAGES,
) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    work_root = root / WORK_REL
    acquisition_path = root / ACQUISITION_REL
    before_tree = _tree(work_root)
    if expected_preimages is not None:
        actual = {
            relative: sha256_file(root / relative)
            for relative in expected_preimages
        }
        if actual != expected_preimages:
            raise PipelineError(f"Brenton source-member preimages differ: {actual}")

    work = load_work(work_root / "work.json")
    state = validate_state(work_root / "state.json", root=root)
    acquisition = validate_acquisition(acquisition_path, root=root)
    if (
        work.get("work_id") != WORK_ID
        or state.get("work_id") != WORK_ID
        or acquisition.get("acquisition_id") != ACQUISITION_ID
        or acquisition.get("edition_id") != EDITION_ID
        or acquisition.get("source_kind") != "retained-member-set"
        or acquisition.get("source_path") != MEMBER_SET_REL.as_posix()
    ):
        raise PipelineError("Brenton work/acquisition identity differs")
    retained = acquisition.get("retained_files")
    if not isinstance(retained, list) or len(retained) != 60:
        raise PipelineError("Brenton acquisition must bind exactly 60 USFM members")
    numbers = [_member_order(item)[0] for item in retained]
    if len(set(numbers)) != 60:
        raise PipelineError("Brenton numeric source prefixes are not unique")
    source_ids = [_source_id(root, item) for item in retained]
    if len(set(source_ids)) != 60:
        raise PipelineError("Brenton USFM source ids are not unique")

    ordered = sorted(copy.deepcopy(retained), key=_member_order)
    proposed = copy.deepcopy(acquisition)
    proposed["retained_files"] = ordered
    member_set = source_member_set_bytes(proposed)
    proposed["source_bytes"] = len(member_set)
    proposed["source_sha256"] = _sha_bytes(member_set)
    validate_record("acquisition", proposed, context="proposed Brenton source-member rebind")

    acquisition_bytes = canonical_bytes(proposed)
    proposed_tree = dict(before_tree)
    acquisition_inside = ACQUISITION_REL.relative_to(WORK_REL).as_posix()
    member_set_inside = MEMBER_SET_REL.relative_to(WORK_REL).as_posix()
    proposed_tree[acquisition_inside] = _sha_bytes(acquisition_bytes)
    proposed_tree[member_set_inside] = _sha_bytes(member_set)
    if {path for path in proposed_tree if before_tree.get(path) != proposed_tree.get(path)} != {
        acquisition_inside,
        member_set_inside,
    }:
        raise PipelineError("Brenton proposal changes paths outside the acquisition/member-set pair")
    return {
        "root": root,
        "before_tree": before_tree,
        "after_tree": proposed_tree,
        "acquisition": proposed,
        "acquisition_bytes": acquisition_bytes,
        "member_set_bytes": member_set,
        "member_ids": [_source_id(root, item) for item in ordered],
        "numeric_prefixes": [_member_order(item)[0] for item in ordered],
    }


def _manifest(proposal: dict[str, Any]) -> dict[str, Any]:
    before = proposal["before_tree"]
    after = proposal["after_tree"]
    return {
        "contract": CONTRACT,
        "writer": {
            "identity": WRITER_IDENTITY,
            "implementation": "build/tools/rebind_brenton_source_members.py",
            "generated_member_set_writer": {
                "module": "ocd_kernel.library.acquisitions",
                "callable": "source_member_set_bytes",
                "contract": "ocd-retained-source-member-set-v1",
            },
        },
        "authority": (
            "Brenton-only source-accounting repair. No source bytes, work identity, "
            "state, acceptance, rights, master, projection, or publication change."
        ),
        "work_id": WORK_ID,
        "identity": {
            "textual_form_id": FORM_ID,
            "edition_id": EDITION_ID,
            "acquisition_id": ACQUISITION_ID,
        },
        "ordering_rule": "ascending integer filename prefix; one-based position",
        "member_count": 60,
        "member_ids": proposal["member_ids"],
        "numeric_prefixes": proposal["numeric_prefixes"],
        "before": before,
        "after": after,
        "changed_paths": [ACQUISITION_REL.as_posix(), MEMBER_SET_REL.as_posix()],
        "files": [
            {
                "path": ACQUISITION_REL.as_posix(),
                "before_sha256": before[ACQUISITION_REL.relative_to(WORK_REL).as_posix()],
                "proposed_sha256": after[ACQUISITION_REL.relative_to(WORK_REL).as_posix()],
            },
            {
                "path": MEMBER_SET_REL.as_posix(),
                "before_sha256": before[MEMBER_SET_REL.relative_to(WORK_REL).as_posix()],
                "proposed_sha256": after[MEMBER_SET_REL.relative_to(WORK_REL).as_posix()],
            },
        ],
    }


def stage(root: Path, destination: Path) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    destination = Path(destination).resolve()
    if destination.exists():
        raise PipelineError(f"Brenton rebind stage must be fresh: {destination}")
    if destination == root or root in destination.parents:
        raise PipelineError("Brenton rebind stage must be outside the repository")
    proposal = _proposal(root)
    manifest = _manifest(proposal)
    staged_work = destination / WORK_REL
    shutil.copytree(io_path(root / WORK_REL), io_path(staged_work))
    io_path(destination / ACQUISITION_REL).write_bytes(proposal["acquisition_bytes"])
    io_path(destination / MEMBER_SET_REL).write_bytes(proposal["member_set_bytes"])
    if _tree(staged_work) != proposal["after_tree"]:
        raise PipelineError("Brenton staged work generation differs")
    write_json(io_path(destination / "manifest.json"), manifest)
    return manifest


def preflight(root: Path, destination: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(root).resolve(strict=True)
    destination = Path(destination).resolve(strict=True)
    proposal = _proposal(root)
    manifest = load_json(io_path(destination / "manifest.json"))
    if manifest != _manifest(proposal):
        raise PipelineError("Brenton stage manifest is stale or differs")
    if _tree(destination / WORK_REL) != proposal["after_tree"]:
        raise PipelineError("Brenton staged generation is stale or differs")
    if io_path(destination / ACQUISITION_REL).read_bytes() != proposal["acquisition_bytes"]:
        raise PipelineError("Brenton staged acquisition bytes differ")
    if io_path(destination / MEMBER_SET_REL).read_bytes() != proposal["member_set_bytes"]:
        raise PipelineError("Brenton staged member-set bytes differ")
    return manifest, proposal


def apply_staged(
    root: Path,
    destination: Path,
    *,
    fail_at: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve(strict=True)
    destination = Path(destination).resolve(strict=True)
    if io_path(destination / "apply-receipt.json").exists():
        raise PipelineError("Brenton rebind stage already has an apply receipt")
    manifest, proposal = preflight(root, destination)
    target = root / WORK_REL
    operations = root / "library/.sidecar-operations"
    io_path(operations).mkdir(parents=True, exist_ok=True)
    operation = operations / ("brenton-source-rebind-" + uuid.uuid4().hex[:16])
    io_path(operation).mkdir(parents=True, exist_ok=False)
    incoming, previous, failed_new = (
        operation / name for name in ("incoming", "previous", "failed-new")
    )
    journal_path = operation / "operation.json"
    journal: dict[str, Any] = {
        "contract": "ocd-brenton-source-member-rebind-operation-v1",
        "writer_identity": WRITER_IDENTITY,
        "manifest_sha256": sha256_file(destination / "manifest.json"),
        "phase": "created",
        "before": proposal["before_tree"],
        "after": proposal["after_tree"],
    }
    write_json(io_path(journal_path), journal)
    moved = False
    live = False
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        try:
            if _tree(target) != proposal["before_tree"]:
                raise PipelineError("Brenton canonical work changed before apply")
            shutil.copytree(io_path(destination / WORK_REL), io_path(incoming))
            if _tree(incoming) != proposal["after_tree"] or _tree(target) != proposal["before_tree"]:
                raise PipelineError("Brenton incoming or canonical generation differs")
            journal["phase"] = "prepared"
            write_json(io_path(journal_path), journal)
            if fail_at:
                fail_at("after-copy")
            os.replace(io_path(target), io_path(previous))
            moved = True
            journal["phase"] = "previous-moved"
            write_json(io_path(journal_path), journal)
            if fail_at:
                fail_at("after-old-rename")
            os.replace(io_path(incoming), io_path(target))
            live = True
            journal["phase"] = "new-live"
            write_json(io_path(journal_path), journal)
            if fail_at:
                fail_at("after-new-rename")
            if _tree(target) != proposal["after_tree"]:
                raise PipelineError("Brenton installed work generation differs")
            validate_acquisition(io_path(root / ACQUISITION_REL), root=io_path(root))
            validate_state(io_path(target / "state.json"), root=io_path(root))
            if fail_at:
                fail_at("after-validation")
            journal["phase"] = "complete"
            write_json(io_path(journal_path), journal)
        except BaseException:
            try:
                if live:
                    if _tree(target) != proposal["after_tree"]:
                        raise PipelineError("Brenton live generation changed before rollback")
                    os.replace(io_path(target), io_path(failed_new))
                if moved:
                    if io_path(target).exists() or _tree(previous) != proposal["before_tree"]:
                        raise PipelineError("Brenton rollback preimage differs")
                    os.replace(io_path(previous), io_path(target))
                    if _tree(target) != proposal["before_tree"]:
                        raise PipelineError("Brenton rollback restored unexpected bytes")
                journal["phase"] = "rolled-back" if moved else "failed-before-swap"
                write_json(io_path(journal_path), journal)
            except BaseException as rollback_error:
                journal["phase"] = "recovery-required"
                journal["rollback_error"] = str(rollback_error)
                write_json(io_path(journal_path), journal)
                raise PipelineError(
                    f"Brenton source rebind rollback needs recovery: {operation}"
                ) from rollback_error
            raise
    result = {
        "contract": "ocd-brenton-source-member-rebind-apply-v1",
        "status": "installed-and-validated",
        "writer_identity": WRITER_IDENTITY,
        "manifest_sha256": sha256_file(destination / "manifest.json"),
        "operation": operation.as_posix(),
        "files": manifest["files"],
        "member_count": 60,
        "numeric_prefixes": proposal["numeric_prefixes"],
    }
    write_json(io_path(destination / "apply-receipt.json"), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.apply:
            result = apply_staged(args.repository_root, args.destination)
        else:
            result = stage(args.repository_root, args.destination)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Brenton source-member rebind failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
