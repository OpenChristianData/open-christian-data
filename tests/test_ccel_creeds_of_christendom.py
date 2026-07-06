"""Tests for ccel_creeds_of_christendom.py.

Schaff's "The Creeds of Christendom, Vol. I: The History of Creeds" (CCEL ThML)
parsed into the structured_text schema. The ThML nests div1 (chapter) > div2
(section) > div3 (subsection); the parser must recurse all three levels and skip
front/back matter (Title Page, Prefatory, Indexes).

Integration tests are skipped when the raw CCEL XML is absent (gitignored raw/).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.schema_enums import get_enum  # noqa: E402
from build.parsers import ccel_creeds_of_christendom as cc  # noqa: E402

RAW = REPO_ROOT / "raw" / "ccel" / "schaff" / "creeds1.xml"


def _walk(sections):
    for s in sections:
        yield s
        yield from _walk(s.get("children", []))


def test_config_enums_are_schema_valid():
    assert set(cc.WORK_META["tradition"]) <= get_enum("structured_text", "meta", "tradition")
    assert cc.WORK_KIND in get_enum("structured_text", "data", "work_kind")
    assert cc.WORK_META["era"] in get_enum("structured_text", "meta", "era")
    assert cc.WORK_META["audience"] in get_enum("structured_text", "meta", "audience")


@pytest.mark.skipif(not RAW.exists(), reason="raw creeds1.xml not present")
def test_parses_eight_content_chapters():
    data = cc.parse_creeds_volume()
    chapters = data["sections"]
    assert len(chapters) == 8, f"expected 8 content chapters, got {len(chapters)}"
    for ch in chapters:
        assert ch["section_type"] == "chapter"
        assert ch["title"], f"chapter missing title: {ch.get('label')}"
    titles = " ".join((ch.get("title") or "") for ch in chapters).lower()
    assert "index" not in titles
    assert "title page" not in titles
    assert "prefatory" not in titles


@pytest.mark.skipif(not RAW.exists(), reason="raw creeds1.xml not present")
def test_chapter_two_has_section_children():
    data = cc.parse_creeds_volume()
    ch2 = next(
        c for c in data["sections"] if "cumenical" in (c.get("title") or "").lower()
    )
    assert ch2["children"], "Chapter 2 should have section children"
    assert all(s["section_type"] == "section" for s in ch2["children"])
    # one of the sections is the Apostles' Creed discussion
    sec_titles = " ".join((s.get("title") or "") for s in ch2["children"]).lower()
    assert "apostles" in sec_titles


@pytest.mark.skipif(not RAW.exists(), reason="raw creeds1.xml not present")
def test_div3_becomes_subsection():
    data = cc.parse_creeds_volume()
    types = {s["section_type"] for s in _walk(data["sections"])}
    # creeds1.xml has 49 div3 elements; recursion must surface them as subsections
    assert "subsection" in types


@pytest.mark.skipif(not RAW.exists(), reason="raw creeds1.xml not present")
def test_section_shape():
    data = cc.parse_creeds_volume()
    for s in _walk(data["sections"]):
        assert isinstance(s["content_blocks"], list)
        assert all(isinstance(b, str) for b in s["content_blocks"])
        assert isinstance(s["scripture_references"], list)
        assert isinstance(s["word_count"], int)


@pytest.mark.skipif(
    not (REPO_ROOT / "data" / "structured-text" / "creeds-of-christendom-vol-1.json").exists(),
    reason="output not yet generated",
)
def test_output_top_section_count():
    path = REPO_ROOT / "data" / "structured-text" / "creeds-of-christendom-vol-1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["data"]["sections"]) == 8
