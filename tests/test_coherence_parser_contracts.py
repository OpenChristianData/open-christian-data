"""Bounded contracts for the maintained parser and scraper paths in Sub #202.

These tests exercise parser symbols with small source-shaped fixtures.  They do
not fetch sources or write repository data; all write-capable paths are pointed
at ``tmp_path``.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from build.parsers import bcp1662, bcp1928, bsb_bible_text
from build.parsers import ccel_devotional, ccel_hodge_systematic, ccel_sermon
from build.parsers import gutenberg_catechisms, gutenberg_theology
from build.parsers import spurgeon_mtp_missing
from build.scrapers import westminster_standard_org


def test_bcp1662_extracts_collect_and_stops_at_epistle() -> None:
    html = """
    <center><strong><a name="Advent1">First Sunday in Advent.</a></strong></center>
    <center><i>The Collect.</i></center>
    <p><strong><img alt="A">LMIGHTY and merciful God, we beseech thee to hear us
    and grant us grace through Jesus Christ our Lord. Amen.</strong></p>
    <center><i>The Epistle.</i></center>
    <p>This epistle text must not enter the collect.</p>
    """

    records, errors = bcp1662.extract_collects_from_html(html, "xmas.html")

    assert errors == 0
    assert records == [
        {
            "anchor": "Advent1",
            "title": "First Sunday in Advent",
            "text": (
                "ALMIGHTY and merciful God, we beseech thee to hear us and grant "
                "us grace through Jesus Christ our Lord. Amen."
            ),
            "source_filename": "xmas.html",
        }
    ]
    prayer = bcp1662.build_prayer_record(records[0])
    assert prayer["prayer_id"] == "advent1"
    assert prayer["word_count"] == len(records[0]["text"].split())


def test_bcp1662_skips_short_collects_without_false_records() -> None:
    html = (
        '<center><strong><a name="Short">Short.</a></strong></center>'
        '<center><i>The Collect.</i></center>'
        '<p>Too brief.</p><center><i>The Gospel.</i></center>'
    )

    records, errors = bcp1662.extract_collects_from_html(html, "xmas.html")

    assert records == []
    assert errors == 0


def test_bcp1928_extracts_collect_and_preserves_record_contract() -> None:
    html = """
    <h2>Advent</h2>
    <center><b><i><font>First Sunday in Advent.</font></i></b></center>
    <center>The Collect.</center>
    <p>Almighty God, give us grace to cast away the works of darkness and put
    upon us the armor of light, now in the time of this mortal life in which thy
    Son Jesus Christ came to visit us in great humility; that in the last day,
    when he shall come again in his glorious majesty to judge the quick and the
    dead, we may rise to the life immortal; through him who liveth and reigneth
    with thee and the Holy Ghost, one God, now and ever. Amen.</p>
    <center>The Epistle.</center>
    """

    records, errors = bcp1928.extract_collects_from_html(html.encode(), "advent1.html")

    assert errors == 0
    assert len(records) == 1
    record = records[0]
    assert record["prayer_id"] == "advent1"
    assert record["title"] == "First Sunday in Advent"
    assert record["content_blocks"][0].endswith("Amen.")
    assert record["word_count"] == len(record["content_blocks"][0].split())


def test_bcp1928_multi_collect_split_and_missing_marker_failure() -> None:
    raw = (
        "<p>First prayer with enough words to be a collect and finish Amen.<br><br>"
        "Second prayer with enough words to be a collect and finish Amen.<br><br>"
        "Third prayer with enough words to be a collect and finish Amen.</p>"
    )

    parts = bcp1928.split_multiple_collects(raw)
    assert len(parts) == 3
    assert all(part.endswith(".") for part in parts)
    assert bcp1928.is_multi_collect("<center>The Collects.</center>")

    records, errors = bcp1928.extract_collects_from_html(
        b"<h2>No collect marker</h2>", "missing.html"
    )
    assert records == []
    assert errors == 1


_BSB_CONFIG = {
    "resource_id": "bsb",
    "title": "Berean Standard Bible",
    "language": "en",
    "tradition": "evangelical",
    "tradition_notes": "bounded fixture",
    "license": "cc0-1.0",
    "source_url": "https://example.test/bsb",
    "source_format": "JSON",
    "source_edition": "fixture",
}


def test_bsb_process_book_writes_bounded_json_and_skips_empty_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bsb_bible_text, "OUTPUT_DIR", tmp_path)
    book = {
        "name": "Genesis",
        "chapters": [
            {
                "chapter": 1,
                "verses": [
                    {"verse": 1, "text": " In the beginning "},
                    {"verse": 2, "text": ""},
                ],
            }
        ],
    }

    dry_stats = bsb_bible_text.process_book(
        book, _BSB_CONFIG, "2026-09-05", "sha256:fixture", dry_run=True
    )
    assert dry_stats["status"] == "dry-run"
    assert dry_stats["verse_count"] == 1
    assert dry_stats["source_verse_count"] == 2
    assert not list(tmp_path.glob("*.json"))

    stats = bsb_bible_text.process_book(
        book, _BSB_CONFIG, "2026-09-05", "sha256:fixture", dry_run=False
    )
    assert stats["status"] == "partial"
    assert stats["skipped_count"] == 1
    output = json.loads((tmp_path / "genesis.json").read_text(encoding="utf-8"))
    assert output["data"] == [
        {
            "osis": "Gen.1.1",
            "chapter": 1,
            "verse": 1,
            "text": "In the beginning",
            "word_count": 3,
        }
    ]

    assert bsb_bible_text.book_slug("1Kgs") == "1-kings"
    assert bsb_bible_text.process_book(
        {"name": "Unknown Book", "chapters": []},
        _BSB_CONFIG,
        "2026-09-05",
        "hash",
        dry_run=True,
    ) == {}


def test_ccel_devotional_entry_extracts_reference_content_and_rejects_bad_id() -> None:
    xml = ET.fromstring(
        """
        <div2 id="d0101am">
          <h3 class="scripPassage"><scripRef osisRef="Bible:Matt.1.1">Matthew 1:1</scripRef></h3>
          <p class="normal">A devotional paragraph with useful words.</p>
          <p><a href="next">Go To Evening Reading</a></p>
          <verse><l>line one</l><l>line two</l></verse>
          <note>editorial note omitted</note>
        </div2>
        """
    )

    entry = ccel_devotional.extract_entry(xml)

    assert entry is not None
    assert entry["entry_id"] == "01-01-morning"
    assert entry["primary_reference"] == {
        "raw": "Matthew 1:1",
        "osis": ["Matt.1.1"],
    }
    assert entry["content_blocks"] == [
        "A devotional paragraph with useful words.",
        "line one\nline two",
    ]
    assert entry["word_count"] == 10
    assert ccel_devotional.extract_entry(
        ET.fromstring('<div2 id="not-a-day"><p>x</p></div2>')
    ) is None


def test_ccel_thml_preprocessing_and_sermon_entry_contract() -> None:
    prepared = ccel_sermon.preprocess_thml(
        b"<!DOCTYPE thml><p>Tom &rsquo;s &unknown; line</p>"
    )
    assert "<!DOCTYPE" not in prepared
    assert "Tom ’s  line" in prepared

    xml = ET.fromstring(
        """
        <div2>
          <h2>Sermon 1</h2>
          <h2>Lord'S Duty Preached at Oxford</h2>
          <h2>Part I</h2>
          <h3><scripRef osisRef="Bible:Eph.2.8">Eph. 2:8.</scripRef></h3>
          <p>body paragraph here.</p>
          <note>footnote omitted</note>
          <verse><l>line one</l></verse>
        </div2>
        """
    )

    entry = ccel_sermon.extract_entry(xml, 1, "Series A", 1)
    assert entry is not None
    assert entry["title"] == "Lord's Duty"
    assert entry["primary_reference"] == {"raw": "Eph. 2:8", "osis": ["Eph.2.8"]}
    assert entry["content_blocks"] == ["body paragraph here.", "line one"]
    assert entry["word_count"] == 5
    assert ccel_sermon.extract_entry(
        ET.fromstring("<div2><h2>Sermon 2</h2></div2>"), 1, "A", 2
    ) is None


def test_ccel_hodge_structure_skips_notes_and_extracts_scripture() -> None:
    div1 = ET.fromstring(
        """
        <div1 id="p1">
          <h2>PART I.</h2><h3>Theology Proper.</h3>
          <div2>
            <h2>CHAPTER I.</h2><h3>Origin.</h3>
            <p>Intro paragraph.</p>
            <div3>
              <p>§ 1. Heading.</p>
              <p>Body sentence one <note>omit this note</note> body sentence two.</p>
              <scripRef osisRef="Bible:Gen.1.1">Gen 1:1</scripRef>
            </div3>
          </div2>
        </div1>
        """
    )

    assert ccel_hodge_systematic.extract_part_label_title(div1, 1) == (
        "Part I",
        "Theology Proper",
    )
    chapter = ccel_hodge_systematic.parse_chapter(div1.find("div2"))
    section = chapter["children"][0]
    assert chapter["label"] == "Chapter I"
    assert chapter["title"] == "Origin"
    assert section["label"] == "§ 1"
    assert section["title"] == "Heading"
    assert section["content_blocks"] == ["Body sentence one body sentence two."]
    assert section["scripture_references"] == [
        {"raw": "Gen 1:1", "osis": ["Gen.1.1"]}
    ]
    assert "omit this note" not in ccel_hodge_systematic.get_all_text(div1)


def test_gutenberg_catechism_parsers_cover_positive_and_gap_paths() -> None:
    small_lines = [
        "I. The Ten Commandments",
        "The First Commandment",
        "What does this mean?",
        "We should fear and love God above all things.",
        "The Second Commandment",
        "What is this?",
    ]
    log_lines: list[str] = []
    entries, errors = gutenberg_catechisms.parse_luther_small(
        small_lines, "luther-small", log_lines
    )
    assert entries[0]["group"] == "I. The Ten Commandments -- The First Commandment"
    assert entries[0]["answer"] == "We should fear and love God above all things."
    assert errors and "empty answer" in errors[0]

    baltimore_lines = [
        "LESSON FIRST",
        "ON THE END OF MAN",
        "1. Q. Who made the world?",
        "A. God made the world and preserves all creatures.",
        "2. Q. Why did God make you?",
    ]
    entries, errors = gutenberg_catechisms.parse_baltimore(
        baltimore_lines, "2", "baltimore-2", []
    )
    assert entries[0]["group"] == "LESSON FIRST: ON THE END OF MAN"
    assert entries[0]["answer"] == "God made the world and preserves all creatures."
    assert entries[1]["answer"] is None
    assert len(errors) == 1

    wrapped = gutenberg_catechisms.strip_pg_wrapper(
        "header\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\nbody\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK X ***\n"
    )
    assert wrapped == ["body"]
    with pytest.raises(ValueError, match="start/end markers"):
        gutenberg_catechisms.strip_pg_wrapper("body without markers")


def test_gutenberg_theology_parsers_build_bounded_section_trees() -> None:
    large_lines = [
        "PREFACE",
        "Preface paragraph one with enough words to retain in the parser output.",
        "",
        "Part First. The Ten Commandments.",
        "The First Commandment.",
        "Paragraph on commandment with enough words to become subsection content.",
        "",
        "Part Second. OF THE CREED.",
        "Article I.",
        "Creed paragraph with enough words for a bounded fixture.",
    ]
    large = gutenberg_theology.parse_luther_large(large_lines, [])
    assert large["work_id"] == "luthers-large-catechism"
    assert [part["label"] for part in large["sections"] if part["section_type"] == "part"] == [
        "Part First",
        "Part Second",
    ]
    first_part = next(s for s in large["sections"] if s.get("label") == "Part First")
    assert first_part["children"][0]["label"] == "The First Commandment"

    calvin = gutenberg_theology.parse_calvin(
        [
            "BOOK I. KNOWLEDGE",
            "Chapter I. The first chapter.",
            "A paragraph from volume one.",
            "",
            "BOOK II. KNOWLEDGE TWO",
            "Chapter I. Another chapter.",
            "Paragraph two.",
        ],
        [
            "BOOK III. KNOWLEDGE THREE",
            "CHAPTER XIV.",
            "CONTINUATION TITLE",
            "Paragraph three.",
            "",
            "BOOK IV. KNOWLEDGE FOUR",
            "CHAPTER I.",
            "FINAL TITLE",
            "Paragraph four.",
        ],
        [],
    )
    assert [section["label"] for section in calvin["sections"]] == [
        "Book I",
        "Book II",
        "Book III",
        "Book IV",
    ]
    book_three = next(s for s in calvin["sections"] if s["label"] == "Book III")
    assert book_three["children"][0]["title"] == "CONTINUATION TITLE"

    augustine = gutenberg_theology.parse_augustine(
        ["BOOK I", "First paragraph here.", "", "BOOK II", "Second paragraph there."],
        [],
    )
    assert [section["label"] for section in augustine["sections"]] == ["Book I", "Book II"]
    assert augustine["sections"][1]["content_blocks"] == ["Second paragraph there."]
    assert gutenberg_theology.strip_pg_wrapper(
        "header\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\nbody\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK X ***\n"
    ) == ["body"]
    with pytest.raises(ValueError, match="start/end markers"):
        gutenberg_theology.strip_pg_wrapper("body without markers")


def test_spurgeon_supplementary_parsers_handle_both_source_shapes() -> None:
    aig = (
        "<div id=\"ipaNodeBody\">A Sermon Delivered on Sunday\n\n"
        "( Genesis 4:10. )\n\nScripture quote from the page\n\n"
        "1. First body paragraph with {a} a cross reference removed.\n\n"
        "2. Second body paragraph long enough to be retained.\n\n"
        "{c}\n\nFootnote definition omitted.</div>"
    ).encode()
    scripture, blocks = spurgeon_mtp_missing.parse_aig(
        aig, spurgeon_mtp_missing.SOURCES[708]
    )
    assert scripture == "Scripture quote from the page"
    assert blocks == [
        "First body paragraph with a cross reference removed.",
        "Second body paragraph long enough to be retained.",
    ]

    archive = (
        "<h1>The Star</h1><blockquote>Scripture quote in the archive text."
        "\u2014Matthew 2:1-2, 9-10.</blockquote>"
        "<p>EE, DEAR hearers, this first body paragraph is long enough for parser testing."
        "<br>Second body paragraph is also long enough to keep.</p>"
        "<p>Collection administered by somebody</p>"
    ).encode()
    scripture, blocks = spurgeon_mtp_missing.parse_archive_spurgeon(
        archive, spurgeon_mtp_missing.SOURCES[1698]
    )
    assert scripture == "Scripture quote in the archive text."
    assert blocks[0].startswith("SEE, DEAR")
    assert all("Collection administered" not in block for block in blocks)

    entry = spurgeon_mtp_missing.build_entry(
        708, spurgeon_mtp_missing.SOURCES[708], scripture, blocks
    )
    assert entry["sermon_id"] == "spurgeon-mtp.708"
    assert entry["word_count"] == sum(len(block.split()) for block in blocks)
    with pytest.raises(ValueError, match="ipaNodeBody"):
        spurgeon_mtp_missing.parse_aig(b"<html />", spurgeon_mtp_missing.SOURCES[708])


class _BytesResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.payload


def test_westminster_scraper_fetch_cache_and_http_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_dir = tmp_path / "raw"
    log_file = tmp_path / "scraper.log"
    raw_dir.mkdir()
    monkeypatch.setattr(westminster_standard_org, "OUTPUT_DIR", raw_dir)
    monkeypatch.setattr(westminster_standard_org, "LOG_FILE", log_file)
    calls: list[str] = []

    def fake_urlopen(request, timeout=30):
        calls.append(request.full_url)
        return _BytesResponse(b"<html><main>bounded Westminster source</main></html>")

    monkeypatch.setattr(westminster_standard_org.urllib.request, "urlopen", fake_urlopen)
    slug = "westminster-shorter-catechism"
    assert westminster_standard_org.fetch_page(slug) == "fetched"
    output = raw_dir / f"{slug}.html"
    assert output.read_bytes().startswith(b"<html>")
    assert len(calls) == 1
    assert westminster_standard_org.fetch_page(slug) == "skipped"
    assert len(calls) == 1

    def fail_urlopen(request, timeout=30):
        raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)

    monkeypatch.setattr(westminster_standard_org.urllib.request, "urlopen", fail_urlopen)
    assert (
        westminster_standard_org.fetch_page(
            "directory-for-family-worship", force=True
        )
        == "failed"
    )
    assert "ERROR fetching directory-for-family-worship" in log_file.read_text(encoding="utf-8")
