"""Bind Calvin's retained CCEL XML witness, with SWORD only as comparison."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from build.tools.library_exclusive_manifest_binding import _source_bindings
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file
from ocd_kernel.tei.install_accepted import _io_path


WORK_ID = "calvin-commentaries"
MANIFEST_SOURCE_ID = "calvin-commentaries-retained-ccel-thml"
ROOT = "raw/ccel/calvin-commentaries/"
CONFIG_REL = "sources/commentaries/calvin/config.json"
RECEIPT_REL = "raw/ccel/calvin-commentaries/calvin-commentaries.manifest.json"
PROFILE_REL = "sources/commentaries/calvin/calvin-commentaries.reconstruction-profile.json"
ATTRIBUTION_REL = "sources/commentaries/calvin/README.source.md"
CCEL_URL = "https://www.ccel.org/ccel/calvin/commentaries.html"
SWORD_ZIP_REL = "raw/sword_modules/CalvinCommentaries.zip"
SWORD_URL = "https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/CalvinCommentaries.zip"


def _bound(root: Path, ref: Any, label: str) -> Path:
    if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
            or not isinstance(ref["path"], str) or not isinstance(ref["sha256"], str)):
        raise PipelineError(f"{label} requires exact path and hash")
    path = resolve_repo_path(root, ref["path"])
    if not path.is_file() or sha256_file(_io_path(path)) != ref["sha256"]:
        raise PipelineError(f"{label} missing or changed: {ref['path']}")
    return path


def _authority(manifest: dict[str, Any], path: str, role: str) -> dict[str, Any]:
    found = [item for item in manifest["authorities"] if isinstance(item, dict)
             and item.get("path") == path and item.get("role") == role]
    if len(found) != 1:
        raise PipelineError(f"Calvin manifest does not uniquely bind {role}: {path}")
    return found[0]


def _exact(root: Path, item: dict[str, Any]) -> None:
    rel = item.get("path")
    if not isinstance(rel, str) or not isinstance(item.get("bytes"), int) or isinstance(item["bytes"], bool):
        raise PipelineError(f"Calvin invalid retained authority: {rel}")
    path = resolve_repo_path(root, rel)
    if (not path.is_file() or path.stat().st_size != item["bytes"]
            or sha256_file(_io_path(path)) != item.get("sha256")):
        raise PipelineError(f"Calvin retained authority missing or changed: {rel}")


def bind_calvin_direct_ccel(
    root: Path, row: dict[str, Any], work: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    """Verify all direct CCEL member bytes and URL bindings, excluding ZIP source claims."""
    if work["work_id"] != WORK_ID or any(key in row for key in (
        "primary_source", "media_type", "source_receipt", "source_packet",
        "cohort_source_set", "archive_member", "acquisition_receipt", "support_source",
        "containing_source", "source_child_element", "shared_volume_evidence",
        "url_evidence", "lookup_source_evidence", "bible_member_evidence",
    )):
        raise PipelineError("Calvin direct CCEL route has competing source evidence")
    manifest_ref = row.get("source_manifest")
    receipt_ref = row.get("direct_ccel_receipt")
    profile_ref = row.get("source_profile")
    config_ref = row.get("config")
    metadata_ref = row.get("metadata_evidence")
    if (not isinstance(manifest_ref, dict) or not isinstance(receipt_ref, dict)
            or receipt_ref.get("path") != RECEIPT_REL
            or not isinstance(profile_ref, dict) or profile_ref.get("path") != PROFILE_REL
            or not isinstance(config_ref, dict) or config_ref.get("path") != CONFIG_REL):
        raise PipelineError("Calvin exact manifest, receipt, profile, and comparison config required")
    manifest = json.loads(_io_path(_bound(root, manifest_ref, "Calvin source manifest")).read_text(encoding="utf-8"))
    receipt = json.loads(_io_path(_bound(root, receipt_ref, "Calvin CCEL receipt")).read_text(encoding="utf-8"))
    profile = json.loads(_io_path(_bound(root, profile_ref, "Calvin profile")).read_text(encoding="utf-8"))
    config = json.loads(_io_path(_bound(root, config_ref, "Calvin comparison config")).read_text(encoding="utf-8"))
    metadata_rel = f"metadata/source-evidence/catalog/{WORK_ID}.json"
    if (not isinstance(metadata_ref, dict) or metadata_ref.get("path") != metadata_rel
            or metadata_rel not in work.get("evidence", [])):
        raise PipelineError("Calvin catalog evidence is not cited by the work")
    metadata = json.loads(_io_path(_bound(root, metadata_ref, "Calvin catalog")).read_text(encoding="utf-8"))
    if (manifest.get("contract") != "ocd-source-manifest-v1"
            or manifest.get("work_id") != WORK_ID
            or manifest.get("source_id") != MANIFEST_SOURCE_ID
            or not isinstance(manifest.get("authorities"), list)
            or receipt.get("work_id") != WORK_ID
            or receipt.get("source_work_url") != CCEL_URL
            or receipt.get("source") != "Christian Classics Ethereal Library"
            or profile.get("contract") != "ocd-calvin-commentaries-profile-v1"
            or profile.get("work_id") != WORK_ID
            or profile.get("member_census") != {"excluded": 0, "included": 46, "retained_family_total": 46}
            or config.get("resource_id") != WORK_ID
            or config.get("source_url") != SWORD_URL
            or row.get("url") != CCEL_URL
            or row.get("provider") != "Christian Classics Ethereal Library"
            or row.get("language") != "en"):
        raise PipelineError("Calvin direct CCEL identity or comparison distinction differs")
    for ref, role in ((receipt_ref, "source-acquisition-manifest"),
                      (profile_ref, "complete-source-feature-profile"),
                      (config_ref, "work-config")):
        if _authority(manifest, ref["path"], role).get("sha256") != ref["sha256"]:
            raise PipelineError(f"Calvin manifest does not pin {role}")
    primary = [item for item in manifest["authorities"] if isinstance(item, dict)
               and item.get("role") == "primary-source"]
    expected_names = ["commentaries.xml", *(f"calcom{number:02d}.xml" for number in range(1, 46))]
    if (len(primary) != 46 or [item.get("name") for item in primary] != expected_names
            or row.get("primary_sources") != primary
            or metadata.get("subject") != {"id": WORK_ID, "kind": "catalog"}
            or not _source_bindings(metadata, primary[0])):
        raise PipelineError("Calvin 46 XML manifest or catalog binding differs")
    profile_members = profile.get("members")
    receipt_files = receipt.get("files")
    if (not isinstance(profile_members, list) or len(profile_members) != 46
            or not isinstance(receipt_files, list) or len(receipt_files) != 46):
        raise PipelineError("Calvin CCEL profile or receipt member count differs")
    profile_map = {item.get("path"): item for item in profile_members if isinstance(item, dict)}
    receipt_map = {item.get("path"): item for item in receipt_files if isinstance(item, dict)}
    if len(profile_map) != 46 or len(receipt_map) != 46:
        raise PipelineError("Calvin CCEL profile or receipt duplicate member")
    scope = ("All 46 direct CCEL XML members (catalogue and calcom01-calcom45) in retained manifest inventory order; "
             "electronic witness only. The CrossWire SWORD ZIP/config are comparison evidence, never the text source. "
             "Inventory order is not a reading-order or complete print-edition claim; accepted TEI, rights clearance, "
             "and publication authorization remain separate.")
    if row.get("source_scope") != scope:
        raise PipelineError("Calvin direct CCEL source scope differs")
    warnings = row.get("warnings")
    if (not isinstance(warnings, list) or not warnings or any(
        not isinstance(value, str) or not value.strip() for value in warnings
    ) or not all(term in " ".join(warnings).casefold() for term in
                 ("rights", "attribution", "accepted", "publication"))):
        raise PipelineError("Calvin rights/attribution/acceptance limits missing")
    retained: list[dict[str, Any]] = []
    evidence = [manifest_ref["path"], receipt_ref["path"], profile_ref["path"], config_ref["path"], metadata_rel]
    for item in primary:
        rel = item["path"]
        if rel != ROOT + item["name"] or not rel.endswith(".xml"):
            raise PipelineError(f"Calvin non-CCEL or non-XML source: {rel}")
        prof, fetched = profile_map.get(rel), receipt_map.get(rel)
        expected = {key: item[key] for key in ("path", "bytes", "sha256")}
        if (not isinstance(prof, dict) or {key: prof.get(key) for key in expected} != expected
                or not isinstance(fetched, dict)
                or {key: fetched.get(key) for key in expected} != expected
                or fetched.get("source_url") != f"https://ccel.org/ccel/c/calvin/{item['name']}"):
            raise PipelineError(f"Calvin profile or direct CCEL URL differs: {rel}")
        _exact(root, item)
        retained.append({**expected, "media_type": "application/xml", "scope": scope})
        evidence.append(rel)
    attribution = _authority(manifest, ATTRIBUTION_REL, "source-attribution")
    comparison = _authority(manifest, SWORD_ZIP_REL, "comparison-witness-only")
    comparison_conf = _authority(manifest, "raw/sword_modules/CalvinCommentaries/mods.d/calvincommentaries.conf",
                                 "comparison-witness-only")
    for item in (attribution, comparison, comparison_conf):
        _exact(root, item)
        evidence.append(item["path"])
    if any(item["path"] in {comparison["path"], comparison_conf["path"]} for item in retained):
        raise PipelineError("Calvin comparison witness cannot be textual source")
    return retained, {"source_kind": "retained-member-set", "source_scope": scope}, list(dict.fromkeys(evidence)), [PROFILE_REL, ATTRIBUTION_REL]
