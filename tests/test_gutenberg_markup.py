"""Regression tests for Project Gutenberg inline markup decoding."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.gutenberg_commentary import _build_entry  # noqa: E402
from build.parsers.gutenberg_maclaren import blocks_from_lines  # noqa: E402
from build.lib.pg_inline_markup import decode_pg_inline_markup  # noqa: E402


def test_decode_pg_inline_markup_preserves_non_markup_underscores_and_headings():
    assert (
        decode_pg_inline_markup("_Multi word emphasis_ stays readable; snake_case and http://x_y remain.")
        == "Multi word emphasis stays readable; snake_case and http://x_y remain."
    )
    assert decode_pg_inline_markup("_multi\nline_ emphasis survives wrapping.") == (
        "multi\nline emphasis survives wrapping."
    )
    assert decode_pg_inline_markup('_2:15—_"quoted text"_') == '2:15—"quoted text"'
    assert decode_pg_inline_markup("I. 3] is a heading fragment, not an anchor.") == (
        "I. 3] is a heading fragment, not an anchor."
    )


def test_maclaren_blocks_decode_pg_markup_on_helper_free_path():
    blocks = blocks_from_lines([
        "The _kingdom_ comes [3].",
        "Second line.",
        "",
        "literal snake_case remains.",
    ])

    assert blocks == [
        "The kingdom comes [[pg-note-anchor:3]]. Second line.",
        "literal snake_case remains.",
    ]


def test_commentary_entries_decode_pg_markup_before_json_projection():
    entry = _build_entry(
        "sample-commentary",
        "Col",
        "Colossians",
        51,
        1,
        "3",
        "Col.1.3",
        "A _word_ with [12] anchor.",
    )

    assert entry["commentary_text"] == "A word with [[pg-note-anchor:12]] anchor."
