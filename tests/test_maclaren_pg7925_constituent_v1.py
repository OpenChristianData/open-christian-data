"""Focused source-fidelity and oracle-sensitivity checks for PG #7925."""

from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree
import pytest

from build.tei import maclaren_pg7925_constituent_oracle_v1 as oracle
from build.tei import maclaren_pg7925_constituent_v1 as producer
from build.lib.tei_xsd import compiled_tei_schema

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "sources/sermons/maclaren-expositions/pg7925-psalms-constituent-v1/content.tei.xml"
NS = {"t": oracle.TEI}


@pytest.fixture(scope="module")
def bound() -> tuple[list[str], bytes]:
    lines = oracle.retained_lines(ROOT)
    existing = CANDIDATE.read_bytes()
    assert existing == producer.render(ROOT)
    return lines, existing


def _tree(data: bytes) -> etree._ElementTree:
    return etree.ElementTree(etree.fromstring(data))


def test_full_source_and_printed_structure(bound: tuple[list[str], bytes]) -> None:
    lines, content = bound
    result = oracle.check_tree(_tree(content), lines)
    assert result["expositions"] == [38, 43]
    assert result["toc_entries"] == [38, 43]
    assert result["last_first_volume_exposition_heading_line"] == 10703
    schema = compiled_tei_schema(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")
    assert schema.validate(_tree(content)), schema.error_log


@pytest.mark.parametrize("damage", ["omit", "move", "head", "invent", "volume", "semantic"])
def test_independent_checker_rejects_fidelity_mutations(
    bound: tuple[list[str], bytes], damage: str
) -> None:
    lines, content = bound
    tree = _tree(content)
    if damage == "omit":
        target, = tree.xpath("//*[@xml:id='pg7925-line-10706']", namespaces=NS)
        target.getparent().remove(target)
    elif damage == "move":
        source, = tree.xpath("//*[@xml:id='pg7925-v1-exposition-38']", namespaces=NS)
        target, = tree.xpath("//*[@xml:id='pg7925-v1-exposition-37']", namespaces=NS)
        target.append(copy.deepcopy(source[-1]))
    elif damage == "head":
        target, = tree.xpath("//*[@xml:id='pg7925-line-10703']", namespaces=NS)
        target.text = "TWO SHEPHERDS"
    elif damage == "invent":
        target, = tree.xpath("//*[@xml:id='pg7925-v1-exposition-38']", namespaces=NS)
        etree.SubElement(target, f"{{{oracle.TEI}}}p").text = "Invented sentence."
    elif damage == "volume":
        target, = tree.xpath("//*[@xml:id='pg7925-volume-2']", namespaces=NS)
        target.set("n", "1")
    else:
        target, = tree.xpath("//*[@xml:id='pg7925-v1-exposition-38']", namespaces=NS)
        target.set("rend", "fictional")
    with pytest.raises(ValueError):
        oracle.check_tree(tree, lines)
