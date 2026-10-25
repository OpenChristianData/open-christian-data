"""Verify ordered retained source members against a separate acquired package."""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, load_json, sha256_file
from ocd_kernel.tei.install_accepted import _io_path


def bind_member_set(root: Path, row: dict[str, Any], work: dict[str, Any],
                    manifest: dict[str, Any], manifest_rel: str,
                    authorities: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Bind all primary members, with container/support evidenced separately."""
    wid = work["work_id"]
    ref = row.get("source_receipt")
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise PipelineError(f"{wid} member-set source receipt needs exact path/hash")
    receipt_rel = ref["path"]
    receipt_path = resolve_repo_path(root, receipt_rel)
    if not receipt_path.is_file() or sha256_file(receipt_path) != ref["sha256"]:
        raise PipelineError(f"{wid} member-set source receipt missing or changed")
    receipt = load_json(receipt_path)
    primary = [item for item in authorities if item.get("role") == "primary-source"]
    ordered = sorted(primary, key=lambda item: (item["path"], item["name"]))
    containers = [item for item in authorities if item.get("role") == "acquisition-container"]
    support = [item for item in authorities if item.get("role") == "source-description"
               and isinstance(item.get("path"), str) and item["path"].startswith("raw/")]
    if (len(primary) < 2 or len(containers) != 1 or not support
            or row.get("primary_sources") != ordered or "primary_source" in row
            or any(PurePosixPath(item["path"]).suffix.lower() == ".zip" for item in primary)):
        raise PipelineError(f"{wid} member-set primary authorities differ from exact ordered source members")
    package = containers[0]
    if (receipt.get("schema") != "ocd-member-set-acquisition-receipt-v1"
            or receipt.get("work_id") != wid or receipt.get("source_id") != manifest.get("source_id")
            or receipt.get("source_manifest") != row.get("source_manifest")
            or receipt.get("config") != row.get("config")
            or receipt.get("provider") != row.get("provider")
            or receipt.get("package_url") != row.get("url")
            or receipt.get("package") != package
            or receipt.get("members") != ordered
            or receipt.get("support") != support):
        raise PipelineError(f"{wid} member-set receipt differs from manifest, provider, or package URL")
    package_rel = package["path"]
    if PurePosixPath(package_rel).suffix.lower() != ".zip":
        raise PipelineError(f"{wid} member-set package must be ZIP")
    prefix = str(PurePosixPath(package_rel).parent / PurePosixPath(package_rel).stem) + "/"
    if any(not item["path"].startswith(prefix) for item in ordered + support):
        raise PipelineError(f"{wid} extracted member lies outside package directory")
    package_path = resolve_repo_path(root, package_rel)
    if (not package_path.is_file() or package_path.stat().st_size != package["bytes"]
            or sha256_file(package_path) != package["sha256"]):
        raise PipelineError(f"{wid} member-set package bytes/hash differ")
    expected = {item["path"][len(prefix):]: item for item in ordered + support}
    if len(expected) != len(ordered) + len(support):
        raise PipelineError(f"{wid} repeated ZIP member identity")
    try:
        with zipfile.ZipFile(_io_path(package_path)) as archive:
            names = [item.filename for item in archive.infolist() if not item.is_dir()]
            if len(names) != len(expected) or set(names) != set(expected):
                raise PipelineError(f"{wid} member-set ZIP inventory differs from receipt")
            for name in names:
                item = expected[name]
                digest = hashlib.sha256()
                size = 0
                with archive.open(name) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        size += len(chunk)
                        digest.update(chunk)
                extracted = resolve_repo_path(root, item["path"])
                if (size != item["bytes"] or digest.hexdigest() != item["sha256"]
                        or not extracted.is_file() or extracted.stat().st_size != size
                        or sha256_file(extracted) != digest.hexdigest()):
                    raise PipelineError(f"{wid} extracted source/support differs from ZIP: {name}")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise PipelineError(f"{wid} cannot verify member-set ZIP: {exc}") from exc
    module = receipt.get("sword_module")
    if not isinstance(module, dict) or len(support) != 1 or module.get("path") != support[0]["path"]:
        raise PipelineError(f"{wid} SWORD module description is not bound")
    try:
        lines = resolve_repo_path(root, support[0]["path"]).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise PipelineError(f"{wid} cannot read SWORD module config: {exc}") from exc
    fields = dict(line.split("=", 1) for line in lines if "=" in line)
    expected_module = {"path": support[0]["path"], "description": fields.get("Description"),
                       "version": fields.get("Version"), "language": fields.get("Lang"),
                       "distribution_license": fields.get("DistributionLicense"),
                       "sword_version_date": fields.get("SwordVersionDate")}
    if module != expected_module or any(not value for value in expected_module.values()):
        raise PipelineError(f"{wid} SWORD module metadata differs from retained config")
    edition_title = f"{module['description']} — CrossWire SWORD module v{module['version']}"
    warning = (f"Retained SWORD module declares DistributionLicense={module['distribution_license']}; "
               "independent rights clearance and publication authorization are not established.")
    if (row.get("edition_title") != edition_title or row.get("language") != module["language"]
            or row.get("warnings") != [warning] or row.get("media_type") != "application/octet-stream"):
        raise PipelineError(f"{wid} SWORD edition, language, media type, or rights warning differs")
    scope = row.get("source_scope")
    if (not isinstance(scope, str) or not scope.strip()
            or not all(item["path"] in scope for item in ordered)
            or package_rel not in scope or support[0]["path"] not in scope):
        raise PipelineError(f"{wid} member-set scope must distinguish source, package, and support")
    retained = [{"path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"],
                 "media_type": "application/octet-stream", "scope": scope} for item in ordered]
    evidence = [manifest_rel, row["config"]["path"], receipt_rel, package_rel]
    evidence.extend(item["path"] for item in ordered + support)
    return retained, {"source_kind": "retained-member-set", "source_scope": scope}, evidence
