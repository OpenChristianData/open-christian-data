"""Bind five LIB-028 work roots to three exact retained CCEL XML volumes."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file


SOURCE_ID = "ccel-schaff-npnf2-lib028-three-retained-xml-members"
BASE = "sources/structured-text/eusebius-ecclesiastical-history"


def _bound_authority(root: Path, manifest: dict[str, Any], role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = [item for item in manifest["authorities"]
               if isinstance(item, dict) and item.get("role") == role]
    if len(matches) != 1:
        raise PipelineError(f"LIB-028 needs exactly one {role} authority")
    item = matches[0]
    path = resolve_repo_path(root, item["path"])
    if (not path.is_file() or path.stat().st_size != item["bytes"]
            or sha256_file(path) != item["sha256"]):
        raise PipelineError(f"LIB-028 {role} bytes/hash differ: {item['path']}")
    return item, json.loads(path.read_text(encoding="utf-8"))


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def bind_lib028_member(root: Path, row: dict[str, Any], work: dict[str, Any],
                       config: dict[str, Any], manifest: dict[str, Any],
                       source: dict[str, Any]) -> list[str]:
    """Check exact source/member/root identity, without accepting reconstructed text."""
    wid = work["work_id"]
    if manifest.get("source_id") != SOURCE_ID:
        raise PipelineError("LIB-028 source manifest identity differs")
    source_set_item, source_set = _bound_authority(root, manifest, "retained-member-census")
    profile_item, profile = _bound_authority(root, manifest, "complete-source-feature-profile")
    if row.get("cohort_source_set") != {"path": source_set_item["path"], "sha256": source_set_item["sha256"]}:
        raise PipelineError(f"{wid} LIB-028 source-set packet binding differs")
    members = source_set.get("members")
    roots = profile.get("assigned_roots")
    if (source_set.get("contract") != "ocd-lib028-retained-source-set-v1"
            or source_set.get("unaccounted_members") != 0
            or not isinstance(members, list) or len(members) != 3
            or profile.get("contract") != "ocd-lib028-reconstruction-profile-v1"
            or profile.get("profile_id") != "lib028-five-church-histories-v1"
            or not isinstance(roots, list) or len(roots) != 5):
        raise PipelineError("LIB-028 source-set/profile census differs")
    primary = [item for item in manifest["authorities"]
               if isinstance(item, dict) and item.get("role") == "primary-source"]
    primary_by_path = {item.get("path"): item for item in primary}
    if len(primary) != 3 or len(primary_by_path) != 3:
        raise PipelineError("LIB-028 manifest primary source census differs")
    for member in members:
        rel = f"raw/ccel/schaff/{member.get('name')}"
        expected = {"path": rel, "bytes": member.get("bytes"), "sha256": member.get("sha256")}
        current = primary_by_path.get(rel)
        if member.get("disposition") != "include" or current is None or any(
                current.get(key) != value for key, value in expected.items()):
            raise PipelineError(f"LIB-028 retained member differs: {rel}")
    if set(primary_by_path) != {f"raw/ccel/schaff/{member['name']}" for member in members}:
        raise PipelineError("LIB-028 manifest has an unassigned primary source")
    binding_items = [item for item in manifest["authorities"]
                     if isinstance(item, dict) and item.get("role") == "exact-work-binding"]
    config_items = [item for item in manifest["authorities"]
                    if isinstance(item, dict) and item.get("role") == "local-metadata-claim-evidence"]
    bindings: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for item in binding_items:
        path = resolve_repo_path(root, item["path"])
        if (not path.is_file() or path.stat().st_size != item["bytes"]
                or sha256_file(path) != item["sha256"]):
            raise PipelineError(f"LIB-028 work binding changed: {item['path']}")
        binding = json.loads(path.read_text(encoding="utf-8"))
        member_id = binding.get("work_id")
        if (member_id in bindings or binding.get("contract") != "ocd-lib028-work-binding-v1"
                or binding.get("ticket") != "LIB-028"
                or binding.get("source_member") not in primary_by_path
                or binding.get("source_sha256") != primary_by_path[binding["source_member"]]["sha256"]
                or binding.get("disposition") != "complete-subtree-represented"
                or binding.get("accepted_ir") != "not_accepted"):
            raise PipelineError(f"LIB-028 work binding contract differs: {item['path']}")
        bindings[member_id] = item, binding
    if len(binding_items) != 5 or len(bindings) != 5 or len(config_items) != 5:
        raise PipelineError("LIB-028 five-work binding/config census differs")
    expected_roots = sorted([
        [Path(binding["source_member"]).stem, binding["source_root_id"], member_id]
        for member_id, (_, binding) in bindings.items()
    ])
    if sorted(roots) != expected_roots:
        raise PipelineError("LIB-028 profile work-root assignments differ")
    for item in config_items:
        path = resolve_repo_path(root, item["path"])
        if (not path.is_file() or path.stat().st_size != item["bytes"]
                or sha256_file(path) != item["sha256"]):
            raise PipelineError(f"LIB-028 work config changed: {item['path']}")
        config_id = json.loads(path.read_text(encoding="utf-8")).get("resource_id")
        if config_id not in bindings or item["path"] != f"sources/structured-text/{config_id}/config.json":
            raise PipelineError(f"LIB-028 work config identity differs: {item['path']}")
    if wid not in bindings:
        raise PipelineError(f"{wid} LIB-028 work absent from five-member source set")
    binding_item, binding = bindings[wid]
    if (source != primary_by_path[binding["source_member"]]
            or config.get("resource_id") != wid or config.get("title") != work["title"]
            or config.get("source_hash") != "sha256:" + source["sha256"]
            or config.get("source_url") != row.get("url")
            or config.get("language") != row.get("language")):
        raise PipelineError(f"{wid} LIB-028 work/config/source binding differs")
    metadata_ref = row.get("metadata_evidence")
    metadata_rel = f"metadata/source-evidence/catalog/{wid}.json"
    if (not isinstance(metadata_ref, dict) or metadata_ref.get("path") != metadata_rel
            or metadata_rel not in work["evidence"]):
        raise PipelineError(f"{wid} LIB-028 metadata evidence binding differs")
    metadata_path = resolve_repo_path(root, metadata_rel)
    if sha256_file(metadata_path) != metadata_ref.get("sha256"):
        raise PipelineError(f"{wid} LIB-028 metadata hash differs")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("subject") != {"id": wid, "kind": "catalog"}:
        raise PipelineError(f"{wid} LIB-028 metadata subject differs")
    locator = f"{source['path']}#{binding['source_root_id']}"
    containing = row.get("containing_source")
    if (not isinstance(containing, dict) or containing.get("locator") != locator
            or containing.get("title") != config.get("source_edition")
            or not isinstance(containing.get("evidence"), list)
            or not {metadata_rel, binding_item["path"], locator}.issubset(containing["evidence"])):
        raise PipelineError(f"{wid} LIB-028 containing-source identity differs")
    xml_path = resolve_repo_path(root, source["path"])
    if (not xml_path.is_file() or xml_path.stat().st_size != source["bytes"]
            or sha256_file(xml_path) != source["sha256"]):
        raise PipelineError(f"{wid} LIB-028 retained XML bytes/hash differ")
    try:
        tree = etree.parse(str(xml_path), etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"{wid} LIB-028 retained XML cannot be parsed: {exc}") from exc
    divs = tree.xpath("/ThML/ThML.body/div1[@id=$identity]", identity=binding["source_root_id"])
    selected = tree.xpath("/ThML/" + binding["source_root_selector"])
    if (len(divs) != 1 or len(selected) != 1 or divs[0] is not selected[0]
            or not isinstance(divs[0].get("title"), str)):
        raise PipelineError(f"{wid} LIB-028 source root/selector differs")
    if _norm(work["title"]) not in _norm(divs[0].get("title")):
        raise PipelineError(f"{wid} LIB-028 source title differs from work identity")
    expected_scope = (f"Complete acquired XML volume {source['path']}; work-specific locator {locator} "
                      "is recorded in edition.containing_source and does not establish accepted child text.")
    if row.get("source_scope") != expected_scope:
        raise PipelineError(f"{wid} LIB-028 source scope differs")
    warnings = " ".join(row.get("warnings", [])).casefold()
    if not all(term in warnings for term in ("ccel", "print", "rights", "accepted")):
        raise PipelineError(f"{wid} LIB-028 edition/rights limitations absent")
    return [source_set_item["path"], profile_item["path"], binding_item["path"], metadata_rel]
