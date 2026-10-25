"""Bounded source accounting for three config-free retained member sets.

The ZIP in a package URL or Nave authority is acquisition evidence only.
Every source member here is an extracted, independently hashed real file.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from build.tools.library_exclusive_manifest_binding import _source_bindings
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file
from ocd_kernel.tei.install_accepted import _io_path


MANIFEST_SOURCE_IDS = {
    "bcp-1928-collects": "bcp-1928-collects-retained-episcopalnet-html",
    "daily-light": "crosswire-daily-light-sword-rawld-retained",
    "naves-topical-bible": "crosswire-nave-sword-v3",
}


def _exact_file(root: Path, rel: str, size: int, digest: str, label: str) -> Path:
    path = resolve_repo_path(root, rel)
    if (not path.is_file() or path.stat().st_size != size
            or sha256_file(_io_path(path)) != digest):
        raise PipelineError(f"{label} missing or changed: {rel}")
    return path


def _ref(root: Path, ref: Any, label: str) -> Path:
    if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
            or not isinstance(ref["path"], str) or not isinstance(ref["sha256"], str)):
        raise PipelineError(f"{label} requires exact path and hash")
    path = resolve_repo_path(root, ref["path"])
    if not path.is_file() or sha256_file(_io_path(path)) != ref["sha256"]:
        raise PipelineError(f"{label} missing or changed")
    return path


def _manifest_authority(manifest: dict[str, Any], ref: dict[str, str], role: str) -> dict[str, Any]:
    matches = [a for a in manifest["authorities"] if isinstance(a, dict)
               and a.get("role") == role and a.get("path") == ref["path"]
               and a.get("sha256") == ref["sha256"]]
    if len(matches) != 1:
        raise PipelineError(f"manifest does not bind exact {role}: {ref['path']}")
    return matches[0]


def _has_catalog_ref(value: Any, ref: dict[str, str]) -> bool:
    if isinstance(value, dict):
        if value.get("path") == ref["path"] and value.get("sha256") == ref["sha256"]:
            return True
        return any(_has_catalog_ref(v, ref) for v in value.values())
    if isinstance(value, list):
        return any(_has_catalog_ref(v, ref) for v in value)
    return False


def bind_config_free_multi(
    root: Path, row: dict[str, Any], work: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    wid = work["work_id"]
    if wid not in MANIFEST_SOURCE_IDS or any(key in row for key in (
        "config", "primary_source", "media_type", "source_receipt", "source_packet",
        "cohort_source_set", "archive_member", "acquisition_receipt", "support_source",
        "containing_source", "source_child_element", "shared_volume_evidence",
    )):
        raise PipelineError(f"{wid} unsupported or competing config-free source route")
    manifest_ref = row.get("source_manifest")
    profile_ref = row.get("source_profile")
    url_ref = row.get("url_evidence")
    manifest = json.loads(_io_path(_ref(root, manifest_ref, f"{wid} manifest")).read_text(encoding="utf-8"))
    profile = json.loads(_io_path(_ref(root, profile_ref, f"{wid} profile")).read_text(encoding="utf-8"))
    url_text = _io_path(_ref(root, url_ref, f"{wid} URL evidence")).read_text(encoding="utf-8")
    if (manifest.get("contract") != "ocd-source-manifest-v1"
            or manifest.get("work_id") != wid
            or manifest.get("source_id") != MANIFEST_SOURCE_IDS[wid]
            or not isinstance(manifest.get("authorities"), list)
            or _manifest_authority(manifest, profile_ref, "complete-source-feature-profile").get("bytes") is None
            or not isinstance(row.get("url"), str)
            or not row["url"].startswith(("https://", "http://"))
            or row["url"] not in url_text):
        raise PipelineError(f"{wid} source manifest, profile, or URL evidence differs")
    if wid != "daily-light":
        role = "source-attribution" if wid == "naves-topical-bible" else "complete-source-feature-profile"
        _manifest_authority(manifest, url_ref, role)
    elif url_ref["path"] != "sources/devotionals/daily-light/config.json":
        raise PipelineError("daily-light URL must be pinned to its source config")
    if wid == "bcp-1928-collects" and (
        profile.get("source_id") != manifest["source_id"]
        or profile.get("source_url") != row["url"]
        or manifest.get("scope", {}).get("kind") != "partial-retained-html-expression"
        or manifest["scope"].get("unbound_manual_claims") != ["trinity23", "trinity24"]
    ):
        raise PipelineError(f"{wid} partial retained expression boundary differs")
    if wid == "daily-light":
        config = json.loads(url_text)
        if (config.get("resource_id") != wid or config.get("source_url") != row["url"]
                or profile.get("source_scope", {}).get("extracted_root") != "raw/sword_modules/Daily"):
            raise PipelineError("daily-light source URL or extracted scope differs")
    if wid == "naves-topical-bible" and profile.get("source_id") != manifest["source_id"]:
        raise PipelineError("Nave profile does not bind the manifest source")
    metadata_rel = f"metadata/source-evidence/catalog/{wid}.json"
    metadata_ref = row.get("metadata_evidence")
    if (not isinstance(metadata_ref, dict) or metadata_ref.get("path") != metadata_rel
            or metadata_rel not in work.get("evidence", [])):
        raise PipelineError(f"{wid} catalog evidence is not cited by the work")
    metadata = json.loads(_io_path(_ref(root, metadata_ref, f"{wid} catalog")).read_text(encoding="utf-8"))
    primary = [a for a in manifest["authorities"] if isinstance(a, dict) and a.get("role") == "primary-source"]
    if (metadata.get("subject") != {"id": wid, "kind": "catalog"}
            or not (any(_source_bindings(metadata, a) for a in primary)
                    or wid == "naves-topical-bible" and _has_catalog_ref(metadata, manifest_ref))
            or row.get("primary_sources") != primary):
        raise PipelineError(f"{wid} retained member inventory or catalog association differs")
    counts = {"bcp-1928-collects": 100, "daily-light": 2, "naves-topical-bible": 4}
    if len(primary) != counts[wid]:
        raise PipelineError(f"{wid} primary member count differs")
    scope = (f"All {len(primary)} extracted source members in {manifest_ref['path']}, in manifest inventory order. "
             "Inventory order is not a reading-order or complete print-edition claim. "
             "The ZIP, where present, is acquisition package only; accepted TEI, rights clearance, "
             "and publication authorization remain separate.")
    if row.get("source_scope") != scope:
        raise PipelineError(f"{wid} source scope differs")
    warnings = row.get("warnings")
    if (not isinstance(warnings, list) or not warnings or any(
        not isinstance(w, str) or not w.strip() for w in warnings
    ) or not all(term in " ".join(warnings).casefold() for term in
                 ("rights", "attribution", "accepted", "publication"))):
        raise PipelineError(f"{wid} rights/attribution/acceptance limits missing")
    expected_ext = {"bcp-1928-collects": {".html"}, "daily-light": {".dat", ".idx"},
                    "naves-topical-bible": {".dat", ".idx", ".zdt", ".zdx"}}[wid]
    evidence = [manifest_ref["path"], profile_ref["path"], url_ref["path"], metadata_rel]
    retained = []
    for item in primary:
        rel = item["path"]
        if (not rel.startswith("raw/") or Path(rel).suffix.lower() not in expected_ext
                or rel.lower().endswith(".zip")):
            raise PipelineError(f"{wid} package or wrong-format file named primary: {rel}")
        _exact_file(root, rel, item["bytes"], item["sha256"], f"{wid} primary member")
        retained.append({"path": rel, "bytes": item["bytes"], "sha256": item["sha256"],
                         "media_type": "text/html" if wid == "bcp-1928-collects" else "application/octet-stream",
                         "scope": scope})
        evidence.append(rel)
    support_roles = {"source-attribution", "source-attribution-evidence", "source-support-metadata-rights"}
    support = [a for a in manifest["authorities"] if isinstance(a, dict) and a.get("role") in support_roles]
    for item in support:
        _exact_file(root, item["path"], item["bytes"], item["sha256"], f"{wid} support")
        evidence.append(item["path"])
    if wid == "bcp-1928-collects":
        members = manifest.get("source_members", [])
        if ([{k: m[k] for k in ("path", "bytes", "sha256")} for m in members]
                != [{k: p[k] for k in ("path", "bytes", "sha256")} for p in primary]):
            raise PipelineError("BCP 1928 member census differs from manifest authorities")
    if wid == "daily-light":
        members = manifest.get("retained_member_census", {}).get("members", [])
        if {m["sha256"] for m in members} != {p["sha256"] for p in primary + support if p["path"].startswith("raw/")}:
            raise PipelineError("Daily Light extracted source census differs")
    if wid == "naves-topical-bible":
        packages = [a for a in manifest["authorities"] if isinstance(a, dict) and a.get("role") == "acquisition-container"]
        raw_support = [a for a in support if a["path"].startswith("raw/")]
        if len(packages) != 1 or len(raw_support) != 1:
            raise PipelineError("Nave needs one package and one module config")
        package = packages[0]
        archive = _exact_file(root, package["path"], package["bytes"], package["sha256"], "Nave ZIP package")
        prefix = "raw/naves_topical/"
        expected = {item["path"][len(prefix):]: item for item in primary + raw_support}
        try:
            with zipfile.ZipFile(_io_path(archive)) as zipped:
                if set(zipped.namelist()) != set(expected) or len(zipped.namelist()) != len(expected):
                    raise PipelineError("Nave ZIP inventory differs from extracted source")
                for name, item in expected.items():
                    data = zipped.read(name)
                    if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                        raise PipelineError(f"Nave ZIP member differs: {name}")
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            raise PipelineError(f"Nave ZIP cannot verify extracted source: {exc}") from exc
        evidence.append(package["path"])
    return retained, {"source_kind": "retained-member-set", "source_scope": scope}, list(dict.fromkeys(evidence)), [profile_ref["path"], *[a["path"] for a in support]]
