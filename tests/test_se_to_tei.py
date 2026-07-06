from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.se_to_tei import ConversionError, convert_se_to_tei
from build.tei.validate import validate_file
from build.tei.writer import TEI_NS

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
NS = {"tei": TEI_NS}

SE_BOOK = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en-GB">
<head><title>Book I</title></head>
<body epub:type="bodymatter z3998:non-fiction">
  <section id="book-1" epub:type="division">
    <header>
      <h3><span epub:type="se:label">Book</span> <span epub:type="z3998:ordinal z3998:roman">I</span></h3>
      <p epub:type="se:bridgehead">Book argument sentence.</p>
    </header>
    <section id="preface-1-1" epub:type="preface">
      <header>
        <h4 epub:type="title">Preface</h4>
        <p epub:type="se:bridgehead">Explaining his design.</p>
      </header>
      <p>Preface prose<a href="endnotes.xhtml#note-1" id="noteref-1" epub:type="noteref">1</a>.</p>
    </section>
    <section id="chapter-1-1" epub:type="chapter">
      <header>
        <h4 epub:type="z3998:ordinal z3998:roman">I</h4>
        <p epub:type="se:bridgehead">Of the adversaries of the name of Christ.</p>
      </header>
      <p>Chapter prose with <em>emphasis</em>, <i xml:lang="la">civitas</i>,
         <span epub:type="z3998:roman">II</span>, and <abbr epub:type="z3998:initialism">AD</abbr>.</p>
      <blockquote epub:type="z3998:verse"><p>a verse line<br/>second line</p></blockquote>
    </section>
  </section>
</body>
</html>
"""

SE_ENDNOTES = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en-GB">
<head><title>Endnotes</title></head>
<body epub:type="backmatter">
  <section id="endnotes" epub:type="endnotes">
    <ol>
      <li id="note-1"><p>First note body. <a href="book-1.xhtml#noteref-1" epub:type="backlink">↩</a></p></li>
    </ol>
  </section>
</body>
</html>
"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <manifest>
    <item href="text/book-1.xhtml" id="book-1.xhtml" media-type="application/xhtml+xml"/>
    <item href="text/endnotes.xhtml" id="endnotes.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="book-1.xhtml"/>
    <itemref idref="endnotes.xhtml"/>
  </spine>
</package>
"""


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "title": "The City of God",
                "author": "Augustine of Hippo",
                "contributors": ["Marcus Dods", "George Wilson", "J. J. Smith"],
                "source_url": "https://standardebooks.org/ebooks/example",
                "source_hash": None,
                "source_edition": "Standard Ebooks test fixture",
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def se_work_dir(tmp_path: Path) -> Path:
    epub = tmp_path / "src" / "epub"
    text = epub / "text"
    text.mkdir(parents=True)
    (epub / "content.opf").write_text(OPF, encoding="utf-8")
    (text / "book-1.xhtml").write_text(SE_BOOK, encoding="utf-8")
    (text / "endnotes.xhtml").write_text(SE_ENDNOTES, encoding="utf-8")
    return tmp_path


def test_convert_se_to_tei_preserves_nested_sections_and_inline_notes(
    se_work_dir: Path,
    config_path: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out.xml"

    result = convert_se_to_tei(se_work_dir, config_path, output)

    assert result.output_path == output
    tree = etree.parse(str(output))
    book = tree.xpath("//tei:body/tei:div[@type='book' and @xml:id='book-1']", namespaces=NS)[0]
    assert book.get("n") == "1"
    assert tree.xpath("normalize-space(//tei:div[@xml:id='book-1']/tei:head)", namespaces=NS) == "Book I"
    assert tree.xpath("count(//tei:div[@xml:id='book-1']/tei:div)", namespaces=NS) == 2
    assert tree.xpath("count(//tei:div[@xml:id='chapter-1-1'])", namespaces=NS) == 1
    assert tree.xpath("string(//tei:div[@xml:id='chapter-1-1']/tei:argument/tei:p)", namespaces=NS).startswith(
        "Of the adversaries"
    )

    note = tree.xpath("//tei:note[@place='end']", namespaces=NS)[0]
    assert note.get("n") == "1"
    assert note.get(XML_ID) == "note-1"
    assert note.get("corresp") == "#noteref-1"
    assert "First note body." in " ".join(note.itertext())
    assert "↩" not in " ".join(note.itertext())


def test_convert_se_to_tei_maps_emphasis_verse_and_semantic_typography(
    se_work_dir: Path,
    config_path: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out.xml"

    convert_se_to_tei(se_work_dir, config_path, output)

    tree = etree.parse(str(output))
    assert tree.xpath("string(//tei:emph)", namespaces=NS) == "emphasis"
    italic = tree.xpath("//tei:hi[@rend='italic']", namespaces=NS)[0]
    assert italic.get(XML_LANG) == "la"
    assert italic.text == "civitas"
    assert tree.xpath("//tei:seg[@ana='z3998:roman']/text()", namespaces=NS) == ["II"]
    assert tree.xpath("//tei:abbr[@ana='z3998:initialism']/text()", namespaces=NS) == ["AD"]
    assert tree.xpath("count(//tei:quote/tei:lg/tei:l)", namespaces=NS) == 2
    assert tree.xpath("//tei:quote/tei:lg/tei:l/text()", namespaces=NS) == ["a verse line", "second line"]


def test_unknown_epub_type_raises(se_work_dir: Path, config_path: Path, tmp_path: Path) -> None:
    book = se_work_dir / "src" / "epub" / "text" / "book-1.xhtml"
    book.write_text(SE_BOOK.replace('epub:type="chapter"', 'epub:type="mystery"'), encoding="utf-8")

    with pytest.raises(ConversionError, match="mystery"):
        convert_se_to_tei(se_work_dir, config_path, tmp_path / "out.xml")


@pytest.mark.slow
def test_committed_standard_ebooks_city_of_god_tei_validates_against_vendored_tei_schema() -> None:
    tei_path = Path("ir/augustine/city-of-god.standard-ebooks.tei.xml")
    if not tei_path.exists():
        pytest.skip("Committed Standard Ebooks City of God TEI IR is absent; run the converter first.")

    assert validate_file(tei_path) == []
