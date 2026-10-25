"""Focused source-boundary checks for Lambert poems 5-15."""

from __future__ import annotations

from hashlib import sha256
import json

from lxml import etree
import pytest

from build.tei.openmgh_bsb720_next_eleven_oracle import check_candidate
from build.tools import prepare_openmgh_bsb720_next_eleven as source


def _example(work_id: str, number: int) -> tuple[bytes, bytes, dict, dict]:
    retained, tree = source._source(source.ROOT)
    work, acquisition, _work_path, _acquisition_path = source._work(source.ROOT, work_id)
    return retained, source._candidate(tree, work, number), work, acquisition


def test_reversed_catalog_endpoints_are_resolved_in_source_order() -> None:
    retained, candidate, work, acquisition = _example("lambertus-in-alia", 5)
    result = check_candidate(retained, candidate, work, acquisition, number=5)
    assert (result["source_child_start"], result["source_child_end"]) == (25, 28)
    assert result["source_heading_id"] == "bsb00000720_00268_8"
    assert result["source_last_line_id"] == "bsb00000720_00268_11"


def test_all_remaining_source_spans_are_ordered_and_bound_to_retained_ids() -> None:
    inventory = json.loads((source.ROOT / "plans/2026-09-22-source-preflight/"
                            "openmgh-bsb720-remaining-25-source-order-20260927.json").read_bytes())
    retained, tree = source._source(source.ROOT)
    assert inventory["source_sha256"] == sha256(retained).hexdigest()
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    children = list(tree.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']"
                               "/t:div[@n='Carmina']/t:ab", namespaces=ns)[0])
    assert len(children) == 959
    rows = inventory["works"]
    assert len(rows) == 25
    assert sum(row["status"] == "next-eleven-staged-for-review" for row in rows) == 11
    assert sum(row["status"] == "hold-no-stage" for row in rows) == 14
    previous_end = 24
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    for row in rows:
        start, end = row["source_child_start"], row["source_child_end"]
        assert previous_end < start <= end
        assert children[start].get(xml_id) == row["source_start_id"]
        assert children[end].get(xml_id) == row["source_end_id"]
        previous_end = end


def test_oracle_rejects_dropped_line() -> None:
    retained, candidate, work, acquisition = _example("lambertus-in-alia", 5)
    tree = etree.fromstring(candidate)
    block = tree.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='ab']")[0]
    block.remove(block[-1])
    with pytest.raises(ValueError, match="candidate source block differs"):
        check_candidate(retained, etree.tostring(tree), work, acquisition, number=5)


@pytest.mark.parametrize(
    ("work_id", "number", "marker"),
    [("lambertus-circa-agnum-in-paradyso", 6, "bsb00000720_00269"),
     ("lambertus-in-texto", 10, "bsb00000720_00270")],
)
def test_oracle_rejects_mutated_source_owned_boundary_page(
    work_id: str, number: int, marker: str
) -> None:
    retained, candidate, work, acquisition = _example(work_id, number)
    old = f'xml:id="{marker}"'.encode()
    new = f'xml:id="{marker}_changed"'.encode()
    mutated = retained.replace(old, new, 1)
    assert mutated != retained
    with pytest.raises(ValueError, match="pagination"):
        check_candidate(mutated, candidate, work, acquisition, number=number)
