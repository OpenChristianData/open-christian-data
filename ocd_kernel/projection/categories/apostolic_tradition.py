"""Closed Apostolic Tradition native prose projection.

This reads the retained electronic candidate or a header-only successor. It does
not write a master, acceptance, source, or public release.
"""

from __future__ import annotations

import hashlib
import json
import re
import copy
import xml.etree.ElementTree as ET
from pathlib import Path

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import _header_rules, _schema_bindings, _validate_rows

NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
PROFILE = "ocd-prose-apostolic-tradition-pg61614-eleven-spans-v1"
IDENTITY = {
    "work_id": "apostolic-tradition",
    "textual_form_id": "apostolic-tradition-gutenberg-retained",
    "edition_id": "apostolic-tradition-gutenberg-electronic",
}
CANDIDATE_SHA = "bb60e687be96c5ca861686b8833592742e4dbe91a751fa21b9b5970051032034"
BODY_SHA = "db96d7efcb180c1ea3cb64b0160bc0b45528325cb4df5461bc270bd2b4154f8d"
SOURCE_SHA = "820d396c5f69ff601cf2264cb8ed352765c49809a69fda8f616b746e07b9cd05"
SPANS = ((1, 9, "pg-header"), (10, 13, "ch1"), (14, 33, "toc"),
         (34, 34, "ch2"), (35, 87, "ch3"), (88, 133, "ch4"),
         (134, 136, "ch5"), (137, 387, "ch6"), (388, 390, None),
         (391, 423, "ch7"), (424, 427, None))
BLOCK_TYPES = frozenset(("complete-gutenberg-html-body", "provider-footer",
                         "provider-header", "source-footnote-block",
                         "source-footnote-definition", "source-html-blockquote",
                         "source-html-dd", "source-html-div", "source-html-h1",
                         "source-html-h2", "source-html-h3", "source-html-p",
                         "source-html-table"))
KINDS = {"ab": "source-block", "cell": "table-cell", "graphic": "image-reference",
         "hi": "emphasis", "item": "list-item", "label": "label", "lb": "line-break",
         "list": "list", "pb": "page-break", "ref": "source-reference",
         "row": "table-row", "seg": "segment", "table": "table"}
ATTRS = {
    "ab": {"type": "type", "rend": "style", XML+"lang": "language"},
    "cell": {"cols": "columns", "rend": "style"},
    "graphic": {"n": "number", "rend": "style", "url": "source_target"},
    "hi": {"rend": "style"}, "item": {},
    "label": {"rend": "source_annotations"},
    "lb": {"rend": "style"},
    "list": {"rend": "style", "type": "type"},
    "pb": {"n": "number", "rend": "style"},
    "ref": {"rend": "style", "target": "source_target"},
    "row": {"rend": "style"},
    "seg": {"rend": "style", XML+"lang": "language"},
    "table": {},
}
OMIT = {"note", "page-break", "column-break", "source-marker", "anchor",
        "page-furniture", "generator-placeholder"}
BOUNDARIES = {"paragraph", "heading", "division", "verse-group", "list", "list-item",
              "embedded-text", "opening", "closing", "salutation", "epigraph", "argument",
              "trailer", "postscript", "signature", "dateline", "figure", "horizontal-rule",
              "source-block", "table", "table-row", "table-cell"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _check_envelope(raw: bytes, *, candidate_only: bool) -> tuple[ET.Element, ET.Element]:
    if candidate_only and _sha(raw) != CANDIDATE_SHA:
        raise PipelineError("Apostolic proposal requires exact frozen candidate bytes")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise PipelineError("Apostolic TEI contains a declaration")
    try:
        lxml_root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False,
                                                          load_dtd=False, no_network=True))
        root = ET.fromstring(raw)
    except (etree.XMLSyntaxError, ET.ParseError) as exc:
        raise PipelineError("invalid Apostolic TEI") from exc
    if root.tag != NS+"TEI" or root.attrib != {XML+"lang": "en"}:
        raise PipelineError("Apostolic root/language differs")
    if [child.tag for child in root] != [NS+"teiHeader", NS+"text"]:
        raise PipelineError("Apostolic header/text envelope differs")
    allowed_children, allowed_attributes = _header_rules(True)
    for node in root[0].iter():
        tag = node.tag.removeprefix(NS)
        if (tag not in allowed_children
                or any(child.tag.removeprefix(NS) not in allowed_children[tag] for child in node)):
            raise PipelineError("Apostolic header element differs from accepted policy")
        allowed = set(allowed_attributes.get(tag, [])) | {"xml:id"}
        for key in node.attrib:
            name = "xml:"+key[len(XML):] if key.startswith(XML) else key
            if name not in allowed:
                raise PipelineError("Apostolic header attribute differs from accepted policy")
    text = root.find(NS+"text")
    if text is None or text.attrib or [child.tag for child in text] != [NS+"body"]:
        raise PipelineError("Apostolic text/body envelope differs")
    body = text.find(NS+"body")
    if body is None or body.attrib or [child.tag for child in body] != [NS+"ab"]:
        raise PipelineError("Apostolic complete-body carrier differs")
    wrapper = body[0]
    if wrapper.attrib != {"type": "complete-gutenberg-html-body"} or len(wrapper) != 427:
        raise PipelineError("Apostolic body scope or child count differs")
    bound_body = lxml_root.find(NS+"text/"+NS+"body/"+NS+"ab")
    if bound_body is None or _sha(etree.tostring(bound_body, method="c14n")) != BODY_SHA:
        raise PipelineError("Apostolic retained body bytes/structure differ")
    for start, end, identifier in SPANS:
        if end < start or (identifier is not None and wrapper[start-1].get(XML+"id") != identifier):
            raise PipelineError("Apostolic source heading boundary differs")
    if [i for i, x in enumerate(wrapper, 1) if x.get("type") == "source-html-h2"] != [10, 14, 34, 35, 88, 134, 137, 388, 391, 424]:
        raise PipelineError("Apostolic top-level H2 positions differ")
    return root, wrapper


def _content(node: ET.Element) -> dict:
    if not isinstance(node.tag, str) or not node.tag.startswith(NS):
        raise PipelineError("Apostolic content namespace differs")
    tag = node.tag[len(NS):]
    if tag not in KINDS:
        raise PipelineError(f"Apostolic content tag differs: {tag}")
    if tag == "ab" and node.get("type") not in BLOCK_TYPES:
        raise PipelineError("Apostolic block type differs")
    if tag in {"pb", "lb", "graphic"} and (len(node) or (node.text or "").strip()):
        raise PipelineError(f"Apostolic empty {tag} carrier differs")
    if tag == "graphic" and not node.get("url"):
        raise PipelineError("Apostolic graphic URL is missing")
    attrs = {}
    for key, value in node.attrib.items():
        if key == XML+"id":
            continue
        target = ATTRS[tag].get(key)
        if target is None:
            raise PipelineError(f"Apostolic unsupported {tag} attribute {key}")
        attrs[target] = value
    parts = []
    if node.text:
        parts.append({"kind": "text", "text": node.text})
    for child in node:
        parts.append(_content(child))
        if child.tail:
            parts.append({"kind": "text", "text": child.tail})
    return {"kind": KINDS[tag], "attributes": attrs, "content": parts}


def _readable(structure: dict) -> str:
    def walk(node: dict) -> str:
        kind = node["kind"]
        if kind == "text":
            return re.sub(r"\s+", " ", node["text"])
        if kind in OMIT:
            return ""
        if kind == "line-break":
            return "" if node["attributes"].get("break_mode") == "no" else " "
        value = "".join(walk(part) for part in node["content"])
        return "\n\n"+value.strip()+"\n\n" if kind in BOUNDARIES else value
    return re.sub(r"\n{3,}", "\n\n", re.sub(r" *\n *", "\n", walk(structure))).strip()


def _ledger(wrapper: ET.Element) -> tuple[list[dict], dict[str, int], list[dict]]:
    inventory = []
    ids = {}
    links = []
    def visit(node: ET.Element, path: tuple[int, ...], row: int) -> None:
        ordinal = len(inventory)+1
        identifier = node.get(XML+"id")
        if identifier:
            if identifier in ids:
                raise PipelineError("duplicate Apostolic source ID")
            ids[identifier] = row
        inventory.append({"ordinal": ordinal, "row": row, "path": list(path),
                          "tag": node.tag[len(NS):], "attributes": dict(node.attrib),
                          "text_sha256": _sha((node.text or "").encode("utf-8")),
                          "tail_sha256": _sha((node.tail or "").encode("utf-8"))})
        if node.tag == NS+"ref":
            links.append({"row": row, "path": list(path), "target": node.get("target")})
        for index, child in enumerate(node, 1):
            visit(child, (*path, index), row)
    visit(wrapper, (), 1)
    # The wrapper was visited as row one; update each descendant's owner from
    # its first direct-child path. All source descendants remain in one row.
    for item in inventory[1:]:
        direct = item["path"][0]
        item["row"] = next(index for index, (start, end, _) in enumerate(SPANS, 1)
                           if start <= direct <= end)
    ids = {item["attributes"][XML+"id"]: item["row"] for item in inventory
           if XML+"id" in item["attributes"]}
    for link in links:
        direct = link["path"][0]
        link["row"] = next(index for index, (start, end, _) in enumerate(SPANS, 1)
                           if start <= direct <= end)
        target = link["target"]
        if target is not None and target.startswith("#") and target[1:] not in ids:
            raise PipelineError("Apostolic local link target missing")
        link["target_row"] = ids.get(target[1:]) if target is not None and target.startswith("#") else None
    if len(ids) != 731 or len(links) != 1296 or sum(link["target"] is not None for link in links) != 1249:
        raise PipelineError("Apostolic ID/link counts differ")
    return inventory, ids, links


def project_document(path: Path, *, identity: dict[str, str], language: str,
                     representation_revision: str, edition_title: str,
                     candidate_only: bool = False) -> dict:
    """Project all eleven exact retained spans without editing TEI."""
    if identity != IDENTITY or language != "en" or not representation_revision or not edition_title:
        raise PipelineError("Apostolic identity/language/provenance differs")
    raw = Path(path).read_bytes()
    _, wrapper = _check_envelope(raw, candidate_only=candidate_only)
    inventory, ids, links = _ledger(wrapper)
    rows = []
    for sequence, (start, end, source_id) in enumerate(SPANS, 1):
        section = ET.Element(NS+"ab", {"type": "complete-gutenberg-html-body"})
        if sequence == 1:
            section.text = wrapper.text
        for child in wrapper[start-1:end]:
            section.append(copy.deepcopy(child))
        structure = _content(section)
        locator = {"kind": "native-unit", "text_part": "body", "unit": sequence}
        row = {**identity,
               "record_id": identity["edition_id"]+":native:"+_sha(f"/TEI/text/body/ab/*[{start}..{end}]".encode())[:20],
               "sequence": sequence, "language": language,
               "representation_revision": representation_revision,
               "provenance": {"edition_title": edition_title},
               "category": "prose", "content_format": "ocd-native-content-v1",
               "structure": [structure], "text": _readable(structure),
               "locator": locator}
        rows.append(row)
    _validate_rows(rows, "prose")
    receipt = {"scope": "complete retained PG61614 HTML body; eleven source spans",
               "mapping_version": PROFILE, "projection_profile": PROFILE,
               "master_sha256": _sha(raw), "body_sha256": BODY_SHA,
               "source_sha256": SOURCE_SHA, **_schema_bindings("prose"),
               "output_sha256": _sha(_canonical_json(rows)), "row_count": len(rows),
               "spans": [{"sequence": index, "start": start, "end": end,
                          "source_id": source_id, "record_id": rows[index-1]["record_id"],
                          "text_sha256": _sha(rows[index-1]["text"].encode("utf-8"))}
                         for index, (start, end, source_id) in enumerate(SPANS, 1)],
               "inventory": inventory, "source_ids": ids, "links": links,
               "warnings": ["Complete retained electronic body; physical printing and 1934/1962 rights status unresolved.",
                            "Cover image remains a source reference; offline image payload not embedded."],
               "unsupported": [], "independent_check": {"status": "pending"}}
    return {"rows": rows, "receipt": receipt}


def project_accepted(root: Path, *, acceptance_path: Path) -> dict:
    """Project only the validated promoted work through this exact profile."""
    from ocd_kernel.projection.categories.sermons import _accepted_context
    context = _accepted_context(root, acceptance_path, expected_category="prose")
    result = project_document(context["edition"].path, identity=context["identity"],
                              language=context["language"],
                              representation_revision=context["representation_revision"],
                              edition_title=context["edition_title"])
    result["receipt"]["authority"] = context["authority"]
    result["receipt"]["scope"] = "tei-document; context derived from validated acceptance"
    return result
