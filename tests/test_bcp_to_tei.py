from __future__ import annotations

import json
import struct
from pathlib import Path

from lxml import etree
import pytest

from build.tei.bcp_source import BcpEvent, feature_payload
from build.tei.bcp_to_tei import convert_bcp_to_tei
from build.tei.census import CENSUS_SCHEMA_ID, census_bcp_liturgy
from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.writer import TEI_NS

NS = {"tei": TEI_NS}

BCP_RENDERINGS = (
    (
        "bcp-1549",
        "The Book of Common Prayer (1549)",
        "Church of England",
        "http://justus.anglican.org/resources/bcp/1549/",
        34,
    ),
    (
        "bcp-1559",
        "The Book of Common Prayer (1559)",
        "Church of England",
        "http://justus.anglican.org/resources/bcp/1559/",
        16,
    ),
    (
        "bcp-1662",
        "The Book of Common Prayer (1662)",
        "Church of England",
        "https://www.eskimo.com/~lhowell/bcp1662/",
        105,
    ),
    (
        "bcp-1928-collects",
        "The Book of Common Prayer (1928) Collects",
        "Protestant Episcopal Church in the United States of America",
        "https://www.episcopalnet.org/1928bcp/propers/",
        102,
    ),
)

BCP_1559_LEGACY_TO_TEI = (
    ("Baptism", "bcp-bcp-1559-baptism-1559"),
    ("Burial", "bcp-bcp-1559-burial-1559"),
    ("Churching of Women & Commination", "bcp-bcp-1559-churching-of-women-1559"),
    ("Holy Communion", "bcp-bcp-1559-communion-1559"),
    ("Catechism & Confirmation", "bcp-bcp-1559-confirmation-1559"),
    ("Evening Prayer", "bcp-bcp-1559-ep-1559"),
    ("Godly Prayers", "bcp-bcp-1559-godly-prayers"),
    ("James I's Proclamation of Uniformity", "bcp-bcp-1559-james-i-procl-uniformity"),
    ("Kalendar & Tables", "bcp-bcp-1559-kalendar-1559"),
    ("Litany", "bcp-bcp-1559-litany-1559"),
    ("Morning Prayer", "bcp-bcp-1559-mp-1559"),
    ("Marriage", "bcp-bcp-1559-marriage-1559"),
    ("Churching of Women & Commination", None),
    ("Visitation of the Sick", "bcp-bcp-1559-visitation-sick-1559"),
)

BCP_1559_TEI_ONLY_SERVICE_IDS = {
    "bcp-bcp-1559-bcp-1559",
    "bcp-bcp-1559-commination-1559",
    "bcp-bcp-1559-front-matter-1559",
}

BCP_1559_EMPTY_SERVICE_HEADS = {
    "The 1559 Book of Common Prayer",
    "A Commination against Sinners, from the 1559 Book of Common Prayer",
    "Act of Uniformity; Preface; and Of Ceremonies",
    "Kalendar & Tables",
}

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
    assert tree.xpath("string(.//tei:titleStmt/tei:author)", namespaces=NS) == "Church of England"
    assert not tree.xpath(".//tei:titleStmt/tei:respStmt", namespaces=NS)
    assert (
        tree.xpath("string(.//tei:sourceDesc//tei:ptr/@target)", namespaces=NS)
        == "http://justus.anglican.org/resources/bcp/1549/"
    )
    assert (
        tree.xpath("string(.//tei:sourceDesc//tei:note[@type='edition'])", namespaces=NS)
        == "bcp-1549"
    )
    assert validate_file(output) == []


@pytest.mark.parametrize(
    ("rendering_id", "title", "author", "source_url", "expected_rows"),
    BCP_RENDERINGS,
)
def test_bcp_rendering_metadata_has_no_unsupported_translator(
    rendering_id: str,
    title: str,
    author: str,
    source_url: str,
    expected_rows: int,
) -> None:
    tei_path = Path("ir/bcp") / f"book-of-common-prayer.{rendering_id}.tei.xml"
    projection_path = Path("ir/bcp/hf") / f"book-of-common-prayer.{rendering_id}.jsonl"
    tree = etree.parse(str(tei_path))
    rows = [
        json.loads(line)
        for line in projection_path.read_text(encoding="utf-8").splitlines()
        if line
    ]

    assert tree.xpath("string(.//tei:titleStmt/tei:title)", namespaces=NS) == title
    assert tree.xpath("string(.//tei:titleStmt/tei:author)", namespaces=NS) == author
    assert tree.xpath("string(.//tei:sourceDesc//tei:ptr/@target)", namespaces=NS) == source_url
    assert (
        tree.xpath("string(.//tei:sourceDesc//tei:note[@type='edition'])", namespaces=NS)
        == rendering_id
    )
    responsibilities = [
        " ".join(node.itertext()).strip().lower()
        for node in tree.xpath(".//tei:titleStmt/tei:respStmt/tei:resp", namespaces=NS)
    ]
    assert not any("translator" in responsibility for responsibility in responsibilities)
    assert len(rows) == expected_rows
    assert all(
        row["source"]
        == {
            "author": author,
            "translator": "",
            "source_url": source_url,
            "license": "CC0",
        }
        for row in rows
    )


def test_bcp_1662_collects_are_body_peers_with_correct_title_paths() -> None:
    tei_path = Path("ir/bcp/book-of-common-prayer.bcp-1662.tei.xml")
    census_path = Path("ir/census/book-of-common-prayer.bcp-1662.census.json")
    projection_path = Path("ir/bcp/hf/book-of-common-prayer.bcp-1662.jsonl")
    tree = etree.parse(str(tei_path))
    collects = tree.xpath(
        "/tei:TEI/tei:text/tei:body/tei:div[@type='collect']",
        namespaces=NS,
    )

    assert len(tree.xpath("//tei:div[@type='service']", namespaces=NS)) == 20
    assert len(collects) == 85
    assert not tree.xpath("//tei:div[@type='service']//tei:div[@type='collect']", namespaces=NS)

    rows = [
        json.loads(line)
        for line in projection_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    rows_by_id = {row["id"].rsplit("/", 1)[-1]: row for row in rows}
    collect_ids = [collect.get("{http://www.w3.org/XML/1998/namespace}id") for collect in collects]
    census = json.loads(census_path.read_text(encoding="utf-8"))
    source_order_ids = census["features"]["collects"]["ids"]
    collect_rows = [rows_by_id[collect_id] for collect_id in collect_ids]

    assert len(collect_rows) == 85
    assert collect_ids == source_order_ids
    assert [row["id"].rsplit("/", 1)[-1] for row in collect_rows] == collect_ids
    assert all(row["title_path"] == ["The Book of Common Prayer (1662)"] for row in collect_rows)
    assert all("Consecration of Bishops" not in row["title_path"] for row in collect_rows)


def test_bcp_1559_legacy_sections_reconcile_to_current_service_grain() -> None:
    legacy = json.loads(Path("data/structured-text/bcp-1559.json").read_text(encoding="utf-8"))
    tree = etree.parse("ir/bcp/book-of-common-prayer.bcp-1559.tei.xml")
    rows = [
        json.loads(line)
        for line in Path("ir/bcp/hf/book-of-common-prayer.bcp-1559.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]

    legacy_sections = legacy["data"]["sections"]
    services = tree.xpath("/tei:TEI/tei:text/tei:body/tei:div[@type='service']", namespaces=NS)
    service_ids = {
        service.get("{http://www.w3.org/XML/1998/namespace}id") for service in services
    }
    projected_ids = {row["id"].rsplit("/", 1)[-1] for row in rows}

    assert len(legacy_sections) == len(BCP_1559_LEGACY_TO_TEI) == 14
    assert len(services) == len(rows) == 16
    assert projected_ids == service_ids
    assert [section["title"] for section in legacy_sections] == [
        title for title, _service_id in BCP_1559_LEGACY_TO_TEI
    ]

    mapped_ids = {
        service_id for _title, service_id in BCP_1559_LEGACY_TO_TEI if service_id is not None
    }
    assert service_ids - mapped_ids == BCP_1559_TEI_ONLY_SERVICE_IDS
    assert len(mapped_ids) == 13

    # The one legacy-only row is not a 1559 service: PDF1623.htm is a source-site
    # download notice whose page title incorrectly repeats the preceding Churching title.
    legacy_only = legacy_sections[12]
    legacy_only_text = " ".join(legacy_only["content_blocks"])
    assert legacy_only["word_count"] == 173
    assert "printing of the Book of Common Prayer from 1623" in legacy_only_text
    assert "Download or read the 1623 BCP (27MB)" in legacy_only_text
    assert all("printing of the Book of Common Prayer from 1623" not in row["text"] for row in rows)

    empty_services = {
        service.findtext(f"{{{TEI_NS}}}head")
        for service in services
        if not service.xpath("./*[not(self::tei:head)]", namespaces=NS)
    }
    assert empty_services == BCP_1559_EMPTY_SERVICE_HEADS
    assert {row["title_path"][-1] for row in rows if not row["text"]} == empty_services


@pytest.mark.parametrize(
    ("rendering_id", "distinctive_text"),
    (
        ("bcp-1559", "Ye that mynde to come to the holye Communion"),
        (
            "bcp-1928-collects",
            "Grant us by the same Spirit to have a right judgment in all things",
        ),
    ),
)
def test_bcp_viewer_smoke_artifacts_cover_distinctive_body_text(
    rendering_id: str,
    distinctive_text: str,
) -> None:
    tei_path = Path("ir/bcp") / f"book-of-common-prayer.{rendering_id}.tei.xml"
    screenshot_path = Path("ir/bcp") / f"book-of-common-prayer.{rendering_id}.viewer.png"

    assert distinctive_text in tei_path.read_text(encoding="utf-8")
    png = screenshot_path.read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (1280, 1800)


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
