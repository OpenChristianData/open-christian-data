"""Second Samuel-only derivative of frozen retained-CCEL emitter SHA a14b997922b3d3a2486df617446702bf85f3dde6caf454593292de51fa20e00f.

This module emits only a readable text tree and a reversible source ledger.
It does not acquire sources, decide scope, issue acceptance, or install files.
The callers separately bind identity, primary metadata, retained bytes, and proofs.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import re
from urllib.parse import quote, urlsplit

from lxml import etree

from ocd_kernel.tei.writer import tei_el

NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TAGS = {
    **{f"div{i}": "div" for i in range(1, 5)},
    **{f"h{i}": "p" for i in range(1, 7)},
    "p": "p", "a": "ref", "b": "hi", "strong": "hi", "i": "hi",
    "small": "hi", "big": "hi", "em": "hi", "cite": "hi",
    "sup": "hi", "sub": "hi", "br": "lb", "pb": "pb", "note": "note",
    "scripRef": "ref", "scripCom": "milestone", "insertIndex": "milestone",
    "hr": "milestone", "span": "seg", "verse": "lg", "l": "l",
    "div": "quote", "blockquote": "quote", "ul": "list", "li": "item",
    "table": "table", "tr": "row", "td": "cell", "img": "figure",
}
RENDS = {"i": "italic", "b": "bold", "strong": "bold", "small": "small",
         "big": "large", "em": "emphasis", "cite": "source-citation",
         "sup": "superscript", "sub": "subscript"}
REND_TAGS = {"div", "p", "hi", "seg", "quote", "lg", "l", "list", "item",
             "table", "cell", "ref", "note", "lb", "milestone", "anchor"}
STYLE_TAGS = {"div", "p", "hi", "seg", "table", "cell", "milestone"}
KNOWN_SOURCES = {'blaikie-expositor2sam':'e3397acdd20cbc7ea8ef6c81eb10407263fe1276b40973c07cd908cf4902c379'}
SOURCE_BASE='https://www.ccel.org/ccel/blaikie/expositor2sam.html'


def emit_text(raw: bytes, *, member_id: str, front_ids: tuple[str, ...],
              back_ids: tuple[str, ...]) -> tuple[etree._Element, dict]:
    """Map one complete retained ThML body, preserving source order and fields.

    Numbered divisions retain hierarchy. Unnumbered mixed containers use quote,
    following Moule index-v4; source Index divisions retain their division role.
    HTML tbody has no TEI equivalent: its rows remain in the table in place and
    its whitespace is joined to the adjacent carrier. Original wrapper fields
    and paths are retained for exact inversion. No textual tbody is admitted.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", member_id):
        raise ValueError("Invalid member XML identity")
    if member_id not in KNOWN_SOURCES or hashlib.sha256(raw).hexdigest() != KNOWN_SOURCES[member_id]:
        raise ValueError("Emitter is fenced to the one existing retained Second Samuel witness")
    source = etree.fromstring(raw, etree.XMLParser(resolve_entities=False,
        no_network=True, remove_comments=False, remove_pis=False, huge_tree=True))
    body = source.find("ThML.body")
    if source.tag != "ThML" or body is None:
        raise ValueError("Expected complete retained ThML electronic witness")
    labels = ("scripCom", "pb")
    comment_forms = Counter({" added reason=\"AutoIndexing\" ": 1, " /added ": len(labels) + 1})
    for label in labels:
        comment_forms[f' added reason="insertIndex" class="{label}" '] = 1
        comment_forms[f' Start of automatically inserted {label} index '] = 1
        comment_forms[f' End of {"page" if label == "pb" else label} index '] = 1
    comments = [n for n in body.iter() if n.tag is etree.Comment]
    if (Counter(n.text for n in comments) != comment_forms
            or any((n.tail or "").strip() for n in comments)
            or body.xpath('.//processing-instruction()')):
        raise ValueError("Retained administrative comment/PI census differs")
    roots = [n for n in body if isinstance(n.tag, str)]
    root_ids = [n.get("id") for n in roots]
    if any(n.tag != "div1" for n in roots) or len(set(root_ids)) != len(root_ids):
        raise ValueError("Root source divisions differ")
    if set(front_ids) & set(back_ids) or not set(front_ids + back_ids) <= set(root_ids):
        raise ValueError("Source region identities differ")
    parts = ["front" if i in front_ids else "back" if i in back_ids else "body" for i in root_ids]
    if parts != sorted(parts, key={"front": 0, "body": 1, "back": 2}.get):
        raise ValueError("Region grouping would reorder retained source")
    source_ids = [n.get("id") for n in body.iter() if isinstance(n.tag, str) and n.get("id")]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("Duplicate retained source IDs")
    id_set = set(source_ids)
    text = tei_el("text", {"xml:lang": "en"})
    regions = {p: tei_el(p, {"xml:id": f"{member_id}-{p}"}) for p in ("front", "body", "back")}
    text.extend(regions.values())
    regions["front"].text = body.text
    records: list[dict] = []
    auxiliaries: list[dict] = []
    broken: list[dict] = []

    def append_text(parent: etree._Element, value: str | None) -> None:
        if value is not None:
            if len(parent):
                parent[-1].tail = (parent[-1].tail or "") + value
            else:
                parent.text = (parent.text or "") + value

    def emit(node: etree._Element, parent: etree._Element, path: list[int]) -> None:
        ordinal = len(records) + 1
        record = {"ordinal": ordinal, "source_path": path,
                  "source_parent_path": path[:-1], "source_child_index": path[-1],
                  "source_tag": node.tag if isinstance(node.tag, str) else
                    ("#comment" if node.tag is etree.Comment else "#pi"),
                  "source_attributes": dict(node.attrib), "source_text": node.text,
                  "source_tail": node.tail}
        records.append(record)
        if not isinstance(node.tag, str):
            if node.tag is not etree.Comment:
                raise ValueError("Unsupported retained non-element node")
            if (node.tail or "").strip():
                raise ValueError("Source comment has visible tail text")
            record.update({"disposition": "source-comment-ledger-exact-whitespace-join",
                           "tei_parent_id": parent.get(XML_ID),
                           "tei_preceding_child_index": len(parent) - 1})
            append_text(parent, node.tail)
            return
        if node.tag == "tbody":
            if parent.tag != f"{{{NS}}}table" or (node.text or "").strip() or (node.tail or "").strip():
                raise ValueError("Unaccounted textual or non-table tbody")
            if any(isinstance(c.tag, str) and c.tag != "tr" for c in node):
                raise ValueError("Non-row tbody child")
            record.update({"disposition": "source-tbody-row-flattening", "tei_parent_id": parent.get(XML_ID),
                           "tei_start_child_index": len(parent)})
            append_text(parent, node.text)
            for i, child in enumerate(node):
                emit(child, parent, path + [i])
            append_text(parent, node.tail)
            return
        if node.tag not in TAGS:
            raise ValueError(f"Unmapped retained source tag {node.tag}")
        tag = TAGS[node.tag]
        identity = f"{member_id}-{node.get('id')}" if node.get("id") else f"{member_id}-feature-{ordinal:06d}"
        attrs = {"xml:id": identity}
        if node.tag.startswith("div") and node.tag != "div":
            attrs["type"] = "source-" + node.tag
            if node.get("title"):
                attrs["n"] = node.get("title")
        if node.tag == "div":
            if node.get("class") == "Index":
                tag, attrs["type"] = "div", "source-index"
            else:
                attrs["type"] = "source-div"
                if node.get("title"):
                    attrs["n"] = node.get("title")
        if re.fullmatch(r"h[1-6]", node.tag):
            attrs["rend"] = "source-" + node.tag
        if node.tag in RENDS:
            attrs["rend"] = RENDS[node.tag]
        if node.tag == "span":
            attrs["type"] = "thml-span"
        if node.tag == "verse":
            attrs["type"] = "source-stanza"
        if node.tag == "blockquote":
            attrs["type"] = "source-blockquote"
        if node.tag == "a":
            href = node.get("href")
            if href is None:
                tag = "seg" if node.text or len(node) else "anchor"
                attrs["type"] = "source-anchor"
            elif href.startswith("#"):
                if href[1:] not in id_set:
                    broken.append({"source_path": path, "source_id": node.get("id"), "href": href})
                    tag = "seg"
                    attrs.update({"type": "source-unresolved-link", "n": href})
                else:
                    attrs["target"] = f"#{member_id}-{href[1:]}"
            else:
                attrs["target"] = href
                if href and not urlsplit(href).scheme:
                    attrs["{http://www.w3.org/XML/1998/namespace}base"] = SOURCE_BASE
        if node.tag == "scripRef" and node.get("osisRef"):
            attrs["target"] = node.get("osisRef")
        if node.tag in {"scripCom", "insertIndex", "hr"}:
            if node.text or len(node):
                raise ValueError("Textual retained administrative marker")
            attrs["unit"] = "horizontal-rule" if node.tag == "hr" else node.tag
            label = node.get("passage") if node.tag == "scripCom" else node.get("type") if node.tag == "insertIndex" else None
            if label is not None:
                attrs["n"] = label
            if node.get("osisRef") is not None:
                attrs["corresp"] = node.get("osisRef")
        if node.tag == "br":
            attrs["type"] = "source-br"
        if node.tag == "pb" and node.get("n") is not None:
            attrs["n"] = node.get("n")
        if node.tag == "note":
            for key in ("n", "place", "type"):
                if node.get(key) is not None:
                    attrs[key] = node.get(key)
            if node.get("anchored") is not None:
                value = node.get("anchored")
                if value not in {"yes", "no", "true", "false", "1", "0"}:
                    raise ValueError("Unknown retained note anchoring")
                attrs["anchored"] = {"yes": "true", "no": "false"}.get(value, value)
        if node.tag == "td":
            for original, mapped in (("colspan", "cols"), ("rowspan", "rows")):
                if node.get(original) is not None:
                    if not re.fullmatch(r"[1-9][0-9]*", node.get(original)):
                        raise ValueError("Invalid retained table cell span")
                    attrs[mapped] = node.get(original)
        if node.tag == "table":
            for key in ("rows", "cols"):
                if node.get(key) is not None:
                    attrs[key] = node.get(key)
            if node.get("summary"):
                attrs["n"] = node.get("summary")
        rend = [attrs["rend"]] if "rend" in attrs else []
        if node.get("class") and tag in REND_TAGS:
            rend.append("source-class-" + quote(node.get("class"), safe="-_."))
        if node.get("dir") and tag in REND_TAGS:
            rend.append("source-dir-" + node.get("dir"))
        if node.get("style"):
            if tag in STYLE_TAGS:
                attrs["style"] = node.get("style")
            elif tag in REND_TAGS:
                rend.append("source-style-" + quote(node.get("style"), safe="-_."))
        if rend:
            attrs["rend"] = " ".join(rend)
        if node.tag == "img":
            annotations = [f"urn:ccel:source-img:{key}:{quote(node.get(key), safe='-_.')}"
                           for key in ("width", "height", "align", "class", "style", "border")
                           if node.get(key) is not None]
            if annotations:
                # Literal source dimensions/alignment have no portable TEI
                # graphic/native attributes; typed source annotations retain
                # them without inventing units or interpreting CSS/pixels.
                attrs["ana"] = " ".join(annotations)
        annotations = ["urn:ccel:source-attribute:" + quote(k, safe="-_.") + ":" + quote(v, safe="-_.") for k, v in sorted(node.attrib.items())]
        if annotations:
            attrs["ana"] = " ".join(annotations)
        out = tei_el(tag, attrs)
        out.text, out.tail = node.text, node.tail
        parent.append(out)
        record.update({"disposition": "native-element", "tei_id": identity, "tei_tag": tag,
                       "tei_attributes": dict(out.attrib), "tei_parent_id": parent.get(XML_ID),
                       "tei_child_index": len(parent) - 1,
                       "attribute_disposition": "semantic native attributes plus complete original attributes in reversible source ledger"})
        if node.tag == "img":
            if not node.get("src") or node.text or len(node):
                raise ValueError("Unexpected retained image carrier")
            out.append(tei_el("graphic", {"url": node.get("src")}))
            for attribute, auxiliary in (("alt", "figDesc"), ("title", "label")):
                if node.get(attribute) is not None:
                    out.append(tei_el(auxiliary, text=node.get(attribute)))
            auxiliaries.append({"tei_parent_id": identity, "basis": "literal source img attributes",
                                "source_path": path, "children": [etree.tostring(c, encoding="unicode") for c in out]})
        for i, child in enumerate(node):
            emit(child, out, path + [i])

    current = "front"
    for i, node in enumerate(body):
        if isinstance(node.tag, str):
            current = "front" if node.get("id") in front_ids else "back" if node.get("id") in back_ids else "body"
        emit(node, regions[current], [i])
    account = {"contract": "ocd-retained-ccel-native-emitter-v1", "member_id": member_id,
               "source_sha256": hashlib.sha256(raw).hexdigest(), "source_body_tag": body.tag,
               "source_body_attributes": dict(body.attrib), "source_body_text": body.text,
               "source_body_tail": body.tail, "root_ids_in_order": root_ids,
               "root_disposition": {p: [i for i, r in zip(root_ids, parts) if r == p] for p in regions},
               "features": records, "feature_count": len(records), "image_auxiliaries": auxiliaries,
               "broken_local_links": broken,
               "administrative_comment_count": len(comments),
               "comment_disposition": "Exact fields/positions retained in ledger; whitespace-only tails joined in actual native text; comments are not DOM-retained",
               "source_prolog": [{"node_kind": "comment" if n.tag is etree.Comment else "pi",
                                   "target": n.target if n.tag is etree.PI else None,
                                   "text": n.text, "tail": n.tail}
                                  for n in reversed(list(source.itersiblings(preceding=True)))],
               "scope": "complete retained electronic XML body; external image pixels not inferred or acquired"}
    # This checks ONLY source-to-ledger conservation. Independent callers must
    # inspect actual returned TEI fields/order/attachments against raw-derived
    # expectations, including comment/tbody whitespace and image auxiliaries.
    if etree.tostring(restore_source_body(account), method="c14n", with_comments=True) != etree.tostring(body, method="c14n", with_comments=True):
        raise ValueError("Source body inverse differs")
    return text, account


def restore_source_body(account: dict) -> etree._Element:
    """Restore exact parsed body fields, including removed tbody and comments."""
    body = etree.Element(account["source_body_tag"], account["source_body_attributes"])
    body.text, body.tail = account["source_body_text"], account["source_body_tail"]
    nodes = {(): body}
    for record in account["features"]:
        tag = record["source_tag"]
        if tag == "#comment":
            node = etree.Comment(record["source_text"])
        elif tag == "#pi":
            node = etree.ProcessingInstruction(record["source_pi_target"], record["source_text"])
        else:
            node = etree.Element(tag, record["source_attributes"])
            node.text = record["source_text"]
        node.tail = record["source_tail"]
        path = tuple(record["source_path"])
        parent = nodes[path[:-1]]
        if len(parent) != path[-1]:
            raise ValueError("Source ledger sibling order differs")
        parent.append(node)
        nodes[path] = node
    return body
