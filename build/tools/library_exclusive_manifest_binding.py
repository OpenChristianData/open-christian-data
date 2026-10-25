"""Bind an exclusive, single-file source manifest without a route config.

This establishes acquisition accounting for the retained electronic member.
It does not identify a print edition or accept a reconstruction.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file
from ocd_kernel.tei.install_accepted import _io_path


PROFILE_SOURCE_FIELDS = {
    "augustines-confessions": "source_scope",
    "john-wesley-sermons": "source_scope",
    "luthers-large-catechism": "source_member",
}

MEDIA_TYPES = {
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".html": "text/html",
}


def _bound(root: Path, ref: Any, label: str) -> Path:
    if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
            or not isinstance(ref["path"], str)
            or not isinstance(ref["sha256"], str)):
        raise PipelineError(f"{label} needs an exact path and hash")
    path = resolve_repo_path(root, ref["path"])
    if not path.is_file() or sha256_file(_io_path(path)) != ref["sha256"]:
        raise PipelineError(f"{label} missing or changed: {ref['path']}")
    return path


def _source_bindings(value: Any, source: dict[str, Any]) -> bool:
    if isinstance(value, dict):
        if (value.get("role") == "primary"
                and all(value.get(key) == source[key] for key in ("path", "bytes", "sha256"))):
            return True
        return any(_source_bindings(child, source) for child in value.values())
    if isinstance(value, list):
        return any(_source_bindings(child, source) for child in value)
    return False


def _primary_bindings(value: Any) -> set[tuple[str, int, str]]:
    """Collect distinct catalog primary witnesses without equating byte variants."""
    if isinstance(value, dict):
        if value.get("role") == "primary" and all(key in value for key in ("path", "bytes", "sha256")):
            return {(value["path"], value["bytes"], value["sha256"])}
        result: set[tuple[str, int, str]] = set()
        for child in value.values():
            result.update(_primary_bindings(child))
        return result
    if isinstance(value, list):
        result = set()
        for child in value:
            result.update(_primary_bindings(child))
        return result
    return set()


def _profile_corroborates(root: Path, manifest: dict[str, Any], source: dict[str, Any],
                          metadata: dict[str, Any], wid: str) -> str:
    """Resolve three named older routes using exact source-local profiles."""
    field = PROFILE_SOURCE_FIELDS.get(wid)
    if field is None:
        raise PipelineError(f"{wid} catalog evidence does not corroborate retained primary file")
    profiles = [item for item in manifest["authorities"] if isinstance(item, dict)
                and item.get("role") == "complete-source-feature-profile"]
    if len(profiles) != 1:
        raise PipelineError(f"{wid} requires exactly one bound reconstruction profile")
    profile_ref = profiles[0]
    profile_path = resolve_repo_path(root, profile_ref["path"])
    if (not profile_path.is_file() or profile_path.stat().st_size != profile_ref.get("bytes")
            or sha256_file(_io_path(profile_path)) != profile_ref.get("sha256")):
        raise PipelineError(f"{wid} reconstruction profile bytes changed")
    profile = json.loads(_io_path(profile_path).read_text(encoding="utf-8"))
    if profile.get("work_id") != wid:
        raise PipelineError(f"{wid} reconstruction profile work identity differs")
    observed = profile.get(field)
    if wid == "augustines-confessions":
        bound = {"path": observed.get("retained_member"), "bytes": observed.get("expected_bytes"),
                 "sha256": observed.get("expected_sha256")} if isinstance(observed, dict) else None
    elif wid == "john-wesley-sermons":
        bound = {"path": observed.get("logical_path"), "bytes": observed.get("bytes"),
                 "sha256": observed.get("sha256")} if isinstance(observed, dict) else None
    else:
        bound = observed
    if not isinstance(bound, dict) or any(bound.get(key) != source[key] for key in ("path", "bytes", "sha256")):
        raise PipelineError(f"{wid} reconstruction profile does not corroborate manifest source")
    catalog_primaries = _primary_bindings(metadata)
    if wid == "augustines-confessions":
        alternate = ("raw/gutenberg/pg3296.txt", source["bytes"] + 3,
                     "20f5b0791e2307186e3db1f80a90f2083ace32a00c5074011dd47d1cb3bb6e00")
        if catalog_primaries != {alternate}:
            raise PipelineError(f"{wid} catalog alternate witness changed")
        other_path = resolve_repo_path(root, alternate[0])
        if (not other_path.is_file() or other_path.stat().st_size != alternate[1]
                or sha256_file(_io_path(other_path)) != alternate[2]
                or _io_path(other_path).read_bytes() != b"\xef\xbb\xbf" + _io_path(resolve_repo_path(root, source["path"])).read_bytes()):
            raise PipelineError(f"{wid} catalog alternate is not the exact BOM-prefixed witness")
    elif catalog_primaries:
        raise PipelineError(f"{wid} catalog has a conflicting primary witness")
    return profile_ref["path"]


def bind_exclusive_manifest(
    root: Path, row: dict[str, Any], work: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    """Require two independent path/hash attestations of one retained member."""
    wid = work["work_id"]
    if any(name in row for name in (
            "config", "shared_volume_evidence", "cohort_source_set", "source_packet",
            "source_receipt", "acquisition_receipt", "archive_member", "containing_source",
            "primary_sources", "source_child_element", "support_source")):
        raise PipelineError(f"{wid} exclusive manifest has competing source route")
    manifest_ref = row.get("source_manifest")
    manifest_path = _bound(root, manifest_ref, f"{wid} source manifest")
    manifest = json.loads(_io_path(manifest_path).read_text(encoding="utf-8"))
    if (manifest.get("contract") != "ocd-source-manifest-v1"
            or manifest.get("work_id") != wid
            or not isinstance(manifest.get("authorities"), list)):
        raise PipelineError(f"{wid} manifest does not exclusively identify this work")
    primary = [item for item in manifest["authorities"]
               if isinstance(item, dict) and item.get("role") == "primary-source"]
    if len(primary) != 1 or row.get("primary_source") != primary[0]:
        raise PipelineError(f"{wid} requires exactly one manifest primary source")
    source = primary[0]
    source_rel = source.get("path")
    if (not isinstance(source_rel, str)
            or PurePosixPath(source_rel).suffix.lower() not in MEDIA_TYPES
            or PurePosixPath(source_rel).suffix.lower() == ".zip"
            or source.get("work_ids", [wid]) != [wid]
            or row.get("media_type") != MEDIA_TYPES.get(PurePosixPath(source_rel).suffix.lower())):
        raise PipelineError(f"{wid} primary source path, media type, or work assignment differs")
    source_path = resolve_repo_path(root, source_rel)
    if (not isinstance(source.get("bytes"), int) or isinstance(source["bytes"], bool)
            or source["bytes"] <= 0 or not source_path.is_file()
            or source_path.stat().st_size != source["bytes"]
            or sha256_file(_io_path(source_path)) != source.get("sha256")):
        raise PipelineError(f"{wid} retained primary file bytes changed: {source_rel}")
    metadata_rel = f"metadata/source-evidence/catalog/{wid}.json"
    metadata_ref = row.get("metadata_evidence")
    if (not isinstance(metadata_ref, dict) or metadata_ref.get("path") != metadata_rel
            or metadata_rel not in work.get("evidence", [])):
        raise PipelineError(f"{wid} work does not cite its catalog source evidence")
    metadata = json.loads(_io_path(_bound(root, metadata_ref, f"{wid} metadata")).read_text(encoding="utf-8"))
    if metadata.get("subject") != {"id": wid, "kind": "catalog"}:
        raise PipelineError(f"{wid} catalog evidence subject differs")
    profile_evidence = None
    if not _source_bindings(metadata, source):
        profile_evidence = _profile_corroborates(root, manifest, source, metadata, wid)
    url_ref = row.get("url_evidence")
    url_path = _bound(root, url_ref, f"{wid} URL evidence")
    url = row.get("url")
    if (not isinstance(url, str) or not url.startswith(("http://", "https://"))
            or url not in _io_path(url_path).read_text(encoding="utf-8")):
        raise PipelineError(f"{wid} acquisition URL absent from bound evidence")
    scope = (f"Complete retained textual member {source_rel}; this electronic witness "
             "does not establish print-edition identity, accepted TEI, rights clearance, "
             "or publication authorization.")
    if row.get("source_scope") != scope:
        raise PipelineError(f"{wid} source scope must describe only the retained member")
    warnings = row.get("warnings")
    if (not isinstance(warnings, list) or not warnings
            or any(not isinstance(item, str) or not item.strip() for item in warnings)
            or not all(term in " ".join(warnings).casefold() for term in
                       ("rights", "attribution", "accepted", "publication"))):
        raise PipelineError(f"{wid} rights, attribution, and acceptance limits missing")
    if wid == "augustines-confessions" and profile_evidence is not None and not any(
            "UTF-8 BOM" in warning and "raw/gutenberg/pg3296.txt" in warning
            and source_rel in warning for warning in warnings):
        raise PipelineError(f"{wid} alternate Gutenberg witness must remain explicit")
    notice_paths = []
    for item in manifest["authorities"]:
        if (not isinstance(item, dict) or item.get("role") not in
                {"source-attribution-readme", "source-attribution", "rights-evidence"}):
            continue
        notice_path = resolve_repo_path(root, item["path"])
        if (not notice_path.is_file() or notice_path.stat().st_size != item["bytes"]
                or sha256_file(_io_path(notice_path)) != item["sha256"]):
            raise PipelineError(f"{wid} source notice bytes changed")
        notice_paths.append(item["path"])
    retained = [{"path": source_rel, "bytes": source["bytes"],
                 "sha256": source["sha256"], "media_type": row["media_type"],
                 "scope": scope}]
    source_fields = {"source_path": source_rel, "source_bytes": source["bytes"],
                     "source_sha256": source["sha256"], "source_scope": scope}
    evidence_paths = list(dict.fromkeys([manifest_ref["path"], metadata_rel,
                                         url_ref["path"], source_rel,
                                         *([profile_evidence] if profile_evidence else []), *notice_paths]))
    return retained, source_fields, evidence_paths, notice_paths + ([profile_evidence] if profile_evidence else [])
