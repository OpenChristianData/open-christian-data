from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.thml_to_tei import ConversionError, convert_ccel_work_to_tei, convert_thml_to_tei
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.writer import TEI_NS

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NS = {"tei": TEI_NS}

THML_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<ThML>
  <ThML.head>
    <printSourceInfo>New York: The Christian Literature Publishing Co., 1890</printSourceInfo>
  </ThML.head>
  <ThML.body>
    <div1 id="iv" title="City of God">
      <pb n="ix" id="iv-Page_ix" href="/ignored.html" />
      <p id="iv-p1">The <span id="iv-p1.1" class="c24">City</span> of God</p>
      <div2 id="iv.i" title="Translator's Preface">
        <p id="iv.i-p1">Preface <i>italic <span lang="FR" id="iv.i-p1.1">mot</span></i> text.</p>
      </div2>
      <div2 id="iv.ii" title="Book I">
        <div3 id="iv.ii.i" title="Chapter 1 title">
          <p id="iv.ii.i-p1">Text <scripRef id="iv.ii.i-p1.1" passage="Rom. 9:1">Rom. ix. 1</scripRef>
            <note place="end" n="1" id="iv.ii.i-p1.2"><p id="note-p1">note <i>body</i></p></note>.</p>
          <pb n="2" id="iv.ii-Page_2" href="/drop.html" />
          <p id="iv.ii.i-p2"><span lang="EL" id="iv.ii.i-p2.1">logos</span><sup>1</sup><br />after</p>
        </div3>
      </div2>
    </div1>
  </ThML.body>
</ThML>
"""

NPNF2_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<ThML>
  <ThML.head>
    <printSourceInfo>Nicene and Post-Nicene Fathers, Series 2.</printSourceInfo>
  </ThML.head>
  <ThML.body>
    <div1 id="vii" title="The Incarnation of the Word">
      <div2 id="vii.i" title="Introduction.">
        <p id="vii.i-p1">Introductory matter.</p>
      </div2>
      <div2 id="vii.ii" title="On the Incarnation of the Word.">
        <div3 id="vii.ii.i" type="Section" title="Introductory section.">
          <p id="vii.ii.i-p1">Section text <note id="vii.ii.i-p1.1" place="end" n="1"><p id="vii.ii.i-note-p1">note</p></note>.</p>
          <p id="vii.ii.i-p2"><scripRef id="vii.ii.i-p2.1" passage="1 Cor. xv" osisRef="Bible:1Cor.15">1 Cor. xv</scripRef></p>
          <table id="vii.ii.i-table1"><tr><td>Left</td><td><i>Right</i></td></tr></table>
        </div3>
      </div2>
    </div1>
  </ThML.body>
</ThML>
"""

OWEN_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<ThML>
  <ThML.head>
    <printSourceInfo>Works of John Owen, ed. William H. Goold.</printSourceInfo>
  </ThML.head>
  <ThML.body>
    <div1 id="i" type="Work" title="Of the Mortification of Sin in Believers">
      <div2 id="i.i" type="Titlepage" title="Title page."><p id="i.i-p1">Drop me title page.</p></div2>
      <div2 id="i.ii" type="Preface" title="Prefatory note."><p id="i.ii-p1">Keep me as front matter.</p></div2>
      <div2 id="i.iv" type="Chapter" title="Chapter I.">
        <h1>Chapter I.</h1>
        <argument id="i.iv-arg1">The argument <scripRef id="i.iv-arg1.1" passage="Rom. 8:13">Rom. viii. 13</scripRef> survives.</argument>
        <p id="i.iv-p1">Chapter text from <name id="i.iv-p1.1">Owen</name> with <cite id="i.iv-p1.2">Romans</cite>
        and <scripRef id="i.iv-p1.3" passage="Rom. 8:13">Rom. viii. 13</scripRef>.</p>
      </div2>
    </div1>
  </ThML.body>
</ThML>
"""


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "title": "The City of God",
                "author": "Augustine of Hippo",
                "contributors": ["Marcus Dods (translator, 1871)"],
                "source_url": "https://www.ccel.org/ccel/schaff/npnf102.xml",
                "source_hash": "sha256:abc123",
                "source_edition": "Config edition fallback",
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def thml_path(tmp_path: Path) -> Path:
    path = tmp_path / "sample.xml"
    path.write_text(THML_SAMPLE, encoding="utf-8")
    return path


def test_convert_thml_to_tei_maps_city_of_god_features(
    thml_path: Path,
    config_path: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out.xml"

    result = convert_thml_to_tei(thml_path, "iv", config_path, output)

    assert result.unparsed_scriprefs == 0
    tree = etree.parse(str(output))
    assert tree.xpath("count(//tei:front/tei:div[@type='preface'])", namespaces=NS) == 1
    assert tree.xpath("count(//tei:body/tei:div[@type='book'])", namespaces=NS) == 1
    assert tree.xpath("count(//tei:div[@type='chapter'])", namespaces=NS) == 1
    assert tree.xpath("string(//tei:div[@type='chapter']/tei:head)", namespaces=NS) == "Chapter 1 title"

    paragraph_ids = tree.xpath("//tei:p/@xml:id", namespaces=NS)
    assert {"iv-p1", "iv.i-p1", "iv.ii.i-p1", "iv.ii.i-p2", "note-p1"} <= set(paragraph_ids)
    scripture = tree.xpath("//tei:ref[@type='scripture']", namespaces=NS)[0]
    assert scripture.get("cRef") == "Rom.9.1"
    assert "".join(scripture.itertext()).strip() == "Rom. ix. 1"

    note = tree.xpath("//tei:note[@place='end']", namespaces=NS)[0]
    assert note.get("place") == "end"
    assert note.get("n") == "1"
    assert note.get(XML_ID) == "iv.ii.i-p1.2"
    assert tree.xpath("count(//tei:pb)", namespaces=NS) == 2
    assert tree.xpath("//tei:pb[@xml:id='iv.ii-Page_2']/@href", namespaces=NS) == []
    assert tree.xpath("count(//tei:hi[@rend='italic'])", namespaces=NS) == 2
    assert tree.xpath("//tei:foreign/@xml:lang", namespaces=NS) == ["fr", "grc"]
    assert tree.xpath("count(//tei:hi[@rend='superscript'])", namespaces=NS) == 1
    assert tree.xpath("count(//tei:lb)", namespaces=NS) == 1


def test_convert_ccel_work_config_handles_npnf2_and_owen_shapes(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    npnf2_raw = raw_root / "npnf204.xml"
    owen_raw = raw_root / "mort.xml"
    npnf2_raw.write_text(NPNF2_SAMPLE, encoding="utf-8")
    owen_raw.write_text(OWEN_SAMPLE, encoding="utf-8")
    config = tmp_path / "ccel_work_configs.json"
    config.write_text(
        json.dumps(
            {
                "works": [
                    {
                        "work_id": "athanasius-on-the-incarnation",
                        "rendering_id": "ccel-npnf204",
                        "raw_path": "raw/npnf204.xml",
                        "scope": {"tag": "div1", "id": "vii"},
                        "title": "The Incarnation of the Word",
                        "author": "Athanasius of Alexandria",
                        "contributors": ["Archibald Robertson (editor and translator)"],
                        "source_url": "https://www.ccel.org/ccel/schaff/npnf204.xml",
                        "source_hash": "sha256:npnf2",
                        "source_edition": "NPNF2",
                        "division_rules": [
                            {"tag": "div2", "title": "Introduction.", "tei_type": "preface", "place": "front"},
                            {"tag": "div2", "tei_type": "part", "place": "body"},
                            {"tag": "div3", "tei_type": "section", "place": "body"},
                        ],
                    },
                    {
                        "work_id": "owen-mortification",
                        "rendering_id": "ccel-owen-mort",
                        "raw_path": "raw/mort.xml",
                        "scope": {"tag": "div1", "id": "i"},
                        "title": "Of the Mortification of Sin in Believers",
                        "author": "John Owen",
                        "contributors": ["William H. Goold (editor)"],
                        "source_url": "https://www.ccel.org/ccel/owen/mort.xml",
                        "source_hash": "sha256:owen",
                        "source_edition": "Works of John Owen",
                        "division_rules": [
                            {"tag": "div2", "source_type": "Titlepage", "skip": True},
                            {"tag": "div2", "source_type": "Preface", "tei_type": "preface", "place": "front"},
                            {"tag": "div2", "source_type": "Chapter", "tei_type": "chapter", "place": "body"},
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    npnf2_out = tmp_path / "npnf2.tei.xml"
    owen_out = tmp_path / "owen.tei.xml"
    convert_ccel_work_to_tei(config, "athanasius-on-the-incarnation", npnf2_out, repo_root=tmp_path)
    convert_ccel_work_to_tei(config, "owen-mortification", owen_out, repo_root=tmp_path)

    npnf2 = etree.parse(str(npnf2_out))
    assert npnf2.xpath("count(/tei:TEI/tei:text/tei:front/tei:div[@type='preface'])", namespaces=NS) == 1
    assert npnf2.xpath("count(/tei:TEI/tei:text/tei:body/tei:div[@type='part']/tei:div[@type='section'])", namespaces=NS) == 1
    assert npnf2.xpath("string(//tei:table//tei:cell[2])", namespaces=NS).strip() == "Right"
    assert npnf2.xpath("//tei:note/@xml:id", namespaces=NS) == ["vii.ii.i-p1.1"]
    assert npnf2.xpath("//tei:ref[@xml:id='vii.ii.i-p2.1']/@cRef", namespaces=NS) == ["1Cor.15"]

    owen = etree.parse(str(owen_out))
    assert "Drop me title page" not in " ".join(owen.xpath("//tei:text//text()", namespaces=NS))
    assert owen.xpath("count(/tei:TEI/tei:text/tei:front/tei:div[@type='preface'])", namespaces=NS) == 1
    assert owen.xpath("count(/tei:TEI/tei:text/tei:body/tei:div[@type='chapter'])", namespaces=NS) == 1
    assert owen.xpath("string(//tei:argument)", namespaces=NS).strip() == "The argument Rom. viii. 13 survives."
    assert owen.xpath("count(//tei:argument/tei:p)", namespaces=NS) == 1
    assert owen.xpath("//tei:argument/tei:p/tei:ref/@cRef", namespaces=NS) == ["Rom.8.13"]
    assert owen.xpath("//tei:name/@xml:id", namespaces=NS) == ["i.iv-p1.1"]
    assert owen.xpath("//tei:title/@xml:id", namespaces=NS) == ["i.iv-p1.2"]


def test_unknown_inline_element_raises(thml_path: Path, config_path: Path, tmp_path: Path) -> None:
    broken = thml_path.read_text(encoding="utf-8").replace(
        "<p id=\"iv.ii.i-p2\">",
        "<p id=\"iv.ii.i-p2\"><unknown id=\"bad\">x</unknown>",
    )
    thml_path.write_text(broken, encoding="utf-8")

    with pytest.raises(ConversionError, match="unknown"):
        convert_thml_to_tei(thml_path, "iv", config_path, tmp_path / "out.xml")


@pytest.mark.slow
def test_committed_city_of_god_tei_validates_against_vendored_tei_schema() -> None:
    tei_path = Path("ir/augustine/city-of-god.ccel-npnf102.tei.xml")
    if not tei_path.exists():
        pytest.skip("Committed City of God TEI IR is absent; run the ThML converter first.")

    assert validate_file(tei_path) == []
