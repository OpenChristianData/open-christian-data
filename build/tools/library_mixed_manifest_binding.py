"""Bind shared BCP members and Whitefield's two retained source witnesses.

The resulting edition is an electronic source account, not a claim that the
different witnesses form one historical print edition or accepted TEI.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from build.tools.library_exclusive_manifest_binding import _source_bindings
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file
from ocd_kernel.tei.install_accepted import _io_path


SOURCE_IDS = {
    "bcp-1662": "bcp-1662-retained-partial-html",
    "bcp-1662-collects": "bcp-1662-retained-partial-html",
    "george-whitefield-sermons": "george-whitefield-sermons-retained-cohort-ccel-pg77041",
}


def _ref(root: Path, ref: Any, label: str) -> Path:
    if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
            or not isinstance(ref["path"], str) or not isinstance(ref["sha256"], str)):
        raise PipelineError(f"{label} requires an exact path and hash")
    path = resolve_repo_path(root, ref["path"])
    if not path.is_file() or sha256_file(_io_path(path)) != ref["sha256"]:
        raise PipelineError(f"{label} missing or changed: {ref['path']}")
    return path


def _catalog_ref(value: Any, ref: dict[str, str]) -> bool:
    if isinstance(value, dict):
        return (value.get("path") == ref["path"] and value.get("sha256") == ref["sha256"]
                or any(_catalog_ref(child, ref) for child in value.values()))
    if isinstance(value, list):
        return any(_catalog_ref(child, ref) for child in value)
    return False


def bind_mixed_manifest(
    root: Path, row: dict[str, Any], work: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    wid = work["work_id"]
    if wid == "george-whitefield-sermons":
        raise PipelineError("Whitefield combined-witness packet is superseded by two separate acquisitions")
    if wid not in SOURCE_IDS or any(key in row for key in (
        "primary_source", "media_type", "source_receipt", "source_packet", "cohort_source_set",
        "archive_member", "acquisition_receipt", "support_source", "containing_source",
        "source_child_element", "shared_volume_evidence", "url_evidence",
    )):
        raise PipelineError(f"{wid} unsupported or competing mixed-source route")
    manifest_ref, config_ref, profile_ref = (row.get(k) for k in ("source_manifest", "config", "source_profile"))
    manifest = json.loads(_io_path(_ref(root, manifest_ref, f"{wid} manifest")).read_text(encoding="utf-8"))
    config = json.loads(_io_path(_ref(root, config_ref, f"{wid} config")).read_text(encoding="utf-8"))
    profile = json.loads(_io_path(_ref(root, profile_ref, f"{wid} profile")).read_text(encoding="utf-8"))
    authorities = manifest.get("authorities")
    if (manifest.get("contract") != "ocd-source-manifest-v1"
            or manifest.get("source_id") != SOURCE_IDS[wid]
            or not isinstance(authorities, list)
            or config.get("resource_id") != wid or config.get("source_url") != row.get("url")
            or config.get("language") != row.get("language")):
        raise PipelineError(f"{wid} source identity, URL, or language differs")
    for ref, role in ((config_ref, "routing-observation-not-edition-or-rights-authority"
                       if wid == "george-whitefield-sermons" else "source-identity-and-rights-config"),
                      (profile_ref, "complete-source-feature-profile")):
        matches = [a for a in authorities if isinstance(a, dict) and a.get("path") == ref["path"]
                   and a.get("sha256") == ref["sha256"] and a.get("role") == role]
        if len(matches) != 1:
            raise PipelineError(f"{wid} manifest does not bind exact {role}")
    primary = [a for a in authorities if isinstance(a, dict) and a.get("role") == "primary-source"]
    if wid == "bcp-1662-collects":
        selected = [a for a in primary if a.get("path", "").startswith("raw/bcp1662/")]
        if (len(primary) != 25 or len(selected) != 5 or not config.get("source_url", "").endswith("/communion/")):
            raise PipelineError("BCP Collects needs the five exact communion members")
    elif wid == "bcp-1662":
        selected = primary
        scope_claim = profile.get("source_scope", {})
        if (len(selected) != 25 or scope_claim.get("status") != "partial-expression-scope"
                or scope_claim.get("present_members") != 25 or scope_claim.get("failed_acquisitions") != 5):
            raise PipelineError("BCP 1662 partial expression boundary differs")
    else:
        selected = primary
        profile_members = profile.get("members", [])
        config_pg = config.get("supplementary_source", {})
        if (manifest.get("work_id") != wid or profile.get("work_id") != wid
                or len(selected) != len(profile_members) or len(selected) != 2
                or any(any(p.get(k) != a.get(k) for k in ("path", "bytes", "sha256"))
                       for a, p in zip(selected, profile_members))
                or config_pg.get("url") != "https://www.gutenberg.org/ebooks/77041"
                or config_pg.get("source_hash") != "sha256:" + selected[1]["sha256"]
                or profile.get("identity", {}).get("edition_relationship") != "unresolved"):
            raise PipelineError("Whitefield two-witness scope or PG source URL differs")
    if row.get("primary_sources") != selected:
        raise PipelineError(f"{wid} selected primary set differs from manifest")
    metadata_rel = f"metadata/source-evidence/catalog/{wid}.json"
    metadata_ref = row.get("metadata_evidence")
    if (not isinstance(metadata_ref, dict) or metadata_ref.get("path") != metadata_rel
            or metadata_rel not in work.get("evidence", [])):
        raise PipelineError(f"{wid} catalog evidence is not cited by work")
    metadata = json.loads(_io_path(_ref(root, metadata_ref, f"{wid} catalog")).read_text(encoding="utf-8"))
    if (metadata.get("subject") != {"id": wid, "kind": "catalog"}
            or not (any(_source_bindings(metadata, a) for a in primary)
                    if wid != "george-whitefield-sermons" else _catalog_ref(metadata, config_ref))):
        raise PipelineError(f"{wid} catalog evidence does not corroborate its retained source route")
    scope_text = {
        "bcp-1662": "25 retained HTML members of the partial 1662 BCP expression; five acquisition failures and incomplete print scope remain. Electronic witness only; accepted TEI, rights clearance, and publication authorization remain separate.",
        "bcp-1662-collects": "Five retained communion/collects HTML members within the partial 1662 BCP source manifest; no claim over the other 20 files, a complete print edition, accepted TEI, rights clearance, or publication authorization.",
        "george-whitefield-sermons": "CCEL complete retained XML plus Project Gutenberg #77041 complete retained TXT as separate electronic witnesses; only the two source-native PG sermons selected by the bound profile are in this work route. No unified print-edition, shared numbering, accepted TEI, rights clearance, or publication authorization claim.",
    }[wid]
    if row.get("source_scope") != scope_text:
        raise PipelineError(f"{wid} mixed-source scope differs")
    warnings = row.get("warnings")
    if (not isinstance(warnings, list) or not warnings or any(
        not isinstance(item, str) or not item.strip() for item in warnings
    ) or not all(term in " ".join(warnings).casefold() for term in
                 ("rights", "attribution", "accepted", "publication"))):
        raise PipelineError(f"{wid} rights, attribution, acceptance, or publication limit missing")
    evidence = [manifest_ref["path"], config_ref["path"], profile_ref["path"], metadata_rel]
    retained = []
    for item in selected:
        rel = item["path"]
        media = "text/html" if wid.startswith("bcp-") else (
            "application/xml" if rel.endswith(".xml") else "text/plain")
        if (not rel.startswith("raw/") or rel.lower().endswith(".zip")
                or (wid.startswith("bcp-") and not rel.endswith(".html"))
                or (wid == "george-whitefield-sermons" and not rel.endswith((".xml", ".txt")))):
            raise PipelineError(f"{wid} invalid real source member: {rel}")
        path = resolve_repo_path(root, rel)
        if (not path.is_file() or path.stat().st_size != item["bytes"]
                or sha256_file(_io_path(path)) != item["sha256"]):
            raise PipelineError(f"{wid} source bytes changed: {rel}")
        retained.append({"path": rel, "bytes": item["bytes"], "sha256": item["sha256"],
                         "media_type": media, "scope": scope_text})
        evidence.append(rel)
    notices = []
    for item in authorities:
        if not isinstance(item, dict) or item.get("role") not in {"source-attribution", "source-readme"}:
            continue
        rel = item["path"]
        path = resolve_repo_path(root, rel)
        if (not path.is_file() or path.stat().st_size != item["bytes"]
                or sha256_file(_io_path(path)) != item["sha256"]):
            raise PipelineError(f"{wid} source attribution changed: {rel}")
        notices.append(rel)
        evidence.append(rel)
    return retained, {"source_kind": "retained-member-set", "source_scope": scope_text}, list(dict.fromkeys(evidence)), [profile_ref["path"], *notices]
