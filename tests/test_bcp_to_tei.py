from __future__ import annotations

from pathlib import Path

from lxml import etree

from build.tei.bcp_source import BcpEvent, feature_payload
from build.tei.bcp_to_tei import convert_bcp_to_tei
from build.tei.census import CENSUS_SCHEMA_ID, census_bcp_liturgy
from build.tei.validate import validate_file
from build.tei.writer import TEI_NS

NS = {"tei": TEI_NS}

BCP_1549_SAMPLE = """<html>
<head><title>The 1549 Book of Common Prayer: Morning Prayer</title></head>
<body>
<table width="600"><tr>
<td width="450">
  <p align="center"><font size="+2">AN ORDRE FOR MATTYNS</font></p>
  <p align="justify"><i>Then lykewyse he shall saye,</i></p>
  <p>Priest. O Lorde, open thou my lippes.</p>
  <p align="center">Psal. xcv.</p>
  <p><span class="dropcap2georgia">O</span> COME lette us syng unto the Lorde.</p>
</td>
<td width="150">Editorial side note to exclude.</td>
</tr></table>
</body></html>
"""


def _write_1549_fixture(raw_root: Path) -> None:
    source_dir = raw_root / "bcp-full-text" / "bcp-1549"
    source_dir.mkdir(parents=True)
    (source_dir / "Matins_1549.htm").write_text(BCP_1549_SAMPLE, encoding="utf-8")


def test_bcp_census_records_liturgical_id_sets(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    _write_1549_fixture(raw_root)

    census = census_bcp_liturgy("bcp-1549", raw_root)

    assert census["census_schema"] == CENSUS_SCHEMA_ID
    assert census["source"]["edition"] == "bcp-1549"
    assert census["features"]["services"]["count"] == 1
    assert census["features"]["labels"]["count"] == 2
    assert census["features"]["rubrics"]["count"] == 1
    assert census["features"]["speaker_units"]["count"] == 1
    assert census["features"]["services"]["ids"] == ["bcp-bcp-1549-matins-1549"]


def test_convert_bcp_to_tei_preserves_liturgy_structure(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    _write_1549_fixture(raw_root)
    output = tmp_path / "book-of-common-prayer.bcp-1549.tei.xml"

    convert_bcp_to_tei("bcp-1549", output, raw_root=raw_root)

    tree = etree.parse(str(output))
    assert tree.xpath("count(/tei:TEI/tei:text/tei:body/tei:div[@type='service'])", namespaces=NS) == 1
    assert tree.xpath("string(//tei:div[@type='service']/tei:head)", namespaces=NS) == "Morning Prayer"
    assert tree.xpath("count(//tei:label)", namespaces=NS) == 2
    assert tree.xpath("//tei:p[@rend='rubric']/text()", namespaces=NS) == ["Then lykewyse he shall saye,"]
    assert tree.xpath("string(//tei:sp/tei:speaker)", namespaces=NS) == "Priest"
    assert tree.xpath("string(//tei:sp/tei:p)", namespaces=NS) == "O Lorde, open thou my lippes."
    assert "Editorial side note" not in " ".join(tree.xpath("//tei:text//text()", namespaces=NS))
    assert validate_file(output) == []


def test_bcp_census_labels_include_collect_label_ids() -> None:
    events = (
        BcpEvent(
            "collects",
            "bcp-1662-easter-day-collect",
            "Almighty God...",
            "raw/bcp1662/collects.html",
            label="Easter Day.",
            div_type="collect",
        ),
    )

    assert feature_payload(events, "labels") == {
        "count": 1,
        "ids": ["bcp-1662-easter-day-collect-label"],
    }
