"""Bind three Basil identities to the assigned children of retained NPNF2-08."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file


EVIDENCE = "plans/2026-09-22-source-preflight/basil-npnf208-child-scope-20260926.json"
MANIFEST = "sources/structured-text/npnf2-lib046/npnf2-lib046.source-manifest.json"


def _bound(root: Path, ref: Any, label: str) -> Path:
    if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
            or not isinstance(ref["path"], str) or not isinstance(ref["sha256"], str)):
        raise PipelineError(f"{label} exact path/hash binding missing")
    path = resolve_repo_path(root, ref["path"])
    if not path.is_file() or sha256_file(path) != ref["sha256"]:
        raise PipelineError(f"{label} bytes changed: {ref['path']}")
    return path


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def bind_basil_three(
    root: Path, row: dict[str, Any], work: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    """Validate the full child census before binding one acquisition to a div1."""
    wid = work["work_id"]
    evidence_ref = row.get("basil_child_evidence")
    if not isinstance(evidence_ref, dict) or evidence_ref.get("path") != EVIDENCE:
        raise PipelineError(f"{wid} Basil child evidence missing")
    evidence = _load(_bound(root, evidence_ref, f"{wid} Basil child evidence"))
    if (evidence.get("contract") != "ocd-basil-three-child-scope-v1"
            or row.get("source_manifest") != evidence.get("source_manifest")
            or row["source_manifest"].get("path") != MANIFEST):
        raise PipelineError(f"{wid} Basil manifest binding differs")
    manifest = _load(_bound(root, evidence["source_manifest"], f"{wid} manifest"))
    if (manifest.get("contract") != "ocd-source-manifest-v1"
            or manifest.get("source_id") != "ccel-npnf2-lib046-basil-vii-viii-ix"):
        raise PipelineError(f"{wid} Basil manifest identity differs")
    authorities = manifest.get("authorities", [])
    profiles = [item for item in authorities if item.get("role") == "complete-source-feature-profile"]
    sources = [item for item in authorities if item.get("role") == "primary-source"]
    if (len(profiles) != 1 or len(sources) != 1
            or evidence.get("profile") != {"path": profiles[0]["path"], "sha256": profiles[0]["sha256"]}
            or evidence.get("source") != {key: sources[0][key] for key in ("path", "bytes", "sha256")}):
        raise PipelineError(f"{wid} Basil source/profile binding differs")
    profile = _load(_bound(root, evidence["profile"], f"{wid} profile"))
    source = row.get("primary_source")
    if (profile.get("contract") != "ocd-npnf2-reconstruction-profile-v1"
            or profile.get("profile_id") != "basil-of-caesarea-npnf2-three-work-v1"
            or source != sources[0] or any(
                profile.get("source_member", {}).get(key) != evidence["source"][key]
                for key in ("path", "bytes", "sha256"))
            or row.get("media_type") != "application/xml"):
        raise PipelineError(f"{wid} Basil retained XML differs")
    children = evidence.get("children")
    if not isinstance(children, list) or len(children) != 3:
        raise PipelineError("Basil three-child census differs")
    assigned = profile.get("assigned_roots")
    if (not isinstance(assigned, list) or len(assigned) != 3
            or [(item.get("div1_id"), item.get("work_id")) for item in children]
            != [(item[1], item[2]) for item in assigned]
            or assigned != manifest.get("scope", {}).get("assigned_roots_in_source_order")):
        raise PipelineError("Basil assigned roots differ from source profile")
    envelope = profile.get("source_envelope", {})
    if (envelope.get("assigned_top_level_div1_ids_in_order") != ["vii", "viii", "ix"]
            or envelope.get("top_level_div1_ids_in_order") !=
            ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
            or envelope.get("excluded_top_level_div1_ids") !=
            manifest.get("scope", {}).get("excluded_top_level_roots")):
        raise PipelineError("Basil full source envelope differs")
    members = [item for item in children if item["work_id"] == wid]
    if len(members) != 1:
        raise PipelineError(f"{wid} Basil child assignment missing")
    member = members[0]
    source_path = resolve_repo_path(root, source["path"])
    if (not source_path.is_file() or source_path.stat().st_size != source["bytes"]
            or sha256_file(source_path) != source["sha256"]):
        raise PipelineError(f"{wid} Basil retained XML bytes changed")
    try:
        xml = etree.parse(str(source_path), etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"{wid} Basil XML cannot be inspected: {exc}") from exc
    roots = xml.xpath("/ThML/ThML.body/div1")
    if ([(element.get("id")) for element in roots] != envelope["top_level_div1_ids_in_order"]
            or {element.get("id"): element.get("title") for element in roots}
            .get(member["div1_id"]) != member["child_title"]
            or envelope.get("assigned_root_titles", {}).get(member["div1_id"]) != member["child_title"]):
        raise PipelineError(f"{wid} Basil XML child boundary or title changed")
    header = xml.getroot().find("./ThML.head/electronicEdInfo/DC")
    if header is None:
        raise PipelineError("Basil XML electronic header missing")
    header_title = header.findtext("DC.Title")
    rights = [" ".join("".join(node.itertext()).split()) for node in header.findall("DC.Rights")]
    published = xml.xpath("//*[local-name()='published']")
    if (header_title != evidence.get("volume_title") or rights != ["Public Domain"]
            or len(published) != 1 or " ".join("".join(published[0].itertext()).split())
            != evidence.get("printed_source_notice")):
        raise PipelineError("Basil XML header, rights, or print notice changed")
    config_ref = row.get("config")
    config = _load(_bound(root, config_ref, f"{wid} config"))
    config_auth = [item for item in authorities if item.get("path") == config_ref["path"]]
    if (len(config_auth) != 1 or config_auth[0]["sha256"] != config_ref["sha256"]
            or config.get("resource_id") != wid or config.get("title") != work["title"]
            or config.get("source_file") != source["path"]
            or config.get("source_hash") != "sha256:" + source["sha256"]
            or config.get("source_url") != row.get("url")
            or config.get("language") != row.get("language") or row.get("language") != "en"):
        raise PipelineError(f"{wid} Basil config/source identity differs")
    metadata_ref = row.get("metadata_evidence")
    metadata = _load(_bound(root, metadata_ref, f"{wid} metadata"))
    if (metadata_ref["path"] != f"metadata/source-evidence/catalog/{wid}.json"
            or metadata_ref["path"] not in work.get("evidence", [])
            or metadata.get("subject") != {"id": wid, "kind": "catalog"}
            or source["sha256"] not in json.dumps(metadata)):
        raise PipelineError(f"{wid} Basil catalog metadata differs")
    locator = source["path"] + "#" + member["div1_id"]
    containing = {"title": evidence["volume_title"], "locator": locator,
                  "evidence": [EVIDENCE, metadata_ref["path"], locator]}
    scope = (f"Complete acquired XML volume {source['path']}; work-specific div1 locator {locator} "
             "is recorded in edition.containing_source and does not establish accepted child text.")
    warnings = row.get("warnings")
    if (row.get("containing_source") != containing or row.get("source_scope") != scope
            or not isinstance(warnings, list) or not all(isinstance(value, str) for value in warnings)
            or not all(word in " ".join(warnings) for word in
                       ("CCEL", "rights", "printed", "contributor", "accepted"))):
        raise PipelineError(f"{wid} Basil child scope or warnings differ")
    support = [item for item in authorities if item.get("path") in
               {"sources/structured-text/npnf2-lib046/README.source.md", "docs/sources/ccel-permission.md"}]
    if len(support) != 2:
        raise PipelineError("Basil attribution and permission evidence missing")
    for item in support:
        path = resolve_repo_path(root, item["path"])
        if (not path.is_file() or path.stat().st_size != item["bytes"]
                or sha256_file(path) != item["sha256"]):
            raise PipelineError("Basil attribution or permission bytes changed")
    retained = [{"path": source["path"], "bytes": source["bytes"],
                 "sha256": source["sha256"], "media_type": "application/xml", "scope": scope}]
    fields = {"source_path": source["path"], "source_bytes": source["bytes"],
              "source_sha256": source["sha256"], "source_scope": scope}
    evidence_paths = [MANIFEST, evidence["profile"]["path"], EVIDENCE, config_ref["path"],
                      metadata_ref["path"], source["path"], *(item["path"] for item in support)]
    packet_evidence = [EVIDENCE, evidence["profile"]["path"], *(item["path"] for item in support)]
    return retained, fields, evidence_paths, packet_evidence
