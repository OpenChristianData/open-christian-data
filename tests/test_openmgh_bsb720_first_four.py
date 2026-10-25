"""Focused source and transaction guards for the first four bsb720 poems."""

from __future__ import annotations

from pathlib import Path

from lxml import etree
import pytest

from build.tei.openmgh_bsb720_first_four_oracle import check_candidate
from build.tools import prepare_openmgh_bsb720_first_four as source
from ocd_kernel.tei.install_accepted import _commit_generation, _files


def _first_candidate() -> tuple[bytes, bytes, dict, dict]:
    source_bytes, tree = source._source(source.ROOT)
    work, acquisition, _work_path, _acquisition_path = source._work(
        source.ROOT, "lambertus-circa-reliquias"
    )
    return source_bytes, source._candidate(tree, work, 1), work, acquisition


def test_source_oracle_rejects_dropped_line_and_changed_heading() -> None:
    retained, candidate, work, acquisition = _first_candidate()
    assert check_candidate(retained, candidate, work, acquisition, number=1)["line_count"] == 4
    root = etree.fromstring(candidate)
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    block = root.xpath("/t:TEI/t:text/t:body/t:div/t:ab", namespaces=ns)[0]
    block.remove(block[-1])
    with pytest.raises(ValueError, match="line count|flat source block"):
        check_candidate(retained, etree.tostring(root), work, acquisition, number=1)
    root = etree.fromstring(candidate)
    block = root.xpath("/t:TEI/t:text/t:body/t:div/t:ab", namespaces=ns)[0]
    block[0].tail = "〈1.〉 WRONG HEADING"
    with pytest.raises(ValueError, match="source line changed"):
        check_candidate(retained, etree.tostring(root), work, acquisition, number=1)


def test_source_oracle_rejects_changed_shared_page_marker() -> None:
    retained, _candidate, _work, _acquisition = _first_candidate()
    work, acquisition, _work_path, _acquisition_path = source._work(
        source.ROOT, "lambertus-ad-altare-sancti-benedicti"
    )
    tree = etree.fromstring(retained)
    candidate = source._candidate(tree, work, 2)
    mutated = retained.replace(
        b'xml:id="bsb00000720_00268"',
        b'xml:id="bsb00000720_00268_changed"',
        1,
    )
    assert mutated != retained
    with pytest.raises(ValueError, match="page marker"):
        check_candidate(mutated, candidate, work, acquisition, number=2)


def test_stock_transaction_rolls_back_after_new_work_is_live(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    target = root / "library/works/lambertus-circa-reliquias"
    staged = tmp_path / "stage/library/works/lambertus-circa-reliquias"
    target.mkdir(parents=True)
    staged.mkdir(parents=True)
    (target / "old.txt").write_text("before", encoding="utf-8")
    (staged / "new.txt").write_text("after", encoding="utf-8")
    before, after = _files(target), _files(staged)

    def fail_after_live(checkpoint: str) -> None:
        if checkpoint == "after-new-live":
            raise RuntimeError("injected after new work live")

    with pytest.raises(RuntimeError, match="injected"):
        _commit_generation(
            root, target, staged, work_id="lambertus-circa-reliquias",
            before=before, after=after, existed=True, replacement=False,
            operation_kind="openmgh-bsb720-fixture", result_status="fixture",
            accepted_editions=1, fail_at=fail_after_live,
        )
    assert _files(target) == before
    journals = list((root / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert '"phase": "rolled-back"' in journals[0].read_text(encoding="utf-8")
