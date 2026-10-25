"""Bind one work to its retained XML member in a CCEL reconstruction cohort."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file


def _read_bound_authority(root: Path, manifest: dict[str, Any], role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    matches = [item for item in manifest["authorities"] if isinstance(item, dict) and item.get("role") == role]
    if len(matches) != 1:
        raise PipelineError(f"CCEL cohort requires one {role} authority")
    item = matches[0]
    path = resolve_repo_path(root, item["path"])
    if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
        raise PipelineError(f"CCEL cohort {role} authority changed: {item['path']}")
    return item, json.loads(path.read_text(encoding="utf-8"))


def bind_ccel_cohort_member(root: Path, row: dict[str, Any], work: dict[str, Any],
                            config: dict[str, Any], manifest: dict[str, Any],
                            source: dict[str, Any]) -> list[str]:
    """Return bound evidence paths after checking the whole ten-member map.

    The source-set and profile identify each work's independent XML. This
    checks acquisition identity only; a ThML body is not thereby accepted TEI.
    """
    if manifest.get("source_id") != "ccel-lib031-retained-thml-source-set":
        raise PipelineError("CCEL cohort source manifest identity differs")
    source_set_item, source_set = _read_bound_authority(root, manifest, "source-member-census")
    if row.get("cohort_source_set") != {"path": source_set_item["path"], "sha256": source_set_item["sha256"]}:
        raise PipelineError("CCEL cohort packet source set differs from manifest")
    profile_item, profile = _read_bound_authority(root, manifest, "complete-source-feature-profile")
    if (source_set.get("contract") != "ocd-retained-source-set-v1"
            or profile.get("contract") != "ocd-lib031-reconstruction-profile-v1"):
        raise PipelineError("CCEL cohort source set or profile contract differs")
    members = source_set.get("members")
    works = profile.get("works")
    if (not isinstance(members, list) or len(members) != 10
            or source_set.get("census", {}).get("included") != 10
            or source_set.get("census", {}).get("excluded") != 0
            or not isinstance(works, list) or len(works) != 10
            or profile.get("work_order") != [member.get("work_id") for member in members]):
        raise PipelineError("CCEL cohort ten-member source census differs")
    primaries = [item for item in manifest["authorities"] if isinstance(item, dict) and item.get("role") == "primary-source"]
    primary_by_path = {item.get("path"): item for item in primaries}
    if len(primary_by_path) != len(primaries) or len(primaries) != len(members):
        raise PipelineError("CCEL cohort primary source set is incomplete or duplicated")
    member_by_work: dict[str, dict[str, Any]] = {}
    for member in members:
        wid = member.get("work_id")
        rel = member.get("logical_path")
        if (not isinstance(wid, str) or wid in member_by_work
                or not isinstance(rel, str) or not rel.startswith("ccel/")
                or not rel.endswith(".xml") or member.get("disposition") != "include"):
            raise PipelineError("CCEL cohort member identity or disposition differs")
        expected = {"path": "raw/" + rel, "bytes": member.get("bytes"), "sha256": member.get("sha256")}
        primary = primary_by_path.get(expected["path"])
        if primary is None or any(primary.get(key) != value for key, value in expected.items()):
            raise PipelineError(f"{wid} source-set member differs from manifest primary")
        member_by_work[wid] = member
    if set(primary_by_path) != {"raw/" + member["logical_path"] for member in members}:
        raise PipelineError("CCEL cohort has an unassigned primary source")
    profile_by_work = {item.get("work_id"): item for item in works}
    if len(profile_by_work) != 10 or set(profile_by_work) != set(member_by_work):
        raise PipelineError("CCEL cohort profile work identities differ")
    wid = work["work_id"]
    member = member_by_work.get(wid)
    if member is None or source != primary_by_path["raw/" + member["logical_path"]]:
        raise PipelineError(f"{wid} proposed source differs from its cohort member")
    profile_work = profile_by_work[wid]
    if (config.get("resource_id") != wid or profile_work.get("title") != work["title"]
            or config.get("title") != work["title"]
            or config.get("source_url") != profile_work.get("source_url")
            or config.get("source_hash") != "sha256:" + member["sha256"]
            or profile_work.get("source_sha256") != member["sha256"]):
        raise PipelineError(f"{wid} config, work, profile, and source hash differ")
    source_path = resolve_repo_path(root, source["path"])
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        tree = etree.parse(str(source_path), parser)
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"{wid} retained XML cannot be parsed: {exc}") from exc
    root_element = tree.getroot()
    if root_element.tag != "ThML" or len(root_element.findall("ThML.head")) != 1 or len(root_element.findall("ThML.body")) != 1:
        raise PipelineError(f"{wid} retained XML lacks one ThML head and body")
    edition = root_element.find("./ThML.head/electronicEdInfo")
    if edition is None:
        raise PipelineError(f"{wid} retained XML lacks electronic edition identity")
    parts = Path(member["logical_path"]).parts
    expected_ids = {"publisherID": "ccel", "authorID": parts[1], "bookID": Path(parts[-1]).stem}
    if any((edition.findtext(name) or "").strip() != value for name, value in expected_ids.items()):
        raise PipelineError(f"{wid} retained XML edition identity differs from member path")
    titles = [" ".join("".join(node.itertext()).split())
              for node in edition.findall("./DC/DC.Title")]
    if not any(title == work["title"] or title.startswith(work["title"] + " [") for title in titles):
        raise PipelineError(f"{wid} retained XML title differs from work identity")
    return [source_set_item["path"], profile_item["path"]]
