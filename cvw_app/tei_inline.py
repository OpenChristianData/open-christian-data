"""Inert TEI inline runs, preserving mixed-text order and explicit emphasis."""

from __future__ import annotations
import re
from xml.etree import ElementTree as ET

MARKS = {
    "italic": "italic",
    "italics": "italic",
    "bold": "bold",
    "sup": "superscript",
    "superscript": "superscript",
    "sub": "subscript",
    "subscript": "subscript",
    "underline": "underline",
    "smallcaps": "small-caps",
    "small-caps": "small-caps",
}


def page_break_label(element: ET.Element) -> str:
    """Label an explicit page milestone without inventing a page number."""
    number = " ".join((element.get("n") or "").split())
    return f"[Page break: {number}]" if number else "[Page break]"


def pointer_review_label(element: ET.Element) -> str:
    """Expose empty TEI markers without annotating readable reference content."""
    name = element.tag.rsplit("}", 1)[-1]
    # References already carry readable citation/index text. Injecting their
    # attributes into the text corrupts that reading in every projection.
    if name not in {"anchor", "ptr"}:
        return ""
    fields = []
    for label, attribute in (
        ("xml:id", "{http://www.w3.org/XML/1998/namespace}id"),
        ("type", "type"), ("subtype", "subtype"), ("n", "n"),
        ("target", "target"), ("corresp", "corresp"),
    ):
        value = element.get(attribute)
        if value:
            fields.append(f'{label}="{value}"')
    detail = " " + " ".join(fields) if fields else ""
    return f" [TEI review: {name}{detail}] "


def inline_runs(element: ET.Element, *, _on_sources=None) -> list[dict]:
    chunks = []
    owners = []

    def add(text, marks, sources):
        chunks.append((text, marks))
        if _on_sources is not None:
            owners.append(sources)

    def walk(node, inherited, ancestors=()):
        sources = (*ancestors, node) if _on_sources is not None else ()
        name = node.tag.rsplit("}", 1)[-1]
        marks = list(inherited)
        annotation = pointer_review_label(node)
        if annotation:
            add(annotation, [], sources)
        if name == "pb":
            add(" " + page_break_label(node) + " ", [], sources)
            return
        if name in {"hi", "emph"}:
            tokens = (node.get("rend") or ("italic" if name == "emph" else "")).split()
            marks = sorted(
                set(marks + [MARKS[t.lower()] for t in tokens if t.lower() in MARKS])
            )
        if name == "gap" and not "".join(node.itertext()).strip():
            label = node.get("rend") or node.get("display")
            if not label:
                reason = node.get("reason") or node.get("desc") or ""
                label = (
                    "["
                    + (reason + " gap" if reason else "gap")
                    + ("; extent " + node.get("extent") if node.get("extent") else "")
                    + "]"
                )
            add(label, marks, sources)
            return
        if node.get("type") == "json-null":
            add("null", marks, sources)
            return
        add(node.text or "", marks, sources)
        for child in node:
            if child.tag.rsplit("}", 1)[-1] == "lb":
                if child.get("break") != "no":
                    add(" ", marks, (*sources, child))
            else:
                walk(child, marks, sources)
            add(child.tail or "", marks, (*sources, child))

    walk(element, [])
    return normalize_runs(chunks, _owners=owners if _on_sources is not None else None,
                          _on_sources=_on_sources)


def normalize_runs(chunks, *, _owners=None, _on_sources=None):
    result = []
    pending = None
    pending_sources = ()
    contributions = {}

    def append(text, marks, sources):
        contributions.update(dict.fromkeys(sources))
        if result and result[-1]["marks"] == marks:
            result[-1]["text"] += text
        else:
            result.append({"text": text, "marks": marks})

    for index, (text, marks) in enumerate(chunks):
        sources = _owners[index] if _owners is not None else ()
        for token in re.findall(r"[\t\n\f\r ]+|[^\t\n\f\r ]+", text):
            if token[0] in "\t\n\f\r ":
                if result:
                    pending = marks
                    pending_sources = tuple(dict.fromkeys((*pending_sources, *sources)))
            else:
                if pending is not None:
                    append(" ", pending, pending_sources)
                    pending = None
                    pending_sources = ()
                append(token, marks, sources)
    if _on_sources is not None:
        _on_sources(tuple(contributions))
    return result


def inline_node(node_type, element, *, _on_contributions=None, **extra):
    sources = []
    runs = inline_runs(element, _on_sources=sources.extend if _on_contributions else None)
    node = {"type": node_type, "text": "".join(run["text"] for run in runs), **extra}
    if any(run["marks"] for run in runs):
        node["inline"] = runs
    if _on_contributions is not None:
        _on_contributions(node, tuple(sources))
    return node
