"""Complete-envelope successor for the retained Schaff volume."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from build.tei.lib029_reconstruction import _convert as _legacy_convert
from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-lib029-complete-volume-to-tei"
CONVERTER_VERSION = "1"
NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
FRONT = ("i", "ii")
BODY = ("iii", "iv", "v", "vi", "vii", "viii", "ix", "x")
BACK = ("xi", "xii")
LATE_HEADINGS = {
    "i-p1.2", "i-p1.3", "i-p1.4", "i-p2.1", "i-p2.2", "i-p2.3",
    "i-p5.1", "i-p6.1", "i-p6.4", "iii-p4.1", "iii-p8.1",
    "iii-p8.3", "iii-p8.4", "xi-p842.1",
}


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    members = dict(_legacy_convert(source_manifest))
    root = etree.fromstring(members["content.tei.xml"])
    text = root.find(f"{{{NS}}}text")
    if text is None:
        raise ValueError("Schaff candidate text is absent")
    body = text.find(f"{{{NS}}}body")
    if body is None or len(body) != 1:
        raise ValueError("Schaff candidate has no sole body work")
    work = body[0]
    source_divisions = list(work)[1:]
    if len(source_divisions) != 12:
        raise ValueError("Schaff candidate does not cover twelve source divisions")
    accountability = json.loads(members["source-accountability.json"])
    observed = [row["source_xml_id"] for row in accountability["crosswalk"] if row["source_tag"] == "div1"]
    if observed != [*FRONT, *BODY, *BACK]:
        raise ValueError("Schaff source order or division identity changed")
    front = etree.Element(f"{{{NS}}}front", {XML_ID: "lib029-front"})
    back = etree.Element(f"{{{NS}}}back", {XML_ID: "lib029-back"})
    for child in source_divisions[:2]:
        front.append(child)
    for child in source_divisions[-2:]:
        back.append(child)
    text.insert(0, front)
    text.append(back)
    top = {row["source_xml_id"]: row for row in accountability["crosswalk"] if row["source_tag"] == "div1"}
    for index, source_id in enumerate(FRONT, 1):
        top[source_id]["tei_parent_id"] = "lib029-front"
        top[source_id]["tei_child_ordinal"] = index
    for index, source_id in enumerate(BODY, 2):
        top[source_id]["tei_child_ordinal"] = index
    for index, source_id in enumerate(BACK, 1):
        top[source_id]["tei_parent_id"] = "lib029-back"
        top[source_id]["tei_child_ordinal"] = index
    source_ids = {}
    for row in accountability["crosswalk"]:
        source_id = row["source_xml_id"]
        if source_id:
            if source_id in source_ids:
                raise ValueError(f"Schaff source ID is duplicated: {source_id}")
            source_ids[source_id] = row["tei_xml_id"]
    feature_nodes = {node.get(XML_ID): node for node in root.iter() if node.get(XML_ID)}
    links = 0
    for row in accountability["crosswalk"]:
        href = row["attributes"].get("href")
        if row["source_tag"] != "a" or not isinstance(href, str) or not href.startswith("#"):
            continue
        target = source_ids.get(href[1:])
        if target is None:
            raise ValueError(f"Schaff source link has no retained target: {href}")
        node = feature_nodes[row["tei_xml_id"]]
        if node.tag != f"{{{NS}}}ref" or node.get("target") != href:
            raise ValueError(f"Schaff source link projection drifted: {href}")
        node.set("target", f"#{target}")
        row["tei_attributes"]["target"] = f"#{target}"
        links += 1
    if links != 5327:
        raise ValueError(f"Schaff source link census drifted: {links}")
    retained_source = next(
        authority for authority in source_manifest.record["authorities"]
        if authority["name"] == "creeds-of-christendom-vol-1-source"
    )
    source_hash = retained_source["sha256"]
    header_hashes = root.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='sha256']",
        namespaces={"tei": NS},
    )
    if len(header_hashes) != 1 or len(header_hashes[0]) or not header_hashes[0].text:
        raise ValueError("Schaff retained-source header binding is absent")
    header_hashes[0].text = source_hash
    headings = 0
    for row in accountability["crosswalk"]:
        if row["source_tag"] not in {"h1", "h2", "h3", "h4", "h5", "h6", "title"}:
            continue
        node = feature_nodes[row["tei_xml_id"]]
        if node.tag != f"{{{NS}}}p" or node.getparent().tag != f"{{{NS}}}div":
            raise ValueError("Schaff inherited heading placement drifted")
        if row["source_xml_id"] in LATE_HEADINGS:
            rendition = f"source-{row['source_tag']}"
            node.set("rend", rendition)
            row["tei_attributes"]["rend"] = rendition
        else:
            node.tag = f"{{{NS}}}head"
            row["tei_tag"] = "head"
        headings += 1
    if headings != 52:
        raise ValueError(f"Schaff source heading census drifted: {headings}")
    accountability["source_scope"] = "complete ThML.body division sequence i through xii, with source title and dedication in TEI front, eight history chapters in body, and both source indexes in back"
    accountability["document_accounting"][0]["disposition"] = "complete-volume-with-front-body-back"
    members["content.tei.xml"] = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    members["source-accountability.json"] = _json(accountability)
    unresolved = [json.loads(line) for line in members["unresolved.jsonl"].splitlines()]
    for row in unresolved:
        row["scope"] = "complete-retained-volume"
        row["evidence"] = row["evidence"].replace("selected chapter scope", "complete retained volume").replace("selected chapters", "complete volume")
    members["unresolved.jsonl"] = b"".join(_json(row) for row in unresolved)
    members["README.source.md"] = members["README.source.md"].replace(
        b"Every selected source-scope node", b"Every retained body node"
    ) + b"\nThe twelve source divisions are assigned in order to front (i-ii), history body (iii-x), and back indexes (xi-xii).\n"
    return members


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
