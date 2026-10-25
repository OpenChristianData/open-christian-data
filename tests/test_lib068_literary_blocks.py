"""Focused source and schema checks for the isolated LIB-068 block producer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

from lxml import etree
import pytest


ROOT = Path(__file__).resolve().parents[1]
NS = {"t": "http://www.tei-c.org/ns/1.0"}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def modules():
    return (
        _load(ROOT / "build/tei/lib068_source_local.py", "_lib068_special_test_producer"),
        _load(ROOT / "build/tei/lib068_literary_blocks.py", "_lib068_special_test_blocks"),
    )


@pytest.fixture(params=["newman-apologia-pro-vita-sua", "donne-devotions-upon-emergent-occasions"])
def built(request, modules):
    producer, blocks = modules
    work_id = request.param
    spec = producer._SPECS[work_id]
    profile = json.loads(
        (ROOT / "sources/structured-text" / work_id / "LIB-068.reconstruction-profile.json").read_bytes()
    )
    lines = producer._source_lines((ROOT / spec.path).read_bytes(), spec)
    root = etree.fromstring(producer._tei(work_id, spec, profile, lines))
    scope = root.xpath(
        './t:text/t:body/t:div[@type="retained-source"]', namespaces=NS
    )[0]
    assert scope.xpath('.//t:quote[@type="source-verse"]', namespaces=NS)
    return root, scope, blocks, work_id, lines, profile


def test_inventory_receipt_is_pinned_to_retained_source(built):
    _, _, blocks, work_id, lines, profile = built
    summary = blocks.inventory_summary(work_id, lines, profile)
    assert summary["source_sha256"] == blocks.SOURCE_PINS[work_id]["source_sha256"]
    if work_id == blocks.NEWMAN:
        assert summary["special_blocks"]["calendar"] == {
            "months": 12,
            "day_rows": 366,
            "empty_day_rows": 140,
        }
        assert summary["special_blocks"]["chronology"]["dated_entries"] == 300
    else:
        assert summary["special_blocks"]["components"]["items"] == 3
        assert summary["special_blocks"]["station_contents"]["items"] == 23


def test_newman_tables_have_actual_source_columns_and_no_fake_cells(built):
    root, scope, blocks, work_id, lines, _ = built
    if work_id != blocks.NEWMAN:
        pytest.skip("Newman-only table assertions")
    xsd = etree.XMLSchema(etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")))
    assert xsd.validate(root), str(xsd.error_log)
    for table in scope.xpath('.//t:table[@type="calendar"]', namespaces=NS):
        for row in table.findall("t:row", NS):
            cells = row.findall("t:cell", NS)
            assert all(cell.get("role") in {"day", "observance"} for cell in cells)
            assert not any(cell.get("role") == "source-line" for cell in cells)
            assert all(cell.xpath('.//t:seg[@type="source-line-fragment"]', namespaces=NS) for cell in cells)
    table = scope.xpath('.//t:table[@type="supplement-date-page"]', namespaces=NS)[0]
    for row in table.findall("t:row", NS):
        assert [cell.get("role") for cell in row.findall("t:cell", NS)] == ["date", "page"]
        number = int(row.get("n"))
        assert "".join(row.xpath('./t:cell[@role="date"]//t:seg', namespaces=NS)[0].itertext()) == lines[number - 1][:27]
        assert "".join(row.xpath('./t:cell[@role="page"]//t:seg', namespaces=NS)[0].itertext()) == lines[number - 1][27:]


def test_apply_rejects_already_enriched_tree(built):
    _, scope, blocks, work_id, lines, profile = built
    with pytest.raises(ValueError, match="already present"):
        blocks.apply_blocks(scope, work_id, lines, profile)
