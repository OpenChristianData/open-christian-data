"""Project Gutenberg inline-markup normalisation helpers."""

from __future__ import annotations

import re

PG_INLINE_MARKUP_PROVENANCE_NOTE = (
    "Plain-text inline emphasis markers are stripped in the JSON projection; "
    "bare numeric note anchors are tagged as [[pg-note-anchor:N]]."
)

_PG_EMPHASIS_RE = re.compile(r"(?<!\w)_(?!_)([^_]{1,500})_(?!\w)")
_ORPHAN_EMPHASIS_MARKER_RE = re.compile(r"(?<!\w)_(?!\w)")
_PG_NOTE_ANCHOR_RE = re.compile(r"(?<!\[)\[(\d+)\](?!\])")


def decode_pg_inline_markup(text: str) -> str:
    """Convert PG emphasis and note-anchor notation for JSON text fields."""
    for _ in range(4):
        next_text = _PG_EMPHASIS_RE.sub(r"\1", text)
        if next_text == text:
            break
        text = next_text
    text = _ORPHAN_EMPHASIS_MARKER_RE.sub("", text)
    return _PG_NOTE_ANCHOR_RE.sub(r"[[pg-note-anchor:\1]]", text)


def append_pg_inline_markup_note(notes: str | None) -> str:
    """Append the standard PG inline-markup note to provenance notes."""
    if not notes:
        return PG_INLINE_MARKUP_PROVENANCE_NOTE
    if PG_INLINE_MARKUP_PROVENANCE_NOTE in notes:
        return notes
    return f"{notes} {PG_INLINE_MARKUP_PROVENANCE_NOTE}"
