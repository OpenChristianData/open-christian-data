"""Shared helpers for CCEL ThML parsers."""
from __future__ import annotations

import html
from pathlib import Path
import re

from lxml import etree

XML_SAFE_ENTITIES = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}
_EXTRA_ENTITIES = {
    "&emdash;": "-",
    "&mdash;": "-",
    "&ndash;": "-",
    "&lsquo;": "'",
    "&rsquo;": "'",
    "&ldquo;": '"',
    "&rdquo;": '"',
    "&nbsp;": " ",
}
_SKIP_TEXT_TAGS = frozenset({"note", "pb", "insertIndex", "style", "selector", "scripContext"})


def _replace_entity(match: re.Match[str]) -> str:
    entity = match.group(0)
    if entity in XML_SAFE_ENTITIES:
        return entity
    if entity in _EXTRA_ENTITIES:
        return _EXTRA_ENTITIES[entity]
    unescaped = html.unescape(entity)
    return "" if unescaped == entity else unescaped


def preprocess_thml(raw_bytes: bytes) -> str:
    """Decode CCEL ThML, strip DOCTYPE, and replace HTML named entities."""
    try:
        text = raw_bytes.decode("utf-8")
        if "\ufffd" in text:
            raise UnicodeDecodeError("utf-8", raw_bytes, 0, 1, "replacement chars found")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
    return re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text)


def display_path(path: Path) -> str:
    """Return a stable repository-relative path when the path is below cwd."""

    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def parse_thml(xml_path: Path) -> etree._Element:
    """Preprocess and strictly parse one retained CCEL ThML document."""

    prepared = preprocess_thml(xml_path.read_bytes()).encode("utf-8")
    parser = etree.XMLParser(huge_tree=True, resolve_entities=False)
    try:
        return etree.fromstring(prepared, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(
            f"Could not parse ThML XML at {display_path(xml_path)}: {exc}"
        ) from exc


def get_all_text(elem) -> str:
    """Recursively collect text, skipping footnotes, page breaks, and style blocks."""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag in _SKIP_TEXT_TAGS:
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(get_all_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def clean_text(text: str) -> str:
    """Collapse whitespace and trim."""
    return re.sub(r"\s+", " ", text).strip()


def get_scriptrefs(elem) -> list[dict[str, object]]:
    """Collect scripture references from ThML scripRef nodes."""
    refs: list[dict[str, object]] = []
    for sr in elem.iter("scripRef"):
        raw_text = clean_text(get_all_text(sr))
        osis_list: list[str] = []
        for part in sr.get("osisRef", "").split():
            cleaned = re.sub(r"^Bible(?:\.[a-z]+)?:", "", part).strip()
            if cleaned:
                osis_list.append(cleaned)
        if raw_text or osis_list:
            refs.append({"raw": raw_text, "osis": osis_list})
    return refs


def count_words(blocks: list[str]) -> int:
    """Count whitespace-delimited words in paragraph blocks."""
    return sum(len(block.split()) for block in blocks)
