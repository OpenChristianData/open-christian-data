"""Tests for build/tei/census.py — the raw-source feature census.

The census is the raw->TEI fidelity oracle: for a raw source it records, per
feature, the count and the full list of source IDs (where the source carries
IDs). The TEI conversion gate compares the emitted TEI against this census, so
a converter cannot silently drop what the raw had.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tei.census import CENSUS_SCHEMA_ID, census_ccel_work, census_se_work, census_thml_div1

# ---------------------------------------------------------------------------
# ThML fixture: the shapes that matter in CCEL NPNF volumes, miniaturized.
# ---------------------------------------------------------------------------

THML_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<ThML>
  <ThML.head></ThML.head>
  <ThML.body>
    <div1 id="iv" title="City of God" type="Work">
      <div2 id="iv.i" title="Translator's Preface">
        <p id="iv.i-p1">Preface text <i>italic run</i> here.</p>
      </div2>
      <div2 id="iv.ii" title="Book I" type="Book">
        <div3 id="iv.ii.i" title="Chapter 1 title">
          <p id="iv.ii.i-p1">Text with a footnote<note place="end" n="1"
            id="iv.ii.i-p1.1"><p>note body</p></note> and more.</p>
          <pb n="2" id="iv.ii-Page_2" />
          <p id="iv.ii.i-p2">A verse <scripRef id="iv.ii.i-p2.1"
            passage="Rom 9:1">Rom. ix. 1</scripRef> and
            <span lang="EL" id="iv.ii.i-p2.2">Greek</span>.</p>
        </div3>
        <div3 id="iv.ii.ii" title="Chapter 2 title">
          <p id="iv.ii.ii-p1">Second chapter.</p>
        </div3>
      </div2>
    </div1>
    <div1 id="v" title="Another Work">
      <div2 id="v.i" title="Ignored"><p id="v.i-p1">Out of scope.</p></div2>
    </div1>
  </ThML.body>
</ThML>
"""


@pytest.fixture()
def thml_file(tmp_path: Path) -> Path:
    p = tmp_path / "sample.xml"
    p.write_text(THML_SAMPLE, encoding="utf-8")
    return p


def test_thml_census_scopes_to_the_requested_div1(thml_file: Path) -> None:
    census = census_thml_div1(thml_file, div1_id="iv")
    feats = census["features"]
    # div1 'v' content must not leak in.
    assert "v.i-p1" not in feats["paragraphs"]["ids"]
    assert feats["divisions_level2"]["count"] == 2
    assert feats["divisions_level2"]["ids"] == ["iv.i", "iv.ii"]
    assert feats["divisions_level3"]["ids"] == ["iv.ii.i", "iv.ii.ii"]


def test_thml_census_counts_and_ids(thml_file: Path) -> None:
    census = census_thml_div1(thml_file, div1_id="iv")
    feats = census["features"]
    assert feats["paragraphs"]["count"] == 4
    assert feats["notes"] == {"count": 1, "ids": ["iv.ii.i-p1.1"]}
    assert feats["page_breaks"] == {"count": 1, "ids": ["iv.ii-Page_2"]}
    assert feats["scripture_refs"] == {"count": 1, "ids": ["iv.ii.i-p2.1"]}
    assert feats["italics"]["count"] == 1  # <i> carries no id in ThML
    assert feats["lang_spans"] == {"count": 1, "ids": ["iv.ii.i-p2.2"]}


def test_thml_census_records_titles_for_structure(thml_file: Path) -> None:
    census = census_thml_div1(thml_file, div1_id="iv")
    titles = census["structure_titles"]
    assert titles["iv.ii"] == "Book I"
    assert titles["iv.ii.i"] == "Chapter 1 title"


def test_thml_census_envelope(thml_file: Path) -> None:
    census = census_thml_div1(thml_file, div1_id="iv")
    assert census["census_schema"] == CENSUS_SCHEMA_ID
    assert census["source"]["path"].endswith("sample.xml")
    assert census["source"]["sha256"]  # non-empty content hash
    assert census["source"]["scope"] == "div1[@id='iv']"


def test_thml_census_unknown_div1_raises(thml_file: Path) -> None:
    with pytest.raises(ValueError, match="div1"):
        census_thml_div1(thml_file, div1_id="nope")


def test_ccel_work_census_uses_config_scope_and_extended_carriers(tmp_path: Path) -> None:
    raw = tmp_path / "raw.xml"
    raw.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<ThML>
  <ThML.head></ThML.head>
  <ThML.body>
    <div1 id="i" title="Configured work">
      <div2 id="i.i" type="Titlepage" title="Title page."><p id="skip-p1">Skip.</p></div2>
      <div2 id="i.ii" type="Chapter" title="Chapter I.">
        <h1 id="i.ii-h1">Chapter I.</h1>
        <argument id="i.ii-arg1"><p id="i.ii-arg1-p1">Argument.</p></argument>
        <p id="i.ii-p1"><name id="i.ii-p1.1">Name</name><cite id="i.ii-p1.2">Citation</cite></p>
        <table id="i.ii-table1"><tr id="i.ii-row1"><td id="i.ii-cell1">Cell</td></tr></table>
      </div2>
    </div1>
  </ThML.body>
</ThML>
""",
        encoding="utf-8",
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "works": [
                    {
                        "work_id": "configured-work",
                        "rendering_id": "ccel-configured",
                        "raw_path": "raw.xml",
                        "scope": {"tag": "div1", "id": "i"},
                        "division_rules": [
                            {"tag": "div2", "source_type": "Titlepage", "skip": True},
                            {"tag": "div2", "source_type": "Chapter", "tei_type": "chapter", "place": "body"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    census = census_ccel_work(config, "configured-work", repo_root=tmp_path)
    features = census["features"]

    assert census["source"]["scope"] == "div1[@id='i']"
    assert features["divisions"]["ids"] == ["i.ii"]
    assert features["paragraphs"]["ids"] == ["i.ii-arg1-p1", "i.ii-p1"]
    assert features["arguments"]["ids"] == ["i.ii-arg1"]
    assert features["headings"]["ids"] == ["i.ii-h1"]
    assert features["names"]["ids"] == ["i.ii-p1.1"]
    assert features["citations"]["ids"] == ["i.ii-p1.2"]
    assert features["tables"]["ids"] == ["i.ii-table1"]
    assert features["table_rows"]["ids"] == ["i.ii-row1"]
    assert features["table_cells"]["ids"] == ["i.ii-cell1"]


# ---------------------------------------------------------------------------
# Standard Ebooks fixture: nested same-file sections, bridgeheads, noterefs
# resolving to endnotes.xhtml (post-2026 SE vocabulary: bare <li id="note-N">,
# epub:type carried on anchors, se:bridgehead on the title paragraphs).
# ---------------------------------------------------------------------------

SE_BOOK = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Book I</title></head>
<body epub:type="bodymatter z3998:non-fiction">
  <section id="book-1" epub:type="division">
    <h3><span epub:type="se:label">Book</span> <span epub:type="z3998:ordinal z3998:roman">I</span></h3>
    <p epub:type="se:bridgehead">Book argument sentence.</p>
    <section id="preface-1" epub:type="preface">
      <p epub:type="se:bridgehead">Explaining his design.</p>
      <p>Preface prose<a href="endnotes.xhtml#note-1" id="noteref-1" epub:type="noteref">1</a>.</p>
    </section>
    <section id="chapter-1-1" epub:type="chapter">
      <h4 epub:type="z3998:ordinal z3998:roman">I</h4>
      <p epub:type="se:bridgehead">Of the adversaries of the name of Christ.</p>
      <p>Chapter prose with <em>emphasis</em> and
         <blockquote epub:type="z3998:verse"><p>a verse line</p></blockquote>
         <a href="endnotes.xhtml#note-2" id="noteref-2" epub:type="noteref">2</a>.</p>
    </section>
  </section>
</body>
</html>
"""

SE_ENDNOTES = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Endnotes</title></head>
<body epub:type="backmatter">
  <section id="endnotes" epub:type="endnotes">
    <ol>
      <li id="note-1"><p>First note body. <a href="book-1.xhtml#noteref-1" epub:type="backlink">↩</a></p></li>
      <li id="note-2"><p>Second note body. <a href="book-1.xhtml#noteref-2" epub:type="backlink">↩</a></p></li>
    </ol>
  </section>
</body>
</html>
"""


@pytest.fixture()
def se_work_dir(tmp_path: Path) -> Path:
    text_dir = tmp_path / "src" / "epub" / "text"
    text_dir.mkdir(parents=True)
    (text_dir / "book-1.xhtml").write_text(SE_BOOK, encoding="utf-8")
    (text_dir / "endnotes.xhtml").write_text(SE_ENDNOTES, encoding="utf-8")
    return tmp_path


def test_se_census_sections_are_nested_and_typed(se_work_dir: Path) -> None:
    census = census_se_work(se_work_dir)
    feats = census["features"]
    assert feats["sections"]["count"] == 3
    assert feats["sections"]["ids"] == ["book-1", "preface-1", "chapter-1-1"]
    # nesting recorded so the collapse bug class is visible in the census
    depths = census["section_depths"]
    assert depths["book-1"] == 1
    assert depths["chapter-1-1"] == 2


def test_se_census_notes_resolve_to_endnotes(se_work_dir: Path) -> None:
    census = census_se_work(se_work_dir)
    feats = census["features"]
    assert feats["noterefs"] == {"count": 2, "ids": ["noteref-1", "noteref-2"]}
    assert feats["endnotes"] == {"count": 2, "ids": ["note-1", "note-2"]}
    # every noteref must resolve to an existing endnote id
    assert census["unresolved_noterefs"] == []


def test_se_census_detects_dangling_noteref(tmp_path: Path) -> None:
    text_dir = tmp_path / "src" / "epub" / "text"
    text_dir.mkdir(parents=True)
    broken = SE_BOOK.replace("endnotes.xhtml#note-2", "endnotes.xhtml#note-99")
    (text_dir / "book-1.xhtml").write_text(broken, encoding="utf-8")
    (text_dir / "endnotes.xhtml").write_text(SE_ENDNOTES, encoding="utf-8")
    census = census_se_work(tmp_path)
    assert census["unresolved_noterefs"] == ["noteref-2"]


def test_se_census_bridgeheads_emphasis_verse(se_work_dir: Path) -> None:
    census = census_se_work(se_work_dir)
    feats = census["features"]
    assert feats["bridgeheads"]["count"] == 3
    assert feats["emphasis"]["count"] == 1
    assert feats["verse_blocks"]["count"] == 1


def test_census_json_serializable(thml_file: Path, se_work_dir: Path) -> None:
    for census in (
        census_thml_div1(thml_file, div1_id="iv"),
        census_se_work(se_work_dir),
    ):
        json.dumps(census)  # must not raise
