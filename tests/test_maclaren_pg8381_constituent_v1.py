"""Focused source structure and mutation checks for the PG #8381 pilot."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from lxml import etree
import pytest

from build.tei.maclaren_pg8381_constituent_oracle_v1 import _source, check_tree
from build.tei.maclaren_pg8381_constituent_v1 import render

ROOT = Path(__file__).resolve().parents[1]
NS = {"t": "http://www.tei-c.org/ns/1.0"}


@pytest.fixture(scope="module")
def source_and_tree() -> tuple[list[str], etree._ElementTree]:
    content = render(ROOT)
    candidate = (
        ROOT / "sources/sermons/maclaren-expositions/pg8381-constituent-v1/content.tei.xml"
    ).read_bytes()
    assert content == candidate
    return _source(ROOT), etree.ElementTree(etree.fromstring(content))


def test_full_source_and_exposition_structure(source_and_tree: tuple[list[str], etree._ElementTree]) -> None:
    lines, tree = source_and_tree
    report = check_tree(tree, lines)
    assert (report["source_lines"], report["expositions"], report["back_lines"]) == (12244, 45, 364)


def test_changed_indented_exposition_heading_rejected(source_and_tree: tuple[list[str], etree._ElementTree]) -> None:
    lines, original = source_and_tree
    tree = deepcopy(original)
    heading = tree.xpath("./t:text/t:body/t:div[@n='38']/t:head/t:seg", namespaces=NS)[0]
    assert heading.text == " THOMAS AND JESUS"
    heading.text = "THOMAS AND JESUS"
    with pytest.raises(ValueError, match="heading differs from source"):
        check_tree(tree, lines)


def test_wrong_exposition_attachment_rejected(source_and_tree: tuple[list[str], etree._ElementTree]) -> None:
    lines, original = source_and_tree
    tree = deepcopy(original)
    divisions = tree.xpath("./t:text/t:body/t:div", namespaces=NS)
    moved = divisions[1][1]
    divisions[0].append(moved)
    with pytest.raises(ValueError, match="source paragraph or carrier ownership changed|omits, duplicates, or reorders"):
        check_tree(tree, lines)


def test_license_line_loss_rejected(source_and_tree: tuple[list[str], etree._ElementTree]) -> None:
    lines, original = source_and_tree
    tree = deepcopy(original)
    license_line = tree.xpath("./t:text/t:back/t:div//t:seg[@n='11922']", namespaces=NS)[0]
    license_line.getparent().remove(license_line)
    with pytest.raises(ValueError, match="unaccounted paragraph text|omits, duplicates, or reorders"):
        check_tree(tree, lines)


def test_invented_unaccounted_paragraph_rejected(
    source_and_tree: tuple[list[str], etree._ElementTree],
) -> None:
    lines, original = source_and_tree
    tree = deepcopy(original)
    exposition = tree.xpath("./t:text/t:body/t:div[@n='1']", namespaces=NS)[0]
    invented = etree.Element("{http://www.tei-c.org/ns/1.0}p")
    invented.text = "INVENTED TEXT NOT IN THE SOURCE"
    exposition.insert(2, invented)
    with pytest.raises(ValueError, match="unaccounted paragraph text"):
        check_tree(tree, lines)


def test_invented_carrier_tail_rejected(
    source_and_tree: tuple[list[str], etree._ElementTree],
) -> None:
    lines, original = source_and_tree
    tree = deepcopy(original)
    carrier = tree.xpath("./t:text/t:body/t:div[@n='1']//t:seg[@n='158']", namespaces=NS)[0]
    carrier.tail = "INVENTED TAIL"
    with pytest.raises(ValueError, match="unaccounted candidate tail"):
        check_tree(tree, lines)


def test_source_line_paragraph_split_without_blank_rejected(
    source_and_tree: tuple[list[str], etree._ElementTree],
) -> None:
    lines, original = source_and_tree
    tree = deepcopy(original)
    exposition = tree.xpath("./t:text/t:body/t:div[@n='1']", namespaces=NS)[0]
    paragraph = exposition.xpath("./t:p", namespaces=NS)[0]
    trailing_break = paragraph[-2]
    trailing_line = paragraph[-1]
    paragraph.remove(trailing_break)
    paragraph.remove(trailing_line)
    invented_split = etree.Element("{http://www.tei-c.org/ns/1.0}p")
    invented_split.append(trailing_line)
    exposition.insert(exposition.index(paragraph) + 1, invented_split)
    with pytest.raises(ValueError, match="source paragraph or carrier ownership changed"):
        check_tree(tree, lines)


def test_source_carrier_semantic_attribute_rejected(
    source_and_tree: tuple[list[str], etree._ElementTree],
) -> None:
    lines, original = source_and_tree
    tree = deepcopy(original)
    carrier = tree.xpath("./t:text/t:body/t:div[@n='1']//t:seg[@n='158']", namespaces=NS)[0]
    carrier.set("ana", "#invented-reading")
    with pytest.raises(ValueError, match="unaccounted candidate attribute"):
        check_tree(tree, lines)
