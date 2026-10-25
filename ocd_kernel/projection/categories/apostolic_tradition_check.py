"""Independent lxml checker for the Apostolic Tradition native prose profile."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from lxml import etree

NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
BODY_SHA = "db96d7efcb180c1ea3cb64b0160bc0b45528325cb4df5461bc270bd2b4154f8d"
SOURCE_SHA = "820d396c5f69ff601cf2264cb8ed352765c49809a69fda8f616b746e07b9cd05"
CANDIDATE_SHA = "bb60e687be96c5ca861686b8833592742e4dbe91a751fa21b9b5970051032034"
PROFILE = "ocd-prose-apostolic-tradition-pg61614-eleven-spans-v1"
IDENTITY = ("apostolic-tradition", "apostolic-tradition-gutenberg-retained",
            "apostolic-tradition-gutenberg-electronic")
SPANS = ((1, 9, "pg-header"), (10, 13, "ch1"), (14, 33, "toc"),
         (34, 34, "ch2"), (35, 87, "ch3"), (88, 133, "ch4"),
         (134, 136, "ch5"), (137, 387, "ch6"), (388, 390, None),
         (391, 423, "ch7"), (424, 427, None))
KINDS = {"ab": "source-block", "cell": "table-cell", "graphic": "image-reference",
         "hi": "emphasis", "item": "list-item", "label": "label", "lb": "line-break",
         "list": "list", "pb": "page-break", "ref": "source-reference",
         "row": "table-row", "seg": "segment", "table": "table"}
ATTRS = {"ab": {"type": "type", "rend": "style", XML+"lang": "language"},
         "cell": {"cols": "columns", "rend": "style"},
         "graphic": {"n": "number", "rend": "style", "url": "source_target"},
         "hi": {"rend": "style"}, "item": {},
         "label": {"rend": "source_annotations"}, "lb": {"rend": "style"},
         "list": {"rend": "style", "type": "type"},
         "pb": {"n": "number", "rend": "style"},
         "ref": {"rend": "style", "target": "source_target"},
         "row": {"rend": "style"},
         "seg": {"rend": "style", XML+"lang": "language"}, "table": {}}
BLOCKS = {"complete-gutenberg-html-body", "provider-footer", "provider-header",
          "source-footnote-block", "source-footnote-definition", "source-html-blockquote",
          "source-html-dd", "source-html-div", "source-html-h1", "source-html-h2",
          "source-html-h3", "source-html-p", "source-html-table"}
OMIT = {"note", "page-break", "column-break", "source-marker", "anchor",
        "page-furniture", "generator-placeholder"}
BOUNDARIES = {"paragraph", "heading", "division", "verse-group", "list", "list-item",
              "embedded-text", "opening", "closing", "salutation", "epigraph", "argument",
              "trailer", "postscript", "signature", "dateline", "figure", "horizontal-rule",
              "source-block", "table", "table-row", "table-cell"}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _encode(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _convert(node: etree._Element) -> dict:
    local = etree.QName(node).localname
    if etree.QName(node).namespace != NS[1:-1] or local not in KINDS:
        raise ValueError("Apostolic checker found unsupported source element")
    if local == "ab" and node.get("type") not in BLOCKS:
        raise ValueError("Apostolic checker found unsupported block type")
    if local in {"pb", "lb", "graphic"} and (len(node) or (node.text or "").strip()):
        raise ValueError("Apostolic checker found nonempty marker")
    attributes = {}
    for key, value in node.attrib.items():
        if key == XML+"id":
            continue
        if key not in ATTRS[local]:
            raise ValueError("Apostolic checker found unsupported attribute")
        attributes[ATTRS[local][key]] = value
    if local == "graphic" and not node.get("url"):
        raise ValueError("Apostolic checker found graphic without URL")
    content = []
    if node.text:
        content.append({"kind": "text", "text": node.text})
    for child in node:
        content.append(_convert(child))
        if child.tail:
            content.append({"kind": "text", "text": child.tail})
    return {"kind": KINDS[local], "attributes": attributes, "content": content}


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


def _inventory(body: etree._Element) -> tuple[list[dict], dict[str, int], list[dict]]:
    ledger = []
    identifiers = {}
    links = []
    for node in body.iter():
        path = []
        cursor = node
        while cursor is not body:
            parent = cursor.getparent()
            if parent is None:
                raise ValueError("Apostolic checker parent path differs")
            path.append(parent.index(cursor)+1)
            cursor = parent
        path.reverse()
        row = 1 if not path else next(i for i, (first, last, _) in enumerate(SPANS, 1)
                                      if first <= path[0] <= last)
        identifier = node.get(XML+"id")
        if identifier:
            if identifier in identifiers:
                raise ValueError("Apostolic checker duplicate source ID")
            identifiers[identifier] = row
        ledger.append({"ordinal": len(ledger)+1, "row": row, "path": path,
                       "tag": etree.QName(node).localname, "attributes": dict(node.attrib),
                       "text_sha256": _sha((node.text or "").encode("utf-8")),
                       "tail_sha256": _sha((node.tail or "").encode("utf-8"))})
        if etree.QName(node).localname == "ref":
            links.append({"row": row, "path": path, "target": node.get("target")})
    for link in links:
        target = link["target"]
        if target is not None and target.startswith("#") and target[1:] not in identifiers:
            raise ValueError("Apostolic checker dangling local link")
        link["target_row"] = identifiers.get(target[1:]) if target is not None and target.startswith("#") else None
    if len(identifiers) != 731 or len(links) != 1296 or sum(x["target"] is not None for x in links) != 1249:
        raise ValueError("Apostolic checker identity/link counts differ")
    return ledger, identifiers, links


def verify_document(path: Path, rows: list[dict], receipt: dict, *,
                    candidate_only: bool, source_path: Path,
                    representation_revision: str = "apostolic-tradition-pg61614-html-body-v1",
                    edition_title: str = "Project Gutenberg retained HTML witness") -> list[str]:
    """Inspect saved output with lxml only; this module never imports producer."""
    try:
        raw = Path(path).read_bytes()
        if candidate_only and _sha(raw) != CANDIDATE_SHA:
            raise ValueError("frozen candidate bytes differ")
        if _sha(Path(source_path).read_bytes()) != SOURCE_SHA:
            raise ValueError("retained HTML source bytes differ")
        root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False,
                                                     no_network=True))
        if root.tag != NS+"TEI" or dict(root.attrib) != {XML+"lang": "en"}:
            raise ValueError("root/language differs")
        if [node.tag for node in root] != [NS+"teiHeader", NS+"text"]:
            raise ValueError("header/text envelope differs")
        text = root.find(NS+"text")
        if text is None or dict(text.attrib) or [node.tag for node in text] != [NS+"body"]:
            raise ValueError("text/body envelope differs")
        body_container = text[0]
        if dict(body_container.attrib) or [node.tag for node in body_container] != [NS+"ab"]:
            raise ValueError("body carrier differs")
        body = body_container[0]
        if dict(body.attrib) != {"type": "complete-gutenberg-html-body"} or len(body) != 427:
            raise ValueError("body scope differs")
        if _sha(etree.tostring(body, method="c14n")) != BODY_SHA:
            raise ValueError("whole body C14N hash differs")
        if [i for i, x in enumerate(body, 1) if x.get("type") == "source-html-h2"] != [10, 14, 34, 35, 88, 134, 137, 388, 391, 424]:
            raise ValueError("source heading positions differ")
        if (len(rows) != 11 or receipt.get("row_count") != 11
                or receipt.get("mapping_version") != PROFILE
                or receipt.get("projection_profile") != PROFILE):
            raise ValueError("row count/profile differs")
        inventory, identifiers, links = _inventory(body)
        expected_spans = []
        for sequence, (start, end, source_id) in enumerate(SPANS, 1):
            if source_id is not None and body[start-1].get(XML+"id") != source_id:
                raise ValueError("source heading ID differs")
            section = etree.Element(NS+"ab", {"type": "complete-gutenberg-html-body"})
            if sequence == 1:
                section.text = body.text
            for child in list(body)[start-1:end]:
                section.append(etree.fromstring(etree.tostring(child, with_tail=False)))
                section[-1].tail = child.tail
            structure = _convert(section)
            row = rows[sequence-1]
            expected_id = IDENTITY[2]+":native:"+_sha(f"/TEI/text/body/ab/*[{start}..{end}]".encode())[:20]
            if (tuple(row.get(field) for field in ("work_id", "textual_form_id", "edition_id")) != IDENTITY
                    or row.get("record_id") != expected_id or row.get("sequence") != sequence
                    or row.get("category") != "prose" or row.get("language") != "en"
                    or row.get("representation_revision") != representation_revision
                    or row.get("provenance") != {"edition_title": edition_title}
                    or row.get("content_format") != "ocd-native-content-v1"
                    or row.get("locator") != {"kind": "native-unit", "text_part": "body", "unit": sequence}
                    or row.get("structure") != [structure] or row.get("text") != _readable(structure)):
                raise ValueError(f"row {sequence} differs from independent source traversal")
            expected_spans.append({"sequence": sequence, "start": start, "end": end,
                                   "source_id": source_id, "record_id": expected_id,
                                   "text_sha256": _sha(row["text"].encode("utf-8"))})
        if receipt.get("spans") != expected_spans or receipt.get("inventory") != inventory:
            raise ValueError("source span or node inventory differs")
        if receipt.get("source_ids") != identifiers or receipt.get("links") != links:
            raise ValueError("source ID or cross-row link ledger differs")
        if (receipt.get("master_sha256") != _sha(raw) or receipt.get("body_sha256") != BODY_SHA
                or receipt.get("source_sha256") != SOURCE_SHA
                or receipt.get("output_sha256") != _sha(_encode(rows))):
            raise ValueError("master/source/output hash differs")
        from ocd_kernel.projection.categories import sermons
        repository = sermons.ROOT
        for name, path in {
            "schema_sha256": repository / "schemas/v2/categories/prose.schema.json",
            "common_schema_sha256": repository / "schemas/v2/public-row.schema.json",
            "native_content_schema_sha256": repository / "schemas/v2/native-content.schema.json",
        }.items():
            if receipt.get(name) != _sha(path.read_bytes()):
                raise ValueError(f"current {name} differs")
        return []
    except (OSError, ValueError, TypeError, KeyError, etree.XMLSyntaxError) as exc:
        return [str(exc)]


def verify_accepted(root: Path, *, acceptance_path: Path,
                    rows: list[dict], receipt: dict) -> list[str]:
    """Check current canonical authority, then independently inspect all rows."""
    from ocd_kernel.projection.categories.sermons import _accepted_context
    try:
        context = _accepted_context(root, acceptance_path, expected_category="prose")
        if not isinstance(receipt, dict):
            return ["Apostolic receipt must be an object"]
        if receipt.get("authority") != context["authority"]:
            return ["Apostolic acceptance authority differs"]
        if receipt.get("scope") != "tei-document; context derived from validated acceptance":
            return ["Apostolic accepted scope differs"]
        return verify_document(context["edition"].path, rows, receipt,
                               candidate_only=False,
                               source_path=Path(root) / "raw/gutenberg/61614/html/pg61614-images.html",
                               representation_revision=context["representation_revision"],
                               edition_title=context["edition_title"])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return [str(exc)]
