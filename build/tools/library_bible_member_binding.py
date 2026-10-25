"""Bind extracted Bible text members to their acquired package and source claim."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, load_json, sha256_file
from ocd_kernel.tei.install_accepted import _io_path


def bind_bible_members(
    root: Path, row: dict[str, Any], work: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    """Verify a complete extracted member inventory without treating ZIP as text."""
    wid = work["work_id"]
    ref = row.get("bible_member_evidence")
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise PipelineError(f"{wid} requires exact Bible member evidence")
    report_path = resolve_repo_path(root, ref["path"])
    if not report_path.is_file() or sha256_file(report_path) != ref["sha256"]:
        raise PipelineError(f"{wid} Bible member evidence missing or changed")
    report = load_json(report_path)
    if report.get("contract") != "ocd-bible-member-evidence-v1":
        raise PipelineError(f"{wid} Bible member evidence contract differs")
    entries = report.get("entries")
    if not isinstance(entries, list):
        raise PipelineError("Bible member evidence entries missing")
    matching = [entry for entry in entries if entry.get("work_id") == wid]
    if len(matching) != 1:
        raise PipelineError(f"{wid} Bible member evidence identity missing or repeated")
    entry = matching[0]
    for field in ("work", "state"):
        declared = row.get(field)
        if entry.get(field) != declared or not isinstance(declared, dict):
            raise PipelineError(f"{wid} {field} reference differs from evidence")
        path = resolve_repo_path(root, declared["path"])
        if not path.is_file() or sha256_file(path) != declared["sha256"]:
            raise PipelineError(f"{wid} {field} bytes changed")
    if entry.get("config") is not None:
        if row.get("config") != entry["config"]:
            raise PipelineError(f"{wid} config reference differs from evidence")
        config_path = resolve_repo_path(root, row["config"]["path"])
        if not config_path.is_file() or sha256_file(config_path) != row["config"]["sha256"]:
            raise PipelineError(f"{wid} config bytes changed")
        config = load_json(config_path)
        if config.get("resource_id") != wid or entry.get("source_root") != config.get("source_root"):
            raise PipelineError(f"{wid} config source identity differs")
    elif "config" in row or wid != "world-english-bible-classic":
        raise PipelineError(f"{wid} unexpected absent config")
    if row.get("url") != entry.get("source_url") or row.get("warnings") != entry.get("warnings"):
        raise PipelineError(f"{wid} URL or warnings differ from evidence")
    if row.get("primary_sources") != entry.get("textual_members"):
        raise PipelineError(f"{wid} textual member list differs from evidence")
    if row.get("source_scope") != entry.get("source_scope") or row.get("edition_title") != entry.get("edition_title"):
        raise PipelineError(f"{wid} scope or edition differs from evidence")
    package = entry.get("package")
    if not isinstance(package, dict) or set(package) != {"path", "bytes", "sha256"}:
        raise PipelineError(f"{wid} package evidence invalid")
    package_path = resolve_repo_path(root, package["path"])
    if (PurePosixPath(package["path"]).suffix.lower() != ".zip"
            or not package_path.is_file() or package_path.stat().st_size != package["bytes"]
            or sha256_file(package_path) != package["sha256"]):
        raise PipelineError(f"{wid} package differs from retained bytes")
    members = entry.get("textual_members", []) + entry.get("support_members", [])
    if not isinstance(members, list) or len(members) < 2:
        raise PipelineError(f"{wid} member evidence incomplete")
    seen_paths: set[str] = set()
    seen_names: set[str] = set()
    for member in members:
        if (not isinstance(member, dict)
                or set(member) != {"path", "archive_member", "bytes", "sha256", "media_type"}
                or member["path"] in seen_paths or member["archive_member"] in seen_names
                or not member["path"].startswith(entry["source_root"].rstrip("/") + "/")):
            raise PipelineError(f"{wid} member identity repeated or outside source root")
        seen_paths.add(member["path"])
        seen_names.add(member["archive_member"])
    source_root = resolve_repo_path(root, entry["source_root"])
    actual_paths = {
        entry["source_root"].rstrip("/") + "/" + path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*") if path.is_file()
    }
    if actual_paths != seen_paths:
        raise PipelineError(f"{wid} extracted member tree differs from complete evidence inventory")
    try:
        with zipfile.ZipFile(_io_path(package_path)) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            archive_names = [info.filename for info in infos]
            if (len(archive_names) != len(set(archive_names))
                    or any(name.startswith("/") or "\\" in name or ":" in name
                           or any(part in {"", ".", ".."} for part in PurePosixPath(name).parts)
                           for name in archive_names)
                    or sorted(archive_names) != sorted(entry.get("archive_members", []))
                    or not seen_names.issubset(archive_names)):
                raise PipelineError(f"{wid} package member inventory differs or is unsafe")
            for member in members:
                digest = hashlib.sha256()
                size = 0
                with archive.open(member["archive_member"]) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        size += len(chunk)
                        digest.update(chunk)
                path = resolve_repo_path(root, member["path"])
                if (size != member["bytes"] or digest.hexdigest() != member["sha256"]
                        or not path.is_file() or path.stat().st_size != size
                        or sha256_file(path) != member["sha256"]):
                    raise PipelineError(f"{wid} extracted member differs from package: {member['path']}")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise PipelineError(f"{wid} cannot verify retained ZIP members: {exc}") from exc
    receipt = entry.get("acquisition_receipt")
    evidence = [ref["path"], package["path"]]
    if entry.get("config") is not None:
        evidence.append(row["config"]["path"])
    if receipt is not None:
        receipt_path = resolve_repo_path(root, receipt["path"])
        if (not receipt_path.is_file() or sha256_file(receipt_path) != receipt["sha256"]
                or load_json(receipt_path).get("source_url") != row["url"]):
            raise PipelineError(f"{wid} source receipt differs")
        evidence.append(receipt["path"])
    evidence.extend(member["path"] for member in members)
    retained = [
        {"path": member["path"], "bytes": member["bytes"],
         "sha256": member["sha256"], "media_type": member["media_type"],
         "scope": f"Extracted textual member of {entry['source_scope']}"}
        for member in entry["textual_members"]
    ]
    return retained, {"source_kind": "retained-member-set", "source_scope": entry["source_scope"]}, evidence, [ref["path"]]
