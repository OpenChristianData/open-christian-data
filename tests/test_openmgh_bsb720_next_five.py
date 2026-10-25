"""Focused source-order and pagination checks for bsb720 Lambert poems 17-23."""

from __future__ import annotations

from lxml import etree
import pytest

from build.tei.openmgh_bsb720_next_five_oracle import check_candidate
from build.tools import prepare_openmgh_bsb720_next_five as source


def _example(work_id: str, number: int) -> tuple[bytes, bytes, dict, dict]:
    retained, tree = source._source(source.ROOT)
    work, acquisition, _work_path, _acquisition_path = source._work(source.ROOT, work_id)
    return retained, source._candidate(tree, work, number), work, acquisition


@pytest.mark.parametrize(("work_id", "number", "span"), [
    ("lambertus-epitaphium-reginardi", 17, (80, 88)),
    ("lambertus-epitaphium-engelberti", 19, (111, 117)),
    ("lambertus-epitaphium-gozelonis", 20, (118, 122)),
    ("lambertus-epitaphium-adelindis", 22, (131, 139)),
    ("adelmannus-ad-eundem-adhuc-puerum", 23, (140, 143)),
])
def test_each_complete_source_order_span(
    work_id: str, number: int, span: tuple[int, int]
) -> None:
    retained, candidate, work, acquisition = _example(work_id, number)
    checked = check_candidate(retained, candidate, work, acquisition, number=number)
    assert (checked["source_child_start"], checked["source_child_end"]) == span
    assert checked["boundary_page_break"] == (
        "bsb00000720_00274" if number == 23 else None
    )


def test_oracle_rejects_dropped_epitaph_line() -> None:
    retained, candidate, work, acquisition = _example("lambertus-epitaphium-adelindis", 22)
    tree = etree.fromstring(candidate)
    block = tree.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='ab']")[0]
    block.remove(block[-1])
    with pytest.raises(ValueError, match="candidate source block differs"):
        check_candidate(retained, etree.tostring(tree), work, acquisition, number=22)


def test_oracle_rejects_changed_section_boundary_page() -> None:
    retained, candidate, work, acquisition = _example(
        "adelmannus-ad-eundem-adhuc-puerum", 23
    )
    old = b'xml:id="bsb00000720_00274"'
    new = b'xml:id="bsb00000720_00274_changed"'
    mutated = retained.replace(old, new, 1)
    assert mutated != retained
    with pytest.raises(ValueError, match="pagination"):
        check_candidate(mutated, candidate, work, acquisition, number=23)
