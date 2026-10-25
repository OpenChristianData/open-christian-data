"""Bind one LIB-062 work to its retained Creeds.json member.

This establishes acquisition accounting only. The source packet describes a
candidate reconstruction, but neither that packet nor this binding accepts TEI.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file


PREFLIGHT = "plans/2026-09-22-source-preflight/lib062-source-accounting-preflight-20260925.json"
PROVIDER = "NonlinearFruit/Creeds.json"
PROVIDER_URL = "https://github.com/NonlinearFruit/Creeds.json"


def _bound(root: Path, reference: Any, label: str) -> tuple[Path, str]:
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
            or not isinstance(reference["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is None):
        raise PipelineError(f"LIB-062 {label} needs exact path and SHA-256")
    path = resolve_repo_path(root, reference["path"])
    if not path.is_file() or sha256_file(path) != reference["sha256"]:
        raise PipelineError(f"LIB-062 {label} missing or changed: {reference['path']}")
    return path, reference["path"]


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"LIB-062 {label} is unreadable JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"LIB-062 {label} must be a JSON object: {path}")
    return value


def bind_creeds_packet(root: Path, row: dict[str, Any], work: dict[str, Any]) -> tuple[
        list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    """Return a direct JSON source, source fields, evidence, and staged files."""
    wid = work["work_id"]
    preflight_path, preflight_rel = _bound(root, row.get("source_preflight"), "preflight")
    if preflight_rel != PREFLIGHT:
        raise PipelineError(f"{wid} unsupported LIB-062 preflight")
    preflight = _json(preflight_path, "preflight")
    rows = preflight.get("works")
    if (preflight.get("contract") != "ocd-lib062-source-accounting-preflight-v1"
            or not isinstance(rows, list) or len(rows) != 6
            or any(not isinstance(item, dict) for item in rows)
            or len({item.get("work_id") for item in rows}) != 6):
        raise PipelineError("LIB-062 preflight six-work set differs")
    claims = [item for item in rows if item["work_id"] == wid]
    if len(claims) != 1 or claims[0].get("result") != "retained-source-binding-verified":
        raise PipelineError(f"{wid} lacks verified LIB-062 source claim")
    claim = claims[0]
    packet_path, packet_rel = _bound(root, row.get("source_packet"), f"{wid} packet")
    if (packet_rel != claim.get("packet")
            or row["source_packet"]["sha256"] != claim.get("packet_sha256")
            or packet_rel != f"sources/{wid}/LIB-062.packet.json"):
        raise PipelineError(f"{wid} packet identity differs from preflight")
    packet = _json(packet_path, f"{wid} packet")
    if packet.get("contract") != "ocd-lib062-source-packet-v1" or packet.get("work_id") != wid:
        raise PipelineError(f"{wid} packet contract/work identity differs")
    source = packet.get("authority")
    if (not isinstance(source, dict) or source.get("path") != claim.get("source_path")
            or source.get("raw_bytes") != claim.get("source_bytes")
            or source.get("raw_sha256") != claim.get("source_sha256")
            or not isinstance(source.get("path"), str)
            or not source["path"].startswith("raw/Creeds.json/creeds/")
            or not source["path"].endswith(".json")):
        raise PipelineError(f"{wid} packet source member differs from preflight")
    source_path = resolve_repo_path(root, source["path"])
    if (not source_path.is_file() or source_path.stat().st_size != source["raw_bytes"]
            or sha256_file(source_path) != source["raw_sha256"]):
        raise PipelineError(f"{wid} retained JSON source bytes/hash differ")
    source_doc = _json(source_path, f"{wid} source member")
    metadata = source_doc.get("Metadata")
    primary_metadata = packet.get("primary_metadata")
    if (not isinstance(metadata, dict) or not isinstance(primary_metadata, dict)
            or metadata.get("Title") != work["title"]
            or any(metadata.get(key) != value for key, value in primary_metadata.items())):
        raise PipelineError(f"{wid} work title or packet metadata differs from source")
    terms = packet.get("terms_evidence")
    if not isinstance(terms, dict) or terms != claim.get("terms_evidence"):
        raise PipelineError(f"{wid} packet terms differ from preflight")
    terms_path = resolve_repo_path(root, terms["path"])
    if (not terms_path.is_file() or terms_path.stat().st_size != terms["raw_bytes"]
            or sha256_file(terms_path) != terms["raw_sha256"]):
        raise PipelineError(f"{wid} retained provider terms bytes/hash differ")
    terms_text = terms_path.read_text(encoding="utf-8")
    member_rel = source["path"].removeprefix("raw/Creeds.json/")
    copyright_section, _, catalog_section = terms_text.partition("## Creeds Included")
    if ("Unlicense" not in copyright_section or f"({member_rel})" not in catalog_section
            or f"({member_rel})" in copyright_section):
        raise PipelineError(f"{wid} provider terms do not support non-exception member claim")
    census = packet.get("retained_member_census")
    if (not isinstance(census, dict) or census.get("path") != "sources/1695-baptist-catechism/LIB-062.retained-member-census.json"):
        raise PipelineError(f"{wid} source member census binding differs")
    census_path = resolve_repo_path(root, census["path"])
    if (not census_path.is_file() or census_path.stat().st_size != census.get("bytes")
            or sha256_file(census_path) != census.get("sha256")):
        raise PipelineError(f"{wid} source member census bytes/hash differ")
    members = _json(census_path, f"{wid} source member census").get("members")
    if (not isinstance(members, list) or sum(item.get("work_id") == wid and item.get("path") == source["path"]
            and item.get("disposition") == "included-authority" and item.get("raw_sha256") == source["raw_sha256"]
            for item in members if isinstance(item, dict)) != 1):
        raise PipelineError(f"{wid} source member census omits exact authority")
    attribution_path, attribution_rel = _bound(root, row.get("attribution_evidence"), f"{wid} attribution")
    if attribution_rel != f"sources/{wid}/LIB-062.README.md":
        raise PipelineError(f"{wid} attribution path differs")
    attribution_text = attribution_path.read_text(encoding="utf-8")
    if (PROVIDER_URL not in attribution_text or member_rel not in attribution_text
            or "Unlicense" not in attribution_text):
        raise PipelineError(f"{wid} attribution artifact omits provider or member")
    if row.get("provider") != PROVIDER or row.get("url") != PROVIDER_URL:
        raise PipelineError(f"{wid} acquisition provider/URL differs from retained evidence")
    if row.get("media_type") != "application/json" or row.get("edition_title") != "Retained Creeds.json electronic witness":
        raise PipelineError(f"{wid} JSON media or electronic witness title differs")
    scope = row.get("source_scope")
    if not isinstance(scope, str) or source["path"] not in scope:
        raise PipelineError(f"{wid} source scope does not identify exact JSON member")
    retained = [{"path": source["path"], "bytes": source["raw_bytes"],
                 "sha256": source["raw_sha256"], "media_type": "application/json", "scope": scope}]
    source_fields = {"source_path": source["path"], "source_bytes": source["raw_bytes"],
                     "source_sha256": source["raw_sha256"], "source_scope": scope}
    evidence = [preflight_rel, packet_rel, census["path"], source["path"], terms["path"], attribution_rel]
    staged_files = [preflight_rel, packet_rel, census["path"], attribution_rel]
    return retained, source_fields, evidence, staged_files
