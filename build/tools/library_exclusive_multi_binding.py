"""Bind one exclusive work to every primary member of a retained source tree.

This records an acquired electronic witness only. Manifest inventory order is
not asserted to be reading order or evidence of an accepted reconstruction.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from build.tools.library_exclusive_manifest_binding import _source_bindings
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file
from ocd_kernel.tei.install_accepted import _io_path


MEDIA_TYPES = {
    ".htm": "text/html", ".html": "text/html", ".xhtml": "application/xhtml+xml",
    ".xml": "application/xml", ".svg": "image/svg+xml",
    ".jpg": "image/jpeg", ".md": "text/markdown", ".css": "text/css",
    ".opf": "application/oebps-package+xml", "": "application/octet-stream",
}
NOTICE_ROLES = {"source-attribution-readme", "source-readme", "source-attribution", "source-attribution-deliverable", "rights-evidence"}


def _bound(root: Path, ref: Any, label: str) -> Path:
    if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
            or not isinstance(ref["path"], str) or not isinstance(ref["sha256"], str)):
        raise PipelineError(f"{label} requires an exact path and hash")
    path = resolve_repo_path(root, ref["path"])
    if not path.is_file() or sha256_file(_io_path(path)) != ref["sha256"]:
        raise PipelineError(f"{label} is missing or changed: {ref['path']}")
    return path


def bind_exclusive_multi_manifest(
    root: Path, row: dict[str, Any], work: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    """Verify a complete, exclusive manifest inventory and its retained files."""
    wid = work["work_id"]
    if any(isinstance(item, dict) and str(item.get("path", "")).startswith("raw/standard_ebooks/")
           and Path(str(item.get("path", ""))).suffix.lower() != ".xhtml"
           for item in row.get("primary_sources", [])):
        raise PipelineError(f"{wid} all-file Standard Ebooks source packet is superseded by OPF-spine text accounting")
    if any(key in row for key in (
        "primary_source", "media_type", "source_receipt", "source_packet",
        "cohort_source_set", "archive_member", "acquisition_receipt", "support_source",
        "containing_source", "source_child_element", "shared_volume_evidence",
    )):
        raise PipelineError(f"{wid} multi-member manifest has competing source route")
    manifest_ref = row.get("source_manifest")
    config_ref = row.get("config")
    metadata_ref = row.get("metadata_evidence")
    manifest = json.loads(_io_path(_bound(root, manifest_ref, f"{wid} manifest")).read_text(encoding="utf-8"))
    config = json.loads(_io_path(_bound(root, config_ref, f"{wid} config")).read_text(encoding="utf-8"))
    metadata_rel = f"metadata/source-evidence/catalog/{wid}.json"
    if (not isinstance(metadata_ref, dict) or metadata_ref.get("path") != metadata_rel
            or metadata_rel not in work.get("evidence", [])):
        raise PipelineError(f"{wid} catalog evidence is not cited by the work")
    metadata = json.loads(_io_path(_bound(root, metadata_ref, f"{wid} catalog evidence")).read_text(encoding="utf-8"))
    authorities = manifest.get("authorities")
    if (manifest.get("contract") != "ocd-source-manifest-v1"
            or manifest.get("work_id") != wid or not isinstance(authorities, list)
            or config.get("resource_id") != wid or config.get("source_url") != row.get("url")
            or config.get("language") != row.get("language")
            or not isinstance(row.get("url"), str)
            or not row["url"].startswith(("https://", "http://"))):
        raise PipelineError(f"{wid} manifest/config identity, language, or source URL differs")
    config_authorities = [item for item in authorities if isinstance(item, dict)
                          and item.get("path") == config_ref["path"]]
    if len(config_authorities) != 1 or config_authorities[0].get("sha256") != config_ref["sha256"]:
        raise PipelineError(f"{wid} current config is not bound by the manifest")
    primary = [item for item in authorities if isinstance(item, dict) and item.get("role") == "primary-source"]
    if len(primary) < 2 or row.get("primary_sources") != primary:
        raise PipelineError(f"{wid} ordered primary members differ from the exact manifest")
    catalog_sources = primary + [item for item in authorities if isinstance(item, dict)
                                 and item.get("role") == "retained-support"
                                 and isinstance(item.get("path"), str)
                                 and item["path"].startswith("raw/")
                                 and item["path"].endswith("/content.opf")]
    if metadata.get("subject") != {"id": wid, "kind": "catalog"} or not any(
        _source_bindings(metadata, item) for item in catalog_sources
    ):
        raise PipelineError(f"{wid} catalog evidence does not corroborate the retained source")
    scope = (f"All {len(primary)} primary members in manifest {manifest_ref['path']}, in manifest "
             "inventory order; electronic witness only. Inventory order does not establish "
             "reading order, print-edition identity, accepted TEI, rights clearance, or publication authorization.")
    if row.get("source_scope") != scope:
        raise PipelineError(f"{wid} source scope is not the bounded multi-member claim")
    warnings = row.get("warnings")
    if (not isinstance(warnings, list) or not warnings or any(
        not isinstance(item, str) or not item.strip() for item in warnings
    ) or not all(word in " ".join(warnings).casefold() for word in
                 ("rights", "attribution", "accepted", "publication"))):
        raise PipelineError(f"{wid} rights, attribution, acceptance, or publication limit missing")
    evidence = [manifest_ref["path"], config_ref["path"], metadata_rel]
    retained = []
    seen = set()
    for item in primary:
        rel = item.get("path")
        suffix = PurePosixPath(rel).suffix.lower() if isinstance(rel, str) else ""
        if (not isinstance(rel, str) or not rel.startswith("raw/") or rel in seen
                or suffix not in MEDIA_TYPES or suffix == ".zip"
                or not isinstance(item.get("bytes"), int) or isinstance(item["bytes"], bool)
                or item["bytes"] <= 0 or not isinstance(item.get("sha256"), str)):
            raise PipelineError(f"{wid} invalid or duplicate primary member: {rel}")
        seen.add(rel)
        path = resolve_repo_path(root, rel)
        if (not path.is_file() or path.stat().st_size != item["bytes"]
                or sha256_file(_io_path(path)) != item["sha256"]):
            raise PipelineError(f"{wid} retained member bytes changed: {rel}")
        retained.append({"path": rel, "bytes": item["bytes"], "sha256": item["sha256"],
                         "media_type": MEDIA_TYPES[suffix], "scope": scope})
        evidence.append(rel)
    for item in catalog_sources:
        if item.get("role") != "retained-support":
            continue
        rel = item["path"]
        path = resolve_repo_path(root, rel)
        if (not path.is_file() or path.stat().st_size != item.get("bytes")
                or sha256_file(_io_path(path)) != item.get("sha256")):
            raise PipelineError(f"{wid} EPUB content manifest changed: {rel}")
        evidence.append(rel)
    notices = []
    for item in authorities:
        if not isinstance(item, dict) or item.get("role") not in NOTICE_ROLES:
            continue
        rel = item.get("path")
        if not isinstance(rel, str) or not isinstance(item.get("bytes"), int):
            raise PipelineError(f"{wid} invalid source attribution authority")
        path = resolve_repo_path(root, rel)
        if (not path.is_file() or path.stat().st_size != item["bytes"]
                or sha256_file(_io_path(path)) != item.get("sha256")):
            raise PipelineError(f"{wid} source attribution changed: {rel}")
        notices.append(rel)
        evidence.append(rel)
    return retained, {"source_kind": "retained-member-set", "source_scope": scope}, list(dict.fromkeys(evidence)), notices
