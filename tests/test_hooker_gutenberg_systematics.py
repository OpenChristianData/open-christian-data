"""Focused tests for the Hooker Ecclesiastical Polity parser path."""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.gutenberg_systematics import (  # noqa: E402
    _HOOKER_BOOK_RE,
    _HOOKER_CHAPTER_RE,
    _HOOKER_EXPECTED_CHAPTERS,
    _WORK_BY_SLUG,
    _build_hooker_locator_table,
    prepare_ia_lines,
    parse_hooker,
)
from build.lib.pytest_skips import skip_if_missing_data  # noqa: E402

HOOKER_SOURCE_FILES = [
    REPO_ROOT / "raw" / "gutenberg" / "worksofrichardho0001hook_djvu.txt",
    REPO_ROOT / "raw" / "gutenberg" / "worksofrichardho0002hook_djvu.txt",
    REPO_ROOT / "raw" / "gutenberg" / "worksofrichardho0003hook_pt1_djvu.txt",
]


def test_hooker_config_is_registered():
    cfg = _WORK_BY_SLUG["hooker-ecclesiastical-polity"]

    assert cfg["source_type"] == "ia_multi"
    assert [vol["volume"] for vol in cfg["ia_volumes"]] == [1, 2, 3]
    assert cfg["author_id"] == "hooker-richard"
    assert cfg["work_kind"] == "treatise"


def test_hooker_heading_regexes_match_keble_ocr_shapes():
    assert _HOOKER_BOOK_RE.match("BOOK I.")
    assert _HOOKER_BOOK_RE.match("THE FIFTH BOOK.")
    assert _HOOKER_CHAPTER_RE.match("CHAP. I.")
    assert _HOOKER_CHAPTER_RE.match("CHAPTER LXXXI.")


def test_parse_hooker_builds_books_and_chapters_from_sample():
    lines = [
        "THE FIRST BOOK.",
        "",
        "CHAP. I.",
        "",
        "The cause and occasion of handling these things.",
        "",
        "Laws are means to direct us.",
        "",
        "CHAP. II.",
        "",
        "That law which natural agents have given them.",
        "",
        "THE SECOND BOOK.",
        "",
        "CHAP. I.",
        "",
        "Concerning their first position.",
    ]

    sections = parse_hooker(lines, [])

    assert [section["label"] for section in sections] == ["Book I", "Book II"]
    assert len(sections[0]["children"]) == 2
    assert sections[0]["children"][0]["label"] == "Chapter I"
    assert sections[0]["children"][0]["content_blocks"] == [
        "The cause and occasion of handling these things.",
        "Laws are means to direct us.",
    ]


def test_parse_hooker_ignores_selected_editorial_apparatus():
    lines = [
        "THE FIRST BOOK.",
        "",
        "CHAP. I.",
        "",
        "OF THE LAWS OF ECCLESIASTICAL POLITY.",
        "",
        "[Greek: logos]",
        "",
        "This authored sentence remains.",
        "",
        "ENDNOTES",
        "",
        "This late apparatus is not part of the parsed chapter.",
    ]

    sections = parse_hooker(lines, [])
    blocks = sections[0]["children"][0]["content_blocks"]

    assert blocks == ["[Greek: logos]", "This authored sentence remains."]


def _real_hooker_lines() -> list[str]:
    for path in HOOKER_SOURCE_FILES:
        skip_if_missing_data(path)
    text = "\n\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in HOOKER_SOURCE_FILES
    )
    return prepare_ia_lines(text)


def test_hooker_locator_table_covers_all_real_chapters():
    locators = _build_hooker_locator_table(_real_hooker_lines())
    expected_pairs = {
        (book, chapter)
        for book, chapter_count in _HOOKER_EXPECTED_CHAPTERS.items()
        for chapter in range(1, chapter_count + 1)
    }

    assert set(locators) == expected_pairs
    assert len(locators) == 169


def test_hooker_locator_table_has_no_synthetic_locators():
    locators = _build_hooker_locator_table(_real_hooker_lines())

    assert {locator["locator_type"] for locator in locators.values()} <= {
        "inline_heading",
        "running_header",
        "toc_derived",
        "manual_review",
    }
    assert all(locator["locator_type"] != "synthetic" for locator in locators.values())


def test_hooker_regenerated_json_has_boundary_confidence_on_every_chapter():
    data = json.loads(
        (REPO_ROOT / "data" / "structured-text" / "hooker-ecclesiastical-polity.json")
        .read_text(encoding="utf-8")
    )
    chapters = [
        chapter
        for book in data["data"]["sections"]
        for chapter in book["children"]
    ]

    assert len(chapters) == 169
    assert all("boundary_confidence" in chapter for chapter in chapters)
    assert all(chapter["boundary_confidence"] != "synthetic" for chapter in chapters)
