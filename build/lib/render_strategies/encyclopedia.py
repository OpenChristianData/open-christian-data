"""Encyclopedia review HTML strategy."""

from __future__ import annotations

import json
import re
from html import escape
from typing import Any


RESOURCE_TYPE = "encyclopedia"


def render_resource(record: dict[str, Any]) -> str:
    entries = _entries(record)
    pages: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, entry in enumerate(entries, start=1):
        pages.setdefault(_headword_page(entry), []).append((index, entry))

    rendered_pages: list[str] = []
    for page_name, page_entries in pages.items():
        rendered_entries = "\n".join(_render_entry(entry, index) for index, entry in page_entries)
        rendered_pages.append(
            "\n".join(
                [
                    f'<section class="headword-page" id="{escape(_page_anchor(page_name))}">',
                    f"<h2>{escape(page_name)}</h2>",
                    rendered_entries,
                    "</section>",
                ]
            )
        )
    return "\n".join(rendered_pages)


def render_navigation(record: dict[str, Any]) -> str:
    nav_items = []
    for index, entry in enumerate(_entries(record), start=1):
        entry_id = str(entry.get("entry_id") or f"entry-{index}")
        term = str(entry.get("term") or f"Entry {index}")
        nav_items.append(f'<li><a href="#{escape(_anchor_id(entry_id, index))}">{escape(term)}</a></li>')
    return f'<ol class="nav-list">{"".join(nav_items)}</ol>'


def _entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    data = record.get("data")
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def _render_entry(entry: dict[str, Any], index: int) -> str:
    entry_id = str(entry.get("entry_id") or f"entry-{index}")
    anchor = _anchor_id(entry_id, index)
    term = str(entry.get("term") or f"Entry {index}")
    return "\n".join(
        [
            f'<article class="entry encyclopedia-entry" id="{escape(anchor)}">',
            '<div class="entry-toolbar">',
            '<span class="entry-type">Entry type: headword</span>',
            f'<a class="entry-id" href="#{escape(anchor)}">{escape(entry_id)}</a>',
            "</div>",
            f"<h3>{escape(term)}</h3>",
            _render_alt_terms(entry.get("alt_terms")),
            _render_definition_blocks(entry.get("definition_blocks")),
            _render_related_terms(entry.get("related_terms")),
            "<details>",
            "<summary>Raw entry JSON</summary>",
            f"<pre>{escape(json.dumps(entry, ensure_ascii=False, indent=2))}</pre>",
            "</details>",
            "</article>",
        ]
    )


def _render_alt_terms(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    items = "".join(f"<li>{escape(str(term))}</li>" for term in value if isinstance(term, str))
    if not items:
        return ""
    return f'<section class="alt-terms"><h4>Alt terms</h4><ul>{items}</ul></section>'


def _render_definition_blocks(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return '<p class="empty-state">No definition blocks supplied.</p>'
    blocks: list[str] = []
    for index, block in enumerate(value, start=1):
        block_text = _block_text(block)
        block_kind = _block_kind(block)
        paragraphs = _paragraphs(block_text)
        body = "\n".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs)
        blocks.append(
            "\n".join(
                [
                    f'<section class="definition-block definition-block-{escape(block_kind)}">',
                    f'<h4>Definition block {index} <span>{escape(block_kind)}</span></h4>',
                    body,
                    "</section>",
                ]
            )
        )
    return "\n".join(blocks)


def _render_related_terms(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    items = "".join(f"<li>{escape(str(term))}</li>" for term in value if isinstance(term, str))
    if not items:
        return ""
    return f'<section class="related-terms"><h4>Related terms</h4><ul>{items}</ul></section>'


def _block_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict) and isinstance(block.get("text"), str):
        return block["text"]
    return str(block)


def _block_kind(block: Any) -> str:
    if isinstance(block, dict) and isinstance(block.get("type"), str):
        return block["type"]
    return "definition"


def _paragraphs(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return paragraphs or ([text.strip()] if text.strip() else [])


def _headword_page(entry: dict[str, Any]) -> str:
    term = str(entry.get("term") or "#")
    first = term[:1].upper()
    return first if first.isalpha() else "#"


def _page_anchor(page_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "-", page_name).strip("-")
    return f"headword-{slug or 'other'}"


def _anchor_id(entry_id: str, index: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "-", entry_id).strip("-")
    if not slug:
        slug = f"entry-{index}"
    return slug
