"""Reuse the bound literary reconstruction for the complete Devotions work."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import json
from lxml import etree

CONVERTER_ID = "ocd-donne-devotions-scoped-retained-literary-v1"
CONVERTER_VERSION = "2"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def canonical(record):
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _convert(manifest):
    manifest.verify()
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    root = etree.fromstring(manifest.authority_path("historical-literary-tei").read_bytes())
    old_text = root.find(NS + "text")
    old_scope = old_text.find(NS + "body/" + NS + "div")
    text = etree.Element(NS + "text")
    for part, starts, kind, identifier in (
        ("front", [1, 48, 81, 93], "volume-context", "shared-volume-front"),
        ("body", [1481, 1508, 1539, 1608], "work", "complete-devotions"),
        ("back", [7296], "shared-license", "shared-volume-license"),
    ):
        envelope = etree.SubElement(text, NS + part)
        wrapper = etree.SubElement(envelope, NS + "div", type=kind)
        wrapper.set(XML + "id", profile["work_id"] + "-" + identifier)
        if part == "body":
            wrapper.set("n", "Devotions Upon Emergent Occasions")
        for start in starts:
            matches = [node for node in old_scope if node.get("n") == str(start)]
            if len(matches) != 1:
                raise ValueError(f"retained literary section {start} differs")
            wrapper.append(deepcopy(matches[0]))
    root.replace(old_text, text)
    header = root.find(NS + "teiHeader")
    header.find(NS + "encodingDesc/" + NS + "p").text = profile["encoding_statement"]
    source_desc = header.find(NS + "fileDesc/" + NS + "sourceDesc")
    etree.SubElement(source_desc.find(NS + "bibl"), NS + "note", type="work-scope").text = profile["scope"]
    raw = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    return {
        "content.tei.xml": raw,
        "source-accountability.json": canonical(profile["accounting"]),
        "provenance.json": canonical(dict(status="nonaccepted", work_id=profile["work_id"],
            source_manifest_sha256=manifest.sha256, historical_mapping="unchanged LIB-068 literary v2",
            source_sha256=profile["source_sha256"], scope=profile["scope"],
            excluded_works=profile["excluded_works"], rights="not-cleared", publication="not-authorized")),
        "unresolved.jsonl": b"".join(canonical(x) for x in profile["questions"]),
        "README.source.md": manifest.authority_path("source-readme").read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
