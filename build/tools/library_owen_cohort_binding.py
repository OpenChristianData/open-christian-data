"""Bind one Owen work to its exact retained CCEL XML in LIB-050/051/052."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file


def _header_text(node: etree._Element | None) -> str:
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def bind_owen_cohort_member(
    root: Path,
    row: dict[str, Any],
    work: dict[str, Any],
    config: dict[str, Any],
    manifest: dict[str, Any],
    source: dict[str, Any],
) -> list[str]:
    """Verify the cohort map and the member's source/header identity.

    This establishes an acquired electronic witness only. The existing
    reconstruction profile and source manifest remain independent authority
    for what a later TEI candidate must account for.
    """
    source_id = manifest.get("source_id")
    if source_id not in {
        "john-owen-lib050-ten-retained-ccel-xml",
        "john-owen-lib051-ten-retained-ccel-xml",
        "john-owen-lib052-ten-retained-ccel-xml",
    }:
        raise PipelineError("Owen source manifest identity differs")
    authorities = manifest.get("authorities")
    if not isinstance(authorities, list):
        raise PipelineError("Owen source manifest authorities missing")
    profiles = [item for item in authorities if isinstance(item, dict)
                and item.get("role") == "complete-source-feature-profile"]
    if len(profiles) != 1:
        raise PipelineError("Owen cohort requires one pinned profile")
    profile_ref = {"path": profiles[0]["path"], "sha256": profiles[0]["sha256"]}
    if row.get("cohort_source_set") != profile_ref:
        raise PipelineError("Owen packet profile differs from manifest")
    profile_path = resolve_repo_path(root, profile_ref["path"])
    if (not profile_path.is_file() or profile_path.stat().st_size != profiles[0]["bytes"]
            or sha256_file(profile_path) != profile_ref["sha256"]):
        raise PipelineError("Owen pinned profile bytes differ")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    cohort = source_id.split("-")[2]
    if (profile.get("contract") != f"ocd-john-owen-{cohort}-profile-v1"
            or not isinstance(profile.get("works"), list)
            or len(profile["works"]) != 10):
        raise PipelineError("Owen cohort profile contract or work count differs")
    adjacent = profile.get("adjacent_retained_member_accounting")
    if (not isinstance(adjacent, list) or len(adjacent) != 32
            or len({item.get("path") for item in adjacent if isinstance(item, dict)}) != 32):
        raise PipelineError("Owen adjacent retained-source census differs")
    works = {item.get("work_id"): item for item in profile["works"]}
    if len(works) != 10:
        raise PipelineError("Owen cohort profile has duplicate work identity")
    primary = {item.get("name"): item for item in authorities if isinstance(item, dict)
               and item.get("role") == "primary-source"}
    configs = {item.get("name"): item for item in authorities if isinstance(item, dict)
               and item.get("role") == "work-identity-config"}
    if len(primary) != 10 or len(configs) != 10:
        raise PipelineError("Owen cohort authority census differs")
    paths: set[str] = set()
    for member in profile["works"]:
        if not isinstance(member, dict):
            raise PipelineError("Owen cohort member is not an object")
        expected = primary.get(member.get("authority_name"))
        identity = configs.get(member.get("identity_authority_name"))
        if (expected is None or identity is None
                or any(member.get(key) != expected.get(key) for key in ("path", "bytes", "sha256"))
                or identity.get("path") != f"sources/structured-text/{cohort}-john-owen/work-bindings/{member.get('work_id')}/config.json"
                or member.get("path") in paths):
            raise PipelineError("Owen profile member differs from manifest authority")
        paths.add(member["path"])
    adjacent_by_path = {item["path"]: item for item in adjacent}
    for member in profile["works"]:
        neighbor = adjacent_by_path.get(member["path"])
        if (neighbor is None or neighbor.get("bytes") != member["bytes"]
                or neighbor.get("sha256") != member["sha256"]
                or neighbor.get("disposition") != f"included: LIB-{cohort[-3:]} {member['work_id']}"):
            raise PipelineError("Owen adjacent source disposition differs")
    if paths != {item["path"] for item in primary.values()}:
        raise PipelineError("Owen profile omits a primary source")
    wid = work["work_id"]
    member = works.get(wid)
    if (member is None or config != {"contract": "ocd-reconstruction-work-identity-v1", "work_id": wid}
            or work["title"] != member["title"]
            or source != primary[member["authority_name"]]):
        raise PipelineError(f"{wid} Owen work, config, and source differ")
    source_path = resolve_repo_path(root, source["path"])
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        xml = etree.parse(str(source_path), parser)
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"{wid} Owen source XML cannot be parsed: {exc}") from exc
    root_element = xml.getroot()
    if (root_element.tag != "ThML" or len(root_element.findall("ThML.head")) != 1
            or len(root_element.findall("ThML.body")) != 1):
        raise PipelineError(f"{wid} Owen XML lacks one ThML head and body")
    edition = root_element.find("./ThML.head/electronicEdInfo")
    if edition is None:
        raise PipelineError(f"{wid} Owen XML lacks electronic edition identity")
    book_id = Path(source["path"]).stem
    if (edition.findtext("publisherID") != "ccel"
            or edition.findtext("authorID") != "owen"
            or edition.findtext("bookID") != book_id):
        raise PipelineError(f"{wid} Owen XML CCEL identifiers differ")
    titles = [_header_text(node) for node in edition.findall("./DC/DC.Title")]
    if not titles or not titles[0]:
        raise PipelineError(f"{wid} Owen XML has no source title")
    authors = [_header_text(node) for node in edition.findall("./DC/DC.Creator")
               if node.get("sub") == "Author"]
    language = edition.find('./DC/DC.Language[@scheme="ISO639-3"]')
    if ("John Owen" not in authors or _header_text(language) != "eng"
            or row.get("language") != "en"):
        raise PipelineError(f"{wid} Owen XML author or language differs")
    source_identifier = edition.find('./DC/DC.Identifier[@scheme="URL"]')
    expected_url = "https://www.ccel.org" + _header_text(source_identifier)
    if (source_identifier is None or _header_text(source_identifier) != f"/ccel/owen/{book_id}.html"
            or row.get("url") != expected_url):
        raise PipelineError(f"{wid} Owen source URL differs from XML identifier")
    warnings = row.get("warnings")
    if not isinstance(warnings, list) or not all(isinstance(w, str) for w in warnings):
        raise PipelineError(f"{wid} Owen rights warnings missing")
    if not any("CCEL" in warning and "rights" in warning.lower() for warning in warnings):
        raise PipelineError(f"{wid} Owen CCEL rights warning missing")
    status = _header_text(edition.find("status"))
    if "not been proof-read" in status and not any("not proofread" in warning for warning in warnings):
        raise PipelineError(f"{wid} Owen source proofreading warning missing")
    if not status and not any("proofreading status" in warning for warning in warnings):
        raise PipelineError(f"{wid} Owen absent proofreading-status warning missing")
    editorial = _header_text(edition.find("editorialComments"))
    if "AGES" in editorial and not any("AGES" in warning for warning in warnings):
        raise PipelineError(f"{wid} Owen AGES source warning missing")
    if work["title"] not in titles and not any("title differs" in warning for warning in warnings):
        raise PipelineError(f"{wid} Owen XML/catalog title warning missing")
    readmes = [item for item in authorities if isinstance(item, dict)
               and item.get("role") == "source-attribution-readme"]
    if len(readmes) != 1:
        raise PipelineError("Owen CCEL attribution document missing")
    readme = readmes[0]
    readme_path = resolve_repo_path(root, readme["path"])
    if (not readme_path.is_file() or readme_path.stat().st_size != readme["bytes"]
            or sha256_file(readme_path) != readme["sha256"]):
        raise PipelineError("Owen CCEL attribution document changed")
    rights = readme_path.read_text(encoding="utf-8")
    if "CCEL.org" not in rights or "AGES" not in rights or "credit" not in rights:
        raise PipelineError("Owen CCEL/AGES rights guidance differs")
    return [profile_ref["path"], readme["path"]]
