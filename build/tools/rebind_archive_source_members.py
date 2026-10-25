"""Stage and guardedly rebind ZIP-led acquisitions to their extracted text source.

This repairs source identity only. The original ZIP and every extracted member
remain in retained_files, while work, state, edition, and acceptance records stay
unchanged. Staging never changes canonical sidecars.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import uuid
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import (
    PipelineError, canonical_bytes, ensure_relative_path, io_glob, io_path, load_json,
    require_string, safe_identifier, sha256_file, write_json,
)
from ocd_kernel.library.acquisitions import load_acquisition, validate_acquisition
from ocd_kernel.library.identities import validate_record
from ocd_kernel.library.state import validate_state

CONTRACT = "ocd-archive-source-rebind-stage-v1"
EXPECTED_FAMILIES = {"openmgh": 303, "gutenberg": 8}
TEXT_SUFFIXES = {".xml", ".html", ".htm", ".txt"}
OPENMGH_PREFIX = "Complete acquired containing-source package and its extracted TEI member; "
GUTENBERG_END = " and support images. "


def _load_legacy_zip_acquisition(path: Path) -> dict[str, Any]:
    """Read a schema-valid ZIP-led migration preimage without relaxing current readers."""

    record = load_json(path)
    validate_record("acquisition", record, context=str(path))
    safe_identifier(
        require_string(record, "acquisition_id", context=str(path)), field="acquisition_id"
    )
    safe_identifier(
        require_string(record, "edition_id", context=str(path)), field="edition_id"
    )
    retained = record["retained_files"]
    if not isinstance(retained, list) or not retained:
        raise PipelineError(f"{path} requires non-empty retained_files")
    seen: set[str] = set()
    for item in retained:
        if not isinstance(item, dict):
            raise PipelineError(f"{path} retained_files entries must be objects")
        rel = require_string(item, "path", context=str(path))
        ensure_relative_path(rel, field=f"retained_files.path in {path}")
        if rel in seen:
            raise PipelineError(f"duplicate retained file in {path}: {rel}")
        seen.add(rel)
        digest = require_string(item, "sha256", context=str(path))
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise PipelineError(f"invalid retained file sha256 in {path}: {rel}")
        size = item.get("bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise PipelineError(f"retained file bytes must be non-negative integer in {path}: {rel}")
        require_string(item, "media_type", context=str(path))

    source_path = record.get("source_path")
    if source_path is not None:
        source_path = require_string(record, "source_path", context=str(path))
        ensure_relative_path(source_path, field=f"source_path in {path}")
        if not source_path.endswith(".zip"):
            raise PipelineError(f"legacy migration requires an exact ZIP source path: {path}")
        source_size = record.get("source_bytes")
        if not isinstance(source_size, int) or isinstance(source_size, bool) or source_size < 0:
            raise PipelineError(f"source_bytes must be a non-negative integer in {path}")
    return record


def _checked_file(root: Path, item: dict[str, Any], label: str) -> Path:
    if not isinstance(item, dict) or not {"path", "bytes", "sha256"} <= set(item):
        raise PipelineError(f"{label} lacks exact path, bytes, and sha256")
    path = resolve_repo_path(root, item["path"])
    if (not io_path(path).is_file() or io_path(path).stat().st_size != item["bytes"]
            or sha256_file(path) != item["sha256"]):
        raise PipelineError(f"{label} missing or changed: {item['path']}")
    return path


def _archive_members(root: Path, package: dict[str, Any],
                     cache: dict[str, dict[str, tuple[int, str]]]) -> dict[str, tuple[int, str]]:
    rel = package["path"]
    if rel in cache:
        return cache[rel]
    path = _checked_file(root, package, "retained ZIP")
    members: dict[str, tuple[int, str]] = {}
    try:
        with zipfile.ZipFile(io_path(path)) as archive:
            for item in archive.infolist():
                name = item.filename
                parts = PurePosixPath(name).parts
                if (not name or name.startswith("/") or chr(92) in name or ":" in name
                        or any(part in {"", ".", ".."} for part in parts)
                        or PurePosixPath(name).as_posix() != name):
                    raise PipelineError(f"unsafe ZIP member: {rel}#{name}")
                if item.is_dir():
                    continue
                if name in members:
                    raise PipelineError(f"duplicate ZIP member: {rel}#{name}")
                digest = hashlib.sha256()
                count = 0
                with archive.open(item) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        count += len(chunk)
                        digest.update(chunk)
                members[name] = (count, digest.hexdigest())
            if archive.testzip() is not None:
                raise PipelineError(f"ZIP CRC failed: {rel}")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise PipelineError(f"cannot inspect ZIP {rel}: {exc}") from exc
    cache[rel] = members
    return members


def _state_and_edition(root: Path, sidecar: Path, record: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    rel = sidecar.relative_to(root).as_posix()
    work_id = sidecar.parts[sidecar.parts.index("works") + 1]
    work_path = root / "library/works" / work_id / "work.json"
    state_path = root / "library/works" / work_id / "state.json"
    work = load_json(work_path)
    state = load_json(state_path)
    if work.get("work_id") != work_id or state.get("work_id") != work_id:
        raise PipelineError(f"work/state identity differs for {rel}")
    editions = [edition for form in work.get("textual_forms", []) for edition in form.get("editions", [])
                if edition.get("edition_id") == record["edition_id"]
                and record["acquisition_id"] in edition.get("acquisition_ids", [])]
    if len(editions) != 1:
        raise PipelineError(f"acquisition lacks one work edition: {rel}")
    for target_id, target_type in ((record["acquisition_id"], "acquisition"), (record["edition_id"], "edition")):
        targets = [item for item in state.get("targets", [])
                   if item.get("target_id") == target_id and item.get("target_type") == target_type]
        if len(targets) != 1 or rel not in targets[0].get("evidence", []):
            raise PipelineError(f"state target/evidence differs for {rel}: {target_id}")
    return work_id, sha256_file(work_path), sha256_file(state_path), editions[0]


def _proposal(root: Path, sidecar: Path, cache: dict[str, dict[str, tuple[int, str]]]) -> dict[str, Any]:
    record = _load_legacy_zip_acquisition(sidecar)
    rel = sidecar.relative_to(root).as_posix()
    package_rel = record.get("source_path")
    if not isinstance(package_rel, str) or not package_rel.endswith(".zip"):
        raise PipelineError(f"not a ZIP-bound source: {rel}")
    parts = PurePosixPath(package_rel).parts
    if len(parts) != 4 or parts[0] != "raw" or parts[1] not in EXPECTED_FAMILIES:
        raise PipelineError(f"unsupported ZIP source family: {rel}")
    family, source_id = parts[1], parts[2]
    retained = record["retained_files"]
    packages = [item for item in retained if item["path"] == package_rel]
    if len(packages) != 1:
        raise PipelineError(f"ZIP must be retained exactly once: {rel}")
    package = packages[0]
    if any(record.get(field) != package[key] for field, key in
           (("source_bytes", "bytes"), ("source_sha256", "sha256"))):
        raise PipelineError(f"existing source binding differs from retained ZIP: {rel}")
    members = _archive_members(root, package, cache)
    expected_prefix = (f"raw/openmgh/{source_id}/tei/" if family == "openmgh"
                       else f"raw/gutenberg/{source_id}/html/")
    expected_paths = {expected_prefix + name for name in members}
    extracted = [item for item in retained if item["path"] != package_rel]
    if {item["path"] for item in extracted} != expected_paths or len(extracted) != len(members):
        raise PipelineError(f"retained extracted member inventory differs from ZIP: {rel}")
    for item in extracted:
        name = item["path"][len(expected_prefix):]
        if members[name] != (item["bytes"], item["sha256"]):
            raise PipelineError(f"retained extracted member differs from ZIP: {rel}#{name}")
        _checked_file(root, item, "extracted source member")
    text = [item for item in extracted if PurePosixPath(item["path"]).suffix.lower() in TEXT_SUFFIXES]
    archive_text = [name for name in members if PurePosixPath(name).suffix.lower() in TEXT_SUFFIXES]
    if len(text) != 1 or len(archive_text) != 1 or text[0]["path"] != expected_prefix + archive_text[0]:
        raise PipelineError(f"source text member is absent or ambiguous: {rel}")
    member = archive_text[0]
    work_id, work_sha, state_sha, edition = _state_and_edition(root, sidecar, record)
    receipt_rel = f"raw/{family}/{source_id}/acquisition-receipt.json"
    receipt_path = resolve_repo_path(root, receipt_rel)
    if not io_path(receipt_path).is_file():
        raise PipelineError(f"source receipt missing: {receipt_rel}")
    receipt = load_json(receipt_path)
    if (receipt.get("schema") != "ocd-acquisition-source-receipt-v1"
            or receipt.get("package") != {key: package[key] for key in ("path", "bytes", "sha256")}):
        raise PipelineError(f"receipt package binding differs: {receipt_rel}")
    verification = receipt.get("verification")
    if not isinstance(verification, dict):
        raise PipelineError(f"receipt verification missing: {receipt_rel}")
    member_count = verification.get("member_count")
    if member_count is None and isinstance(verification.get("member_hash_inventory"), dict):
        member_count = verification["member_hash_inventory"].get("count")
    if member_count != len(members):
        raise PipelineError(f"receipt ZIP member count differs: {receipt_rel}")
    old_scope = record.get("source_scope")
    if not isinstance(old_scope, str):
        raise PipelineError(f"existing source scope missing: {rel}")
    if family == "openmgh":
        if (receipt.get("source_id") != source_id or package_rel != f"raw/openmgh/{source_id}/{source_id}.zip"
                or member != f"{source_id}.xml" or receipt.get("source_url") != record["url"]
                or not old_scope.startswith(OPENMGH_PREFIX)):
            raise PipelineError(f"openMGH source/receipt identity differs: {rel}")
        containing = edition.get("containing_source")
        if (not isinstance(containing, dict) or containing.get("title") != receipt.get("work_edition")
                or not isinstance(containing.get("locator"), str)
                or not old_scope[len(OPENMGH_PREFIX):].startswith(
                    f"existing work association locators: {containing['locator']}. ")):
            raise PipelineError(f"openMGH existing work locators differ: {rel}")
        tail = old_scope[len(OPENMGH_PREFIX):]
        scope = (f"Extracted TEI XML {text[0]['path']} is the retained text source; "
                 f"ZIP {package_rel} is the acquisition package. {tail}")
    else:
        if (receipt.get("ebook_id") != source_id or package_rel != f"raw/gutenberg/{source_id}/pg{source_id}-h.zip"
                or receipt.get("package_url") != record["url"]
                or receipt.get("source_url") != f"https://www.gutenberg.org/ebooks/{source_id}"
                or receipt.get("html") != {key: text[0][key] for key in ("path", "bytes", "sha256")}
                or record.get("warnings") != [receipt.get("rights")]
                or verification.get("primary_html", member) != member):
            raise PipelineError(f"Gutenberg source/receipt identity differs: {rel}")
        old_prefix = (f"Complete original Project Gutenberg ZIP {package_rel} and all {len(members)} "
                      f"exactly matching extracted archive members under {expected_prefix}, "
                      f"including principal HTML {text[0]['path']}{GUTENBERG_END}")
        if not old_scope.startswith(old_prefix):
            raise PipelineError(f"Gutenberg package-led scope differs: {rel}")
        tail = old_scope[len(old_prefix):]
        scope = (f"Principal extracted HTML {text[0]['path']} is the retained text source; "
                 f"ZIP {package_rel} is the acquisition package, with other extracted members retained "
                 f"as support files. {tail}")
    proposed = copy.deepcopy(record)
    proposed.update(source_path=text[0]["path"], source_bytes=text[0]["bytes"],
                    source_sha256=text[0]["sha256"], source_scope=scope)
    proposed_text = [item for item in proposed["retained_files"] if item["path"] == text[0]["path"]]
    if len(proposed_text) != 1:
        raise PipelineError(f"proposed source member is absent or ambiguous: {rel}")
    proposed_text[0]["scope"] = scope
    validate_record("acquisition", proposed, context=f"proposed rebind {rel}")
    before = sha256_file(sidecar)
    after = hashlib.sha256(canonical_bytes(proposed)).hexdigest()
    return {"path": rel, "work_id": work_id, "family": family,
            "work_sha256": work_sha, "state_sha256": state_sha,
            "receipt": {"path": receipt_rel, "sha256": sha256_file(receipt_path)},
            "before_sha256": before, "after_sha256": after,
            "package_path": package_rel, "package_sha256": package["sha256"],
            "source_path": text[0]["path"], "source_sha256": text[0]["sha256"],
            "archive_member": member, "proposed": proposed}


def prepare(root: Path, *, expected_families: dict[str, int] | None = None) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    expected = EXPECTED_FAMILIES if expected_families is None else expected_families
    paths = sorted(io_glob(root / "library/works", "*/forms/*/editions/*/acquisitions/*.json"),
                   key=lambda path: path.as_posix())
    zip_paths = [path for path in paths if str(load_json(path).get("source_path", "")).endswith(".zip")]
    cache: dict[str, dict[str, tuple[int, str]]] = {}
    proposals = [_proposal(root, path, cache) for path in zip_paths]
    actual = dict(Counter(item["family"] for item in proposals))
    if actual != expected:
        raise PipelineError(f"ZIP-source cohort differs: {actual} != {expected}")
    return proposals


def _manifest_entry(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "proposed"}


def stage(root: Path, destination: Path, *, expected_families: dict[str, int] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise PipelineError(f"stage destination already exists: {destination}")
    if destination == root or root in destination.parents:
        raise PipelineError("stage destination must be outside repository")
    proposals = prepare(root, expected_families=expected_families)
    manifest = {"contract": CONTRACT,
                "authority": "Proposed acquisition-only source rebind; no canonical, acceptance, rights, or publication change.",
                "expected_families": EXPECTED_FAMILIES if expected_families is None else expected_families,
                "entries": [_manifest_entry(item) for item in proposals]}
    io_path(destination).mkdir(parents=True)
    for item in proposals:
        staged = destination / item["path"]
        write_json(staged, item["proposed"])
        load_acquisition(staged)
        if sha256_file(staged) != item["after_sha256"]:
            raise PipelineError(f"staged acquisition hash differs: {item['path']}")
    write_json(destination / "manifest.json", manifest)
    return manifest


def _replace_bytes(target: Path, content: bytes) -> None:
    temporary = target.with_name(target.name + ".rebind-" + uuid.uuid4().hex + ".tmp")
    try:
        io_path(temporary).write_bytes(content)
        os.replace(io_path(temporary), io_path(target))
    finally:
        if io_path(temporary).exists():
            io_path(temporary).unlink()


def apply_staged(root: Path, destination: Path, *,
                 expected_families: dict[str, int] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    destination = Path(destination).resolve()
    if io_path(destination / "operation.json").exists() or io_path(destination / "apply-receipt.json").exists():
        raise PipelineError("stage has an existing apply operation")
    manifest = load_json(destination / "manifest.json")
    expected = EXPECTED_FAMILIES if expected_families is None else expected_families
    if manifest.get("contract") != CONTRACT or manifest.get("expected_families") != expected:
        raise PipelineError("stage manifest contract/cohort differs")
    proposals = prepare(root, expected_families=expected)
    if manifest.get("entries") != [_manifest_entry(item) for item in proposals]:
        raise PipelineError("stage manifest differs from current source-bound proposals")
    for item in proposals:
        rel = item["path"]
        if (sha256_file(root / rel) != item["before_sha256"]
                or sha256_file(destination / rel) != item["after_sha256"]
                or io_path(destination / rel).read_bytes() != canonical_bytes(item["proposed"])):
            raise PipelineError(f"stage/current sidecar changed: {rel}")
    operation = {"contract": "ocd-archive-source-rebind-operation-v1",
                 "manifest_sha256": sha256_file(destination / "manifest.json"),
                 "phase": "prepared", "completed": [], "inflight": None}
    write_json(destination / "operation.json", operation)
    completed: list[dict[str, Any]] = []
    try:
        for item in proposals:
            rel = item["path"]
            target = root / rel
            work_root = root / "library/works" / item["work_id"]
            with acquire_jsonl_lock(work_root, acquire_timeout=30.0):
                if (sha256_file(target) != item["before_sha256"]
                        or sha256_file(work_root / "work.json") != item["work_sha256"]
                        or sha256_file(work_root / "state.json") != item["state_sha256"]):
                    raise PipelineError(f"canonical sidecar/work/state changed during apply: {rel}")
                backup = destination / "rollback" / rel
                if io_path(backup).exists():
                    raise PipelineError(f"rollback backup already exists: {backup}")
                io_path(backup.parent).mkdir(parents=True, exist_ok=True)
                original = io_path(target).read_bytes()
                io_path(backup).write_bytes(original)
                if sha256_file(backup) != item["before_sha256"]:
                    raise PipelineError(f"rollback backup differs: {rel}")
                operation["phase"] = "applying"
                operation["inflight"] = rel
                write_json(destination / "operation.json", operation)
                completed.append(item)
                _replace_bytes(target, canonical_bytes(item["proposed"]))
                if sha256_file(target) != item["after_sha256"]:
                    raise PipelineError(f"installed acquisition hash differs: {rel}")
                validate_acquisition(io_path(target), root=io_path(root))
                validate_state(io_path(work_root / "state.json"), root=io_path(root))
                operation["completed"].append(rel)
                operation["inflight"] = None
                write_json(destination / "operation.json", operation)
        operation["phase"] = "complete"
        write_json(destination / "operation.json", operation)
    except Exception as original_error:
        failures = []
        for item in reversed(completed):
            rel = item["path"]
            target = root / rel
            backup = destination / "rollback" / rel
            work_root = root / "library/works" / item["work_id"]
            try:
                with acquire_jsonl_lock(work_root, acquire_timeout=30.0):
                    _replace_bytes(target, io_path(backup).read_bytes())
                    if sha256_file(target) != item["before_sha256"]:
                        raise PipelineError(f"rollback hash differs: {rel}")
            except Exception as rollback_error:
                failures.append(f"{rel}: {rollback_error}")
        operation["phase"] = "recovery-required" if failures else "rolled-back"
        operation["rollback_errors"] = failures
        write_json(destination / "operation.json", operation)
        if failures:
            raise PipelineError(f"rebind failed and rollback requires recovery: {failures}") from original_error
        raise
    result = {"contract": "ocd-archive-source-rebind-apply-v1",
              "manifest_sha256": operation["manifest_sha256"],
              "installed": [{"path": item["path"], "after_sha256": item["after_sha256"]}
                            for item in completed]}
    write_json(destination / "apply-receipt.json", result)
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
            print(json.dumps({"installed": len(result["installed"]), "receipt": str(args.destination / "apply-receipt.json")}, sort_keys=True))
        else:
            result = stage(args.repository_root, args.destination)
            print(json.dumps({"staged": len(result["entries"]), "manifest": str(args.destination / "manifest.json")}, sort_keys=True))
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"archive source rebind failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
