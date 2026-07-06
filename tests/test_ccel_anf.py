"""Tests for the ANF CCEL parser."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers import ccel_anf  # noqa: E402


def test_config_uses_existing_irenaeus_author_id():
    work = ccel_anf.VOLUME_CONFIG["anf01"]["works"][0]
    assert work["slug"] == "irenaeus-against-heresies"
    assert work["author_id"] == "irenaeus"
    assert work["book_div_ids"] == ["ix.ii", "ix.iii", "ix.iv", "ix.vi", "ix.vii"]


def test_chapter_title_split():
    label, title = ccel_anf.split_chapter_label("Chapter II.—The world was not formed by angels.")
    assert label == "Chapter II"
    assert title == "The world was not formed by angels"


@pytest.mark.raw_required(ccel_anf.VOLUME_CONFIG["anf01"]["raw_file"])
def test_cached_irenaeus_parse_shape():
    raw_file = ccel_anf.VOLUME_CONFIG["anf01"]["raw_file"]
    work = ccel_anf.VOLUME_CONFIG["anf01"]["works"][0]
    result = ccel_anf.parse_volume_work("anf01", work, raw_file.read_bytes())
    assert result["work_id"] == "irenaeus-against-heresies"
    assert len(result["sections"]) == 5
    assert [section["label"] for section in result["sections"]] == [
        "Book I",
        "Book II",
        "Book III",
        "Book IV",
        "Book V",
    ]
    assert sum(len(section["children"]) for section in result["sections"]) == 173
    assert all(section["title"] for section in result["sections"])
    assert all(child["content_blocks"] for section in result["sections"] for child in section["children"])
