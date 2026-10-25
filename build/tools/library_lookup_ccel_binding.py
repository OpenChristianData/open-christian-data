"""Bind the two lookup works to retained CCEL XML electronic witnesses."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError, sha256_file


PREFLIGHT = "plans/2026-09-22-source-preflight/two-lookup-retained-source-preflight-20260925.json"
SPURGEON_MANIFEST = "sources/devotionals/spurgeons-morning-evening/lib030.source-manifest.json"


def _bound(root: Path, rel: str, size: int | None, digest: str) -> Path:
    path = resolve_repo_path(root, rel)
    if (not path.is_file() or (size is not None and path.stat().st_size != size)
            or sha256_file(path) != digest):
        raise PipelineError(f"lookup CCEL retained authority changed: {rel}")
    return path


def bind_lookup_ccel(
    root: Path, row: dict[str, Any], work: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    """Return retained XML and evidence paths after checking source identity.

    The preflight records exact bytes but is not itself a source manifest. For
    Spurgeon, this also checks the source set and attribution named by the
    reconstruction manifest. No TEI or publication conclusion follows.
    """
    wid = work["work_id"]
    if wid not in {"edwards-select-sermons", "spurgeons-morning-evening"}:
        raise PipelineError(f"unsupported lookup CCEL work: {wid}")
    preflight_ref = row.get("lookup_source_evidence")
    if (not isinstance(preflight_ref, dict)
            or preflight_ref.get("path") != PREFLIGHT
            or not isinstance(preflight_ref.get("sha256"), str)):
        raise PipelineError(f"{wid} lookup preflight binding missing")
    preflight_path = _bound(root, PREFLIGHT, None, preflight_ref["sha256"])
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if (preflight.get("report_type") != "ocd-retained-source-read-only-preflight-v1"
            or {item.get("work_id") for item in preflight.get("works", [])}
            != {"edwards-select-sermons", "spurgeons-morning-evening"}):
        raise PipelineError("lookup CCEL preflight census differs")
    item = next(item for item in preflight["works"] if item["work_id"] == wid)
    source = row.get("primary_source")
    if (source != {"path": item["retained_source"], "bytes": item["retained_bytes"],
                   "sha256": item["retained_sha256"]}
            or item["work"] != f"library/works/{wid}/work.json"
            or item["config"] != row.get("config", {}).get("path")
            or item["work_sha256"] != row.get("work", {}).get("sha256")
            or item["config_sha256"] != row.get("config", {}).get("sha256")):
        raise PipelineError(f"{wid} preflight, packet, and current work binding differ")
    source_path = _bound(root, source["path"], source["bytes"], source["sha256"])
    config_path = _bound(root, item["config"], None, item["config_sha256"])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (work["title"] != config.get("title")
            or config.get("resource_id") != wid
            or config.get("language") != row.get("language")
            or config.get("source_url") != row.get("url")
            or row.get("provider") != "Christian Classics Ethereal Library"
            or row.get("media_type") != "application/xml"):
        raise PipelineError(f"{wid} config, title, language, or provider differs")
    if wid == "edwards-select-sermons" and config.get("source_hash") != "sha256:" + source["sha256"]:
        raise PipelineError("Edwards config source hash differs")
    try:
        xml = etree.parse(str(source_path), etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"{wid} source XML cannot be parsed: {exc}") from exc
    xml_root = xml.getroot()
    if (xml_root.tag != "ThML" or len(xml_root.findall("ThML.head")) != 1
            or len(xml_root.findall("ThML.body")) != 1):
        raise PipelineError(f"{wid} retained XML lacks one ThML head and body")
    header = xml_root.find("./ThML.head/electronicEdInfo")
    if header is None:
        raise PipelineError(f"{wid} retained XML edition header missing")
    expected_author = "edwards" if wid == "edwards-select-sermons" else "spurgeon"
    book_id = source_path.stem
    if (header.findtext("publisherID") != "ccel"
            or header.findtext("authorID") != expected_author
            or header.findtext("bookID") != book_id):
        raise PipelineError(f"{wid} CCEL header identifiers differ")
    titles = [" ".join("".join(node.itertext()).split())
              for node in header.findall("./DC/DC.Title")]
    authors = [" ".join("".join(node.itertext()).split())
               for node in header.findall('./DC/DC.Creator[@sub="Author"]')]
    expected_name = "Jonathan Edwards" if wid == "edwards-select-sermons" else "Charles Haddon Spurgeon"
    if work["title"] not in titles or expected_name not in authors:
        raise PipelineError(f"{wid} retained XML title or author differs")
    language = header.find('./DC/DC.Language[@scheme="ISO639-3"]')
    identifier = header.find('./DC/DC.Identifier[@scheme="URL"]')
    if (language is None or " ".join("".join(language.itertext()).split()) != "eng"
            or identifier is None or " ".join("".join(identifier.itertext()).split())
            != f"/ccel/{expected_author}/{book_id}.html"
            or row["url"] != f"https://www.ccel.org/ccel/{expected_author}/{book_id}.xml"):
        raise PipelineError(f"{wid} XML language or CCEL URL differs")
    warnings = row.get("warnings")
    if not isinstance(warnings, list) or not all(isinstance(value, str) for value in warnings):
        raise PipelineError(f"{wid} rights warnings missing")
    joined = " ".join(warnings)
    if "CCEL" not in joined or "rights" not in joined.lower():
        raise PipelineError(f"{wid} CCEL rights warning missing")
    evidence_paths = [PREFLIGHT, item["config"], source["path"]]
    packet_evidence: list[str] = [PREFLIGHT]
    if wid == "edwards-select-sermons":
        if "blank DC.Rights" not in joined or "footnotes" not in joined:
            raise PipelineError("Edwards source rights or legacy footnote warning missing")
    else:
        if not all(term in joined for term in ("Logos", "editorial changes", "contact address", "print")):
            raise PipelineError("Spurgeon edition or privacy warning missing")
        if item.get("retained_source_set") is None:
            raise PipelineError("Spurgeon retained source set missing")
        set_path = _bound(root, item["retained_source_set"], None, item["retained_source_set_sha256"])
        source_set = json.loads(set_path.read_text(encoding="utf-8"))
        if (source_set.get("contract") != "ocd-retained-source-set-v1"
                or source_set.get("members") != [{"work_id": wid, "logical_path": source["path"].removeprefix("raw/"),
                                                   "bytes": source["bytes"], "sha256": source["sha256"]}]):
            raise PipelineError("Spurgeon retained source-set member differs")
        manifest_path = resolve_repo_path(root, SPURGEON_MANIFEST)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest.get("contract") != "ocd-source-manifest-v1"
                or manifest.get("source_id") != "ccel-lib030-retained-thml-source-set"):
            raise PipelineError("Spurgeon reconstruction manifest identity differs")
        sources = [authority for authority in manifest.get("authorities", [])
                   if authority.get("role") == "primary-source"]
        readmes = [authority for authority in manifest.get("authorities", [])
                   if authority.get("role") == "source-attribution-readme"]
        if (len(sources) != 1 or len(readmes) != 1
                or sources[0]["path"] != item["retained_source_set"]
                or sources[0]["sha256"] != item["retained_source_set_sha256"]):
            raise PipelineError("Spurgeon manifest source or attribution differs")
        attribution = readmes[0]
        _bound(root, attribution["path"], attribution["bytes"], attribution["sha256"])
        evidence_paths.extend([item["retained_source_set"], SPURGEON_MANIFEST, attribution["path"]])
        packet_evidence.extend([item["retained_source_set"], SPURGEON_MANIFEST, attribution["path"]])
    scope = row.get("source_scope")
    if (not isinstance(scope, str) or not scope.startswith(f"Complete acquired file {source['path']};")
            or "does not establish complete TEI reconstruction" not in scope):
        raise PipelineError(f"{wid} lookup source scope overclaims or differs")
    retained = [{"path": source["path"], "bytes": source["bytes"],
                 "sha256": source["sha256"], "media_type": "application/xml",
                 "scope": row["source_scope"]}]
    source_fields = {"source_path": source["path"], "source_bytes": source["bytes"],
                     "source_sha256": source["sha256"], "source_scope": row["source_scope"]}
    return retained, source_fields, evidence_paths, packet_evidence
