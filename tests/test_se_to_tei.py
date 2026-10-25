from __future__ import annotations

import json
import base64
import subprocess
from pathlib import Path

import pytest
from lxml import etree

from build.tei.se_to_tei import ConversionError, _git_head_or_empty, convert_se_to_tei
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.writer import TEI_NS

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
NS = {"tei": TEI_NS}


def test_git_trust_is_limited_to_this_invocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="abc123\n")

    monkeypatch.setattr(subprocess, "run", run)
    assert _git_head_or_empty(tmp_path) == "abc123"
    assert calls == [([
        "git", "-c", f"safe.directory={tmp_path.resolve().as_posix()}",
        "-C", str(tmp_path), "rev-parse", "HEAD",
    ], {"check": True, "capture_output": True, "text": True})]

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
                "contributors": [
                    {"name": "Marcus Dods", "role": "translator"},
                    {"name": "George Wilson", "role": "translator"},
                    {"name": "J. J. Smith", "role": "translator"},
                ],
                "source_url": "https://standardebooks.org/ebooks/example",
                "source_revision": "6290cb26fa2cac6ef2f9105c9176a97ee3f46b94",
                "source_revision_type": "git-commit-sha1",
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


def test_whitespace_between_inline_elements_is_not_deleted(
    se_work_dir: Path, config_path: Path, tmp_path: Path,
) -> None:
    source = se_work_dir / "src/epub/text/book-1.xhtml"
    source.write_text(SE_BOOK.replace("Preface prose", '<abbr>Mr.</abbr> <abbr>G.</abbr> Chesterton; <i>by</i>\n <b>George</b>'), encoding="utf-8")
    output = tmp_path / "inline-spacing.xml"
    convert_se_to_tei(se_work_dir, config_path, output)
    tree = etree.parse(str(output))
    paragraph = tree.xpath('//tei:div[@xml:id="preface-1-1"]/tei:p', namespaces=NS)[0]
    assert "Mr. G. Chesterton; by George" in "".join(paragraph.itertext())


def test_materialized_images_reopen_beside_tei_with_exact_bytes(
    se_work_dir: Path, config_path: Path, tmp_path: Path,
) -> None:
    image_bytes = b'<svg xmlns="http://www.w3.org/2000/svg"><text>Logo</text></svg>'
    images = se_work_dir / "src/epub/images"
    images.mkdir()
    (images / "logo.svg").write_bytes(image_bytes)
    source = se_work_dir / "src/epub/text/book-1.xhtml"
    source.write_text(SE_BOOK.replace("Preface prose", 'Preface <img src="../images/logo.svg" alt="Logo"/> prose'), encoding="utf-8")
    output = tmp_path / "candidate/book.xml"
    result = convert_se_to_tei(se_work_dir, config_path, output, materialize_assets=True)
    graphic = etree.parse(str(output)).find(".//tei:graphic", NS)
    asset_path = output.parent / graphic.get("url")
    assert asset_path.read_bytes() == image_bytes
    assert result.asset_paths == (asset_path,)
    assert asset_path.parent == output.with_name("book.xml.assets")
    before = output.read_bytes()
    second = convert_se_to_tei(se_work_dir, config_path, output, materialize_assets=True)
    assert second.asset_paths == result.asset_paths
    assert output.read_bytes() == before
    assert validate_file(output) == []


@pytest.mark.parametrize("src", ["../../../outside.svg", "https://example.org/logo.svg", "../images/missing.svg"])
def test_materialized_images_reject_unbound_assets_before_output(
    se_work_dir: Path, config_path: Path, tmp_path: Path, src: str,
) -> None:
    source = se_work_dir / "src/epub/text/book-1.xhtml"
    source.write_text(SE_BOOK.replace("Preface prose", f'Preface <img src="{src}"/> prose'), encoding="utf-8")
    output = tmp_path / "candidate/refused.xml"
    with pytest.raises(ConversionError, match="Image source|Missing retained image"):
        convert_se_to_tei(se_work_dir, config_path, output, materialize_assets=True)
    assert not output.exists()


@pytest.mark.parametrize("replacement,expected", [
    ('#missing-reference', 'Unresolved note graph'),
    ('#noteref-1" id="note-1', 'Duplicate TEI IDs'),
])
def test_invalid_endnote_graph_fails_before_output(
    se_work_dir: Path, config_path: Path, tmp_path: Path, replacement: str, expected: str,
) -> None:
    source = se_work_dir / "src/epub/text/endnotes.xhtml"
    source.write_text(SE_ENDNOTES.replace('#noteref-1', replacement), encoding="utf-8")
    output = tmp_path / "invalid-notes.xml"
    with pytest.raises(ConversionError, match=expected):
        convert_se_to_tei(se_work_dir, config_path, output)
    assert not output.exists()


@pytest.mark.parametrize("placement", ["block", "inline", "header"])
def test_image_reference_description_and_semantics_survive(
    se_work_dir: Path, config_path: Path, tmp_path: Path, placement: str,
) -> None:
    source = se_work_dir / "src/epub/text/book-1.xhtml"
    image = '<img id="publisher-image" src="../images/logo.svg" alt="The Standard Ebooks logo." epub:type="z3998:publisher-logo"/>'
    if placement == "inline":
        content = SE_BOOK.replace("Preface prose", "Preface " + image + " prose")
    elif placement == "header":
        content = SE_BOOK.replace("<header>", "<header>" + image, 1)
    else:
        content = SE_BOOK.replace("<p>Preface prose", image + "<p>Preface prose")
    source.write_text(content, encoding="utf-8")
    output = tmp_path / "images.xml"
    convert_se_to_tei(se_work_dir, config_path, output)
    tree = etree.parse(str(output))
    figures = tree.xpath('//tei:figure[@xml:id="publisher-image"]', namespaces=NS)
    assert len(figures) == 1
    assert figures[0].get("ana") == "z3998:publisher-logo"
    assert figures[0].find("tei:graphic", NS).get("url") == "../images/logo.svg"
    assert figures[0].findtext("tei:figDesc", namespaces=NS) == "The Standard Ebooks logo."
    assert validate_file(output) == []


@pytest.mark.parametrize("token,tag,tei_tag", [
    ("z3998:event", "span", "seg"),
    ("z3998:nationality", "span", "seg"),
    ("z3998:truncation", "abbr", "abbr"),
    ("se:name.publication.magazine", "i", "hi"),
    ("se:name.publication.newspaper", "i", "hi"),
    ("se:name.publication.pamphlet", "i", "hi"),
    ("se:name.publication.short-story", "i", "hi"),
    ("se:name.music.opera", "i", "hi"),
    ("se:name.visual-art.sculpture", "i", "hi"),
])
def test_retained_work_semantics_preserve_token_text_and_inline_order(
    se_work_dir: Path, config_path: Path, tmp_path: Path,
    token: str, tag: str, tei_tag: str,
) -> None:
    source = se_work_dir / "src/epub/text/book-1.xhtml"
    source.write_text(SE_BOOK.replace("Chapter prose with", f'Before <{tag} epub:type="{token}" id="semantic-case">a named work</{tag}> after. Chapter prose with'), encoding="utf-8")
    output = tmp_path / "semantics.xml"
    convert_se_to_tei(se_work_dir, config_path, output)
    tree = etree.parse(str(output))
    node = tree.xpath('//*[@xml:id="semantic-case"]')[0]
    assert etree.QName(node).localname == tei_tag
    assert node.get("ana") == token
    assert node.text == "a named work"
    assert node.tail.startswith(" after.")
    assert node.getparent().text == "Before "
    if tag == "i":
        assert node.get("rend") == "italic"


def test_hgroup_preserves_title_subtitle_identity_and_block_boundary(
    se_work_dir: Path, config_path: Path, tmp_path: Path,
) -> None:
    source = se_work_dir / "src/epub/text/book-1.xhtml"
    original = '<h4 epub:type="z3998:ordinal z3998:roman">I</h4>'
    replacement = '<hgroup id="heading-group"><h4 epub:type="title" id="title-part">Introduction</h4><p epub:type="subtitle" id="subtitle-part">The <em>Plan</em> of This Book</p></hgroup>'
    source.write_text(SE_BOOK.replace(original, replacement), encoding="utf-8")
    output = tmp_path / "subtitle.xml"
    convert_se_to_tei(se_work_dir, config_path, output)
    tree = etree.parse(str(output))
    group = tree.xpath('//*[@xml:id="heading-group"]')[0]
    assert [etree.QName(n).localname for n in group] == ["seg", "lb", "seg"]
    assert group[0].get("type") == group[0].get("ana") == "title"
    assert group[2].get("type") == group[2].get("ana") == "subtitle"
    assert group[2].get(XML_ID) == "subtitle-part"
    assert "".join(group[2].itertext()) == "The Plan of This Book"
    assert group[2][0].tag == f"{{{TEI_NS}}}emph"
    assert validate_file(output) == []


def test_hgroup_preserves_fulltitle_role(
    se_work_dir: Path, config_path: Path, tmp_path: Path,
) -> None:
    source = se_work_dir / "src/epub/text/book-1.xhtml"
    replacement = '<hgroup epub:type="fulltitle"><h4 epub:type="title">Preface</h4><p epub:type="subtitle">A short subtitle</p></hgroup>'
    source.write_text(SE_BOOK.replace('<h4 epub:type="title">Preface</h4>', replacement, 1), encoding="utf-8")
    output = tmp_path / "fulltitle.xml"
    convert_se_to_tei(se_work_dir, config_path, output)
    group = etree.parse(str(output)).xpath('//*[@xml:id="preface-1-1"]', namespaces=NS)[0]
    assert group.find("tei:head", NS).get("ana") == "fulltitle"
    assert validate_file(output) == []


def test_hgroup_rejects_unknown_semantics(se_work_dir: Path, config_path: Path, tmp_path: Path) -> None:
    source = se_work_dir / "src/epub/text/book-1.xhtml"
    source.write_text(SE_BOOK.replace('<h4 epub:type="title">Preface</h4>', '<hgroup><h4 epub:type="unmapped-role">Preface</h4></hgroup>'), encoding="utf-8")
    with pytest.raises(ConversionError, match="unmapped-role"):
        convert_se_to_tei(se_work_dir, config_path, tmp_path / "refused.xml")


def test_convert_se_to_tei_preserves_nested_sections_and_source_endnote_graph(
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

    reference = tree.xpath("//tei:ref[@type='note']", namespaces=NS)[0]
    assert reference.get(XML_ID) == "noteref-1"
    assert reference.get("target") == "#note-1"
    assert reference.text == "1"
    note = tree.xpath("//tei:back/tei:div[@type='endnotes']/tei:list/tei:item[@xml:id='note-1']", namespaces=NS)[0]
    assert "First note body." in " ".join(note.itertext())
    backlink = note.xpath(".//tei:ref[@type='backlink']", namespaces=NS)[0]
    assert backlink.get("target") == "#noteref-1"
    assert backlink.text == "↩"
    assert validate_file(output) == []


def test_convert_se_to_tei_preserves_contributor_roles_and_git_revision(
    se_work_dir: Path,
    config_path: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out.xml"

    convert_se_to_tei(se_work_dir, config_path, output)

    tree = etree.parse(str(output))
    resp_stmts = tree.xpath("//tei:titleStmt/tei:respStmt", namespaces=NS)
    assert [stmt.findtext("tei:resp", namespaces=NS) for stmt in resp_stmts] == [
        "translator",
        "translator",
        "translator",
    ]
    assert tree.xpath("//tei:sourceDesc//tei:idno/@type", namespaces=NS) == [
        "git-commit-sha1"
    ]
    assert tree.xpath("string(//tei:sourceDesc//tei:idno)", namespaces=NS) == (
        "6290cb26fa2cac6ef2f9105c9176a97ee3f46b94"
    )


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


def test_convert_se_to_tei_supports_retained_paradise_lost_poem_sections(
    tmp_path: Path,
) -> None:
    work_dir = Path("raw/standard_ebooks/john-milton_paradise-lost")
    config = Path("sources/standard-ebooks/john-milton_paradise-lost/config.json")
    config_payload = json.loads(config.read_text(encoding="utf-8"))
    config_payload["source_revision"] = "6290cb26fa2cac6ef2f9105c9176a97ee3f46b94"
    config_payload["source_revision_type"] = "git-commit-sha1"
    pinned_config = tmp_path / "paradise-lost-config.json"
    pinned_config.write_text(json.dumps(config_payload), encoding="utf-8")

    output = tmp_path / "paradise-lost.tei.xml"
    convert_se_to_tei(work_dir, pinned_config, output)

    tree = etree.parse(str(output))
    assert len(tree.xpath("//tei:div[@type='book']", namespaces=NS)) == 12
    assert len(tree.xpath("//tei:div[@type='poem']", namespaces=NS)) == 12
    assert len(tree.xpath("//tei:div[@type='book']/tei:div[@type='argument']", namespaces=NS)) == 12
    assert len(tree.xpath("//tei:div[@type='poem']/tei:lg", namespaces=NS)) == 399
    assert len(tree.xpath("//tei:div[@type='poem']/tei:lg/tei:l", namespaces=NS)) == 10_565
    assert len(tree.xpath("//tei:back//tei:quote/tei:lg/tei:l", namespaces=NS)) == 3
    assert len(tree.xpath("//tei:back//tei:lb", namespaces=NS)) == 17
    assert validate_file(output) == []


@pytest.mark.slow
def test_committed_standard_ebooks_city_of_god_tei_validates_against_vendored_tei_schema() -> None:
    tei_path = Path("ir/augustine/city-of-god.standard-ebooks.tei.xml")
    if not tei_path.exists():
        pytest.skip("Committed Standard Ebooks City of God TEI IR is absent; run the converter first.")

    assert validate_file(tei_path) == []


@pytest.mark.parametrize("work", [
    "george-macdonald_unspoken-sermons",
    "g-k-chesterton_orthodoxy",
    "g-k-chesterton_heretics",
    "g-k-chesterton_the-everlasting-man",
])
@pytest.mark.parametrize("embedded", [False, True])
def test_blocked_work_images_materialize_from_retained_bytes(work: str, tmp_path: Path, embedded: bool) -> None:
    source_root = Path("raw/standard_ebooks") / work
    output = tmp_path / "candidate.xml"
    result = convert_se_to_tei(
        source_root, Path("sources/standard-ebooks") / work / "config.json", output,
        materialize_assets=not embedded, embed_assets=embedded,
    )
    expected = []
    for member in sorted((source_root / "src/epub/text").glob("*.xhtml")):
        for img in etree.parse(str(member)).xpath("//*[local-name()='img']"):
            expected.append((member.parent / img.get("src")).read_bytes())
    urls = etree.parse(str(output)).xpath("//tei:graphic/@url", namespaces=NS)
    actual = [base64.b64decode(url.split(",", 1)[1], validate=True) if embedded else (output.parent / url).read_bytes() for url in urls]
    assert len(actual) == len(expected) == 3
    assert sorted(actual) == sorted(expected)
    assert len(result.asset_paths) == (0 if embedded else len(set(actual)))
    if embedded:
        assert all(url.startswith("data:image/svg+xml;base64,") for url in urls)
        assert list(tmp_path.iterdir()) == [output]
    assert validate_file(output) == []
