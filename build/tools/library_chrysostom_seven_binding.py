"""Bind seven Chrysostom work identities to exact NPNF XML div1 children."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file


EVIDENCE = "plans/2026-09-22-source-preflight/chrysostom-npnf110-114-child-scope-20260926.json"
MANIFEST = "sources/structured-text/chrysostom-npnf110-111-112-114/npnf-chrysostom.source-manifest.json"


def _bound(root: Path, reference: dict[str, Any], label: str) -> Path:
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
            or not isinstance(reference["sha256"], str)):
        raise PipelineError(f"{label} path/hash binding missing")
    path = resolve_repo_path(root, reference["path"])
    if not path.is_file() or sha256_file(path) != reference["sha256"]:
        raise PipelineError(f"{label} bytes changed: {reference['path']}")
    return path


def bind_chrysostom_seven(
    root: Path, row: dict[str, Any], work: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    """Check profile-wide child coverage and one work's source-bound scope."""
    wid = work["work_id"]
    child_ref = row.get("chrysostom_child_evidence")
    if not isinstance(child_ref, dict) or child_ref.get("path") != EVIDENCE:
        raise PipelineError(f"{wid} Chrysostom child evidence missing")
    evidence = json.loads(_bound(root, child_ref, f"{wid} child evidence").read_text(encoding="utf-8"))
    if (evidence.get("contract") != "ocd-chrysostom-seven-child-scope-v1"
            or evidence.get("source_manifest") != row.get("source_manifest")
            or row.get("source_manifest", {}).get("path") != MANIFEST):
        raise PipelineError(f"{wid} Chrysostom source manifest binding differs")
    manifest = json.loads(_bound(root, evidence["source_manifest"], f"{wid} manifest").read_text(encoding="utf-8"))
    if (manifest.get("contract") != "ocd-source-manifest-v1"
            or manifest.get("source_id") != "ccel-npnf-chrysostom-110-111-112-114-retained-xml"):
        raise PipelineError("Chrysostom manifest identity differs")
    authorities = manifest.get("authorities", [])
    profiles = [item for item in authorities if item.get("role") == "complete-source-feature-profile"]
    if (len(profiles) != 1 or evidence.get("profile")
            != {"path": profiles[0]["path"], "sha256": profiles[0]["sha256"]}):
        raise PipelineError("Chrysostom profile binding differs")
    profile = json.loads(_bound(root, evidence["profile"], "Chrysostom profile").read_text(encoding="utf-8"))
    if (profile.get("contract") != "ocd-npnf-chrysostom-reconstruction-profile-v1"
            or profile.get("assigned_work_count") != 7):
        raise PipelineError("Chrysostom profile scope differs")
    children = evidence.get("children")
    if not isinstance(children, list) or len(children) != 7:
        raise PipelineError("Chrysostom seven-child census differs")
    by_work = {item.get("work_id"): item for item in children}
    locators = {(item.get("source", {}).get("path"), item.get("div1_id")) for item in children}
    expected = {(item["path"], child_id) for item in profile["source_members"]
                for child_id in item["assigned_div1"]}
    if (len(by_work) != 7 or len(locators) != 7 or locators != expected
            or {item["path"] for item in profile["source_members"]}
            != {item["path"] for item in authorities if item.get("role") == "primary-source"}):
        raise PipelineError("Chrysostom child locators differ from complete profile")
    member = by_work.get(wid)
    if member is None:
        raise PipelineError(f"{wid} has no assigned Chrysostom child")
    source = row.get("primary_source")
    if (source not in [item for item in authorities if item.get("role") == "primary-source"]
            or member["source"] != {key: source[key] for key in ("path", "bytes", "sha256")}
            or not any(all(item.get(key) == source[key] for key in ("path", "bytes", "sha256"))
                       for item in profile["source_members"])):
        raise PipelineError(f"{wid} source differs from manifest/profile child binding")
    source_path = resolve_repo_path(root, source["path"])
    if source_path.stat().st_size != source["bytes"] or sha256_file(source_path) != source["sha256"]:
        raise PipelineError(f"{wid} retained XML bytes changed")
    config_ref = row.get("config")
    config_path = _bound(root, config_ref, f"{wid} config")
    config_auth = [item for item in authorities if item.get("role") == "local-metadata-claim-evidence"
                   and item.get("path") == config_ref["path"]]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (len(config_auth) != 1 or config_auth[0]["sha256"] != config_ref["sha256"]
            or config.get("resource_id") != wid or config.get("title") != work["title"]
            or config.get("source_hash") != "sha256:" + source["sha256"]
            or config.get("source_url") != row.get("url")
            or config.get("language") != row.get("language") or row.get("language") != "en"
            or row.get("media_type") != "application/xml"):
        raise PipelineError(f"{wid} config/identity/source binding differs")
    metadata_ref = row.get("metadata_evidence")
    metadata_path = _bound(root, metadata_ref, f"{wid} metadata")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (metadata_ref["path"] != f"metadata/source-evidence/catalog/{wid}.json"
            or metadata_ref["path"] not in work.get("evidence", [])
            or metadata.get("subject") != {"id": wid, "kind": "catalog"}
            or source["sha256"] not in json.dumps(metadata)):
        raise PipelineError(f"{wid} source metadata evidence differs")
    try:
        xml = etree.parse(str(source_path), etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"{wid} retained XML cannot be parsed: {exc}") from exc
    found = xml.xpath("/ThML/ThML.body//div1[@id=$identity]", identity=member["div1_id"])
    header = xml.getroot().find("./ThML.head/electronicEdInfo/DC")
    if len(found) != 1 or header is None:
        raise PipelineError(f"{wid} retained div1 or volume header missing")
    titles = [" ".join("".join(node.itertext()).split()) for node in header.findall("DC.Title")]
    rights = [" ".join("".join(node.itertext()).split()) for node in header.findall("DC.Rights")]
    if (found[0].get("title") != member["child_title"]
            or not titles or titles[0] != member["volume_title"]
            or rights != [member["source_rights_label"]]
            or rights != ["Public Domain"]):
        raise PipelineError(f"{wid} retained div1 title or header rights differs")
    locator = source["path"] + "#" + member["div1_id"]
    containing = {"title": member["volume_title"], "locator": locator,
                  "evidence": [EVIDENCE, metadata_ref["path"], locator]}
    scope = (f"Complete acquired XML volume {source['path']}; work-specific div1 locator {locator} "
             "is recorded in edition.containing_source and does not establish accepted child text.")
    warnings = row.get("warnings")
    if (row.get("containing_source") != containing or row.get("source_scope") != scope
            or not isinstance(warnings, list)
            or not all(isinstance(value, str) for value in warnings)
            or not all(term in " ".join(warnings) for term in ("CCEL", "rights", "contributor", "footnotes"))):
        raise PipelineError(f"{wid} child scope or rights warnings differ")
    support = [item for item in authorities if item.get("role") in
               {"source-attribution-readme", "source-rights-evidence"}]
    if len(support) != 2:
        raise PipelineError("Chrysostom CCEL attribution/permission evidence missing")
    for item in support:
        support_path = resolve_repo_path(root, item["path"])
        if (not support_path.is_file() or support_path.stat().st_size != item["bytes"]
                or sha256_file(support_path) != item["sha256"]):
            raise PipelineError("Chrysostom CCEL rights evidence changed")
    evidence_paths = [MANIFEST, evidence["profile"]["path"], EVIDENCE, config_ref["path"],
                      metadata_ref["path"], source["path"], *(item["path"] for item in support)]
    retained = [{"path": source["path"], "bytes": source["bytes"],
                 "sha256": source["sha256"], "media_type": "application/xml", "scope": scope}]
    source_fields = {"source_path": source["path"], "source_bytes": source["bytes"],
                     "source_sha256": source["sha256"], "source_scope": scope}
    packet_evidence = [EVIDENCE, evidence["profile"]["path"], *(item["path"] for item in support)]
    return retained, source_fields, evidence_paths, packet_evidence
