"""Bind LIB-054 work identities to their ten exact retained CCEL XML files."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file


_MANIFEST_ID = "lib054-ten-retained-ccel-puritan-xml"
_PROFILE_ID = "lib054-ten-retained-ccel-xml-v1"
_FRAGMENT_ANCHORS = {
    "edwards-distinguishing-marks": "vii",
    "edwards-history-of-redemption": "xii",
}


def _one_authority(manifest: dict[str, Any], role: str) -> dict[str, Any]:
    matches = [item for item in manifest["authorities"]
               if isinstance(item, dict) and item.get("role") == role]
    if len(matches) != 1:
        raise PipelineError(f"LIB-054 needs exactly one {role} authority")
    return matches[0]


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def bind_lib054_member(root: Path, row: dict[str, Any], work: dict[str, Any],
                       config: dict[str, Any], manifest: dict[str, Any],
                       source: dict[str, Any]) -> list[str]:
    """Check cohort census and one file's identity; make no TEI or rights claim."""
    wid = work["work_id"]
    if manifest.get("source_id") != _MANIFEST_ID:
        raise PipelineError("LIB-054 source manifest identity differs")
    profile_item = _one_authority(manifest, "complete-source-feature-profile")
    profile_ref = {"path": profile_item["path"], "sha256": profile_item["sha256"]}
    if row.get("cohort_source_set") != profile_ref:
        raise PipelineError(f"{wid} LIB-054 profile binding differs")
    profile_path = resolve_repo_path(root, profile_item["path"])
    if (not profile_path.is_file() or profile_path.stat().st_size != profile_item["bytes"]
            or sha256_file(profile_path) != profile_item["sha256"]):
        raise PipelineError("LIB-054 profile bytes/hash differ")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    members = profile.get("works")
    if (profile.get("contract") != "ocd-ccel-puritan-lib054-profile-v1"
            or profile.get("profile_id") != _PROFILE_ID
            or not isinstance(members, list) or len(members) != 10):
        raise PipelineError("LIB-054 profile contract or ten-work census differs")
    by_work = {member.get("work_id"): member for member in members if isinstance(member, dict)}
    if len(by_work) != 10 or wid not in by_work:
        raise PipelineError(f"{wid} LIB-054 profile work identity absent or duplicated")
    primaries = [item for item in manifest["authorities"]
                 if isinstance(item, dict) and item.get("role") == "primary-source"]
    configs = [item for item in manifest["authorities"]
               if isinstance(item, dict) and item.get("role") == "work-identity-config"]
    primary_by_name = {item.get("name"): item for item in primaries}
    config_by_path = {item.get("path"): item for item in configs}
    expected_sources = {member.get("authority_name") for member in members}
    expected_configs = {
        f"sources/structured-text/lib054-ccel-puritan/work-bindings/{member['work_id']}/config.json"
        for member in members
    }
    if (len(primaries) != 10 or len(primary_by_name) != 10
            or set(primary_by_name) != expected_sources
            or len(configs) != 10 or len(config_by_path) != 10
            or set(config_by_path) != expected_configs):
        raise PipelineError("LIB-054 manifest source/config census differs from profile")
    for member in members:
        primary = primary_by_name[member["authority_name"]]
        if (primary.get("path"), primary.get("bytes"), primary.get("sha256")) != (
                member.get("source_path"), member.get("bytes"), member.get("sha256")):
            raise PipelineError(f"{member['work_id']} LIB-054 source differs from profile")
    member = by_work[wid]
    config_rel = f"sources/structured-text/lib054-ccel-puritan/work-bindings/{wid}/config.json"
    if (config_rel not in config_by_path
            or config.get("contract") != "ocd-reconstruction-work-identity-v1"):
        raise PipelineError(f"{wid} LIB-054 config identity differs")
    if (config.get("work_id") != wid or member.get("title") != work["title"]
            or row.get("url") != member.get("source_url")
            or row.get("language") != "en"
            or source != primary_by_name[member["authority_name"]]):
        raise PipelineError(f"{wid} LIB-054 work, URL, language, or source differs")
    source_path = resolve_repo_path(root, source["path"])
    if (not source_path.is_file() or source_path.stat().st_size != source["bytes"]
            or sha256_file(source_path) != source["sha256"]):
        raise PipelineError(f"{wid} LIB-054 retained XML bytes/hash differ")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        document = etree.parse(str(source_path), parser)
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"{wid} LIB-054 retained XML cannot be parsed: {exc}") from exc
    xml = document.getroot()
    heads = xml.findall("ThML.head")
    bodies = xml.findall("ThML.body")
    if (xml.tag != "ThML" or len(bodies) != 1
            or sum(isinstance(element.tag, str) for element in xml.iter()) != member["element_count"]):
        raise PipelineError(f"{wid} LIB-054 ThML envelope or element census differs")
    rights = [" ".join("".join(element.itertext()).split()) for element in xml.findall(".//DC.Rights")]
    if not any(rights) and not any("rights" in warning.casefold() for warning in row.get("warnings", [])):
        raise PipelineError(f"{wid} LIB-054 missing source rights warning")
    anchor = _FRAGMENT_ANCHORS.get(wid)
    if anchor is None:
        if len(heads) != 1:
            raise PipelineError(f"{wid} LIB-054 full XML lacks its ThML head")
        electronic = heads[0].find("electronicEdInfo")
        parts = Path(source["path"]).parts
        if electronic is None or any((electronic.findtext(name) or "").strip() != value for name, value in {
                "publisherID": "ccel", "authorID": parts[2], "bookID": Path(parts[-1]).stem}.items()):
            raise PipelineError(f"{wid} LIB-054 electronic edition ID differs from retained XML")
        titles = [_normalized("".join(node.itertext()))
                  for node in electronic.findall("./DC/DC.Title")]
        expected_title = _normalized(work["title"])
        if wid == "bunyan-grace-abounding":
            expected_title = "grace abounding"
        if not any(title.startswith(expected_title) for title in titles):
            raise PipelineError(f"{wid} LIB-054 XML title differs from work identity")
    else:
        top_divisions = bodies[0].findall("div1")
        if (heads or len(top_divisions) != 1 or len(bodies[0]) != 1
                or top_divisions[0].get("id") != anchor
                or not row["url"].endswith("#" + anchor)):
            raise PipelineError(f"{wid} LIB-054 exact fragment boundary differs")
        title = _normalized(top_divisions[0].get("title") or "")
        expected_title = _normalized(work["title"])
        if expected_title.startswith("the "):
            expected_title = expected_title[4:]
        if expected_title not in title:
            raise PipelineError(f"{wid} LIB-054 fragment title differs from work identity")
        if ("fragment" not in row.get("source_scope", "").casefold()
                or "unverified" not in " ".join(row.get("warnings", [])).casefold()):
            raise PipelineError(f"{wid} LIB-054 fragment provenance warning missing")
    if source["path"] not in row.get("source_scope", ""):
        raise PipelineError(f"{wid} LIB-054 source scope does not name exact retained XML")
    return [profile_item["path"]]
