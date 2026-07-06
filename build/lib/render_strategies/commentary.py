"""Commentary review HTML strategy."""

from __future__ import annotations

import json
import re
from html import escape
from typing import Any


RESOURCE_TYPE = "commentary"


def render_resource(record: dict[str, Any]) -> str:
    """Render commentary entries grouped by chapter."""
    entries = _entries(record)
    chapters: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, entry in enumerate(entries, start=1):
        chapter_key = _chapter_key(entry)
        chapters.setdefault(chapter_key, []).append((index, entry))

    rendered_chapters: list[str] = []
    for chapter_key, chapter_entries in chapters.items():
        rendered_entries = "\n".join(_render_entry(entry, index) for index, entry in chapter_entries)
        rendered_chapters.append(
            "\n".join(
                [
                    f'<section class="chapter-page" id="{escape(_chapter_anchor(chapter_key))}">',
                    f"<h2>{escape(chapter_key)}</h2>",
                    rendered_entries,
                    "</section>",
                ]
            )
        )
    return "\n".join(rendered_chapters)


def render_navigation(record: dict[str, Any]) -> str:
    nav_items = []
    for index, entry in enumerate(_entries(record), start=1):
        entry_id = str(entry.get("entry_id") or f"entry-{index}")
        nav_items.append(
            f'<li><a href="#{escape(_anchor_id(entry_id, index))}">{escape(_entry_heading(entry, index))}</a></li>'
        )
    return f'<ol class="nav-list">{"".join(nav_items)}</ol>'


def _entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    data = record.get("data")
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def _render_entry(entry: dict[str, Any], index: int) -> str:
    entry_id = str(entry.get("entry_id") or f"entry-{index}")
    anchor = _anchor_id(entry_id, index)
    entry_type = _entry_type(entry)
    heading = _entry_heading(entry, index)
    cross_refs = entry.get("cross_references")
    if not isinstance(cross_refs, list):
        cross_refs = []

    return "\n".join(
        [
            f'<article class="entry entry-{escape(entry_type)}" id="{escape(anchor)}">',
            '<div class="entry-toolbar">',
            f'<span class="entry-type">Entry type: {escape(entry_type)}</span>',
            f'<a class="entry-id" href="#{escape(anchor)}">{escape(entry_id)}</a>',
            "</div>",
            f"<h3>{escape(heading)}</h3>",
            _render_verse_text(entry),
            _render_text_blocks(str(entry.get("commentary_text") or "")),
            _render_cross_references(cross_refs),
            "<details>",
            "<h4>Raw entry JSON</h4>",
            f"<pre>{escape(json.dumps(entry, ensure_ascii=False, indent=2))}</pre>",
            "</details>",
            "</article>",
        ]
    )


def _render_text_blocks(text: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs and text.strip():
        paragraphs = [text.strip()]
    rendered = []
    for paragraph in paragraphs:
        lines = [escape(line.strip()) for line in paragraph.splitlines() if line.strip()]
        rendered.append(f'<p class="commentary-text">{"<br>".join(lines)}</p>')
    return "\n".join(rendered)


def _render_verse_text(entry: dict[str, Any]) -> str:
    verse_text = entry.get("verse_text")
    if not verse_text:
        return ""
    return "\n".join(
        [
            '<section class="verse-text">',
            "<h4>Verse text</h4>",
            f"<p>{escape(str(verse_text))}</p>",
            "</section>",
        ]
    )


def _render_cross_references(cross_refs: list[Any]) -> str:
    if not cross_refs:
        return ""
    items = "".join(f"<li>{escape(str(ref))}</li>" for ref in cross_refs)
    return f'<section class="cross-refs"><h4>Cross references</h4><ul>{items}</ul></section>'


def _entry_type(entry: dict[str, Any]) -> str:
    if entry.get("verse_range") == "intro":
        return "intro"
    if entry.get("verse_range_osis"):
        return "verse"
    return "unclassified"


def _entry_heading(entry: dict[str, Any], index: int) -> str:
    book = entry.get("book") or entry.get("book_osis") or "Unknown book"
    chapter = entry.get("chapter")
    verse_range = entry.get("verse_range")
    if verse_range == "intro":
        return f"{book} {chapter} introduction" if chapter else f"{book} introduction"
    if chapter is not None and verse_range:
        return f"{book} {chapter}:{verse_range}"
    return f"Entry {index}"


def _chapter_key(entry: dict[str, Any]) -> str:
    book = str(entry.get("book") or entry.get("book_osis") or "Unknown book")
    chapter = entry.get("chapter")
    if chapter in (None, "", 0):
        return book
    return f"{book} {chapter}"


def _chapter_anchor(chapter_key: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "-", chapter_key).strip("-")
    return f"chapter-{slug or 'unknown'}"


def _anchor_id(entry_id: str, index: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "-", entry_id).strip("-")
    if not slug:
        slug = f"entry-{index}"
    return slug
