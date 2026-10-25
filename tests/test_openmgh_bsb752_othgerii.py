"""Focused bsb752 Othgerii prose part, guard, and notice binding."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lxml import etree
import pytest

from build.tei.openmgh_bsb752_othgerii_oracle import check_candidate
from build.tools import install_openmgh_bsb752_othgerii as installer
from build.tools import prepare_openmgh_bsb752_othgerii as source
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _io_path
from tests.openmgh_historical_fixture import historical_receipt_context


ROOT = Path(__file__).resolve().parents[1]
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb752-othgerii-public-notices-20260928-v2")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb752-othgerii-stage-20260928-v2")


def test_complete_othgerii_part_and_read_only_preflight(historical_context: tuple[Path, Path, str], monkeypatch: pytest.MonkeyPatch) -> None:
    work_id, number = source.WORKS[0]
    retained, tree = source._source(source.ROOT)
    work, acquisition, _work_path, _acquisition_path = source._work(source.ROOT, work_id)
    candidate = source._candidate(tree, work, number)
    checked = check_candidate(retained, candidate, work, acquisition, number=number)
    assert (checked["source_child_start"], checked["source_child_end"]) == (0, 181)
    assert checked["internal_page_break"] == ["bsb00000752_00212", "bsb00000752_00213", "bsb00000752_00214"]
    assert checked["line_count"] == 115
    assert checked["source_word_count"] == 56
    assert checked["source_highlight_count"] == 8
    assert checked["source_column_break_count"] == 0
    assert checked["source_anchor_count"] == 0
    root, receipt, digest = historical_context
    monkeypatch.setattr(installer, "ROOT", root)
    assert installer.preflight(receipt, expected_receipt_sha256=digest)["installation"] == "not-performed"


@pytest.fixture(scope="module")
def historical_context(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    assert len(installer.PINS) == 1
    receipt, digest = installer._receipt(next(iter(installer.PINS)))
    return historical_receipt_context(
        ROOT, tmp_path_factory.mktemp("mgh-historical"), receipt, digest,
        ((source.SOURCE, source.SOURCE_SHA256), (source.PACKAGE, source.PACKAGE_SHA256),
         (source.RECEIPT, source.RECEIPT_SHA256)),
    )


@pytest.mark.parametrize("work_id,number", source.WORKS)
def test_oracle_rejects_changed_marker_or_missing_line(work_id: str, number: int) -> None:
    retained, tree = source._source(source.ROOT)
    work, acquisition, _work_path, _acquisition_path = source._work(source.ROOT, work_id)
    candidate = source._candidate(tree, work, number)
    parsed = etree.fromstring(candidate)
    block = parsed.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='div']/*[local-name()='ab']")[0]
    block[0].set("{http://www.w3.org/XML/1998/namespace}id", "changed")
    with pytest.raises(ValueError, match="candidate native Othgerii part changed"):
        check_candidate(retained, etree.tostring(parsed), work, acquisition, number=number)
    parsed = etree.fromstring(candidate)
    block = parsed.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='div']/*[local-name()='ab']")[0]
    block.remove(block[-1])
    with pytest.raises(ValueError, match="candidate native Othgerii part changed"):
        check_candidate(retained, etree.tostring(parsed), work, acquisition, number=number)


@pytest.mark.parametrize("work_id,number", source.WORKS)
def test_oracle_rejects_changed_word_edge(work_id: str, number: int) -> None:
    retained, tree = source._source(source.ROOT)
    work, acquisition, _work_path, _acquisition_path = source._work(source.ROOT, work_id)
    parsed = etree.fromstring(source._candidate(tree, work, number))
    words = parsed.xpath("//*[local-name()='w']")
    words[0].set("corresp", "#missing")
    with pytest.raises(ValueError, match="candidate native Othgerii part changed"):
        check_candidate(retained, etree.tostring(parsed), work, acquisition, number=number)


@pytest.mark.parametrize("work_id", [work_id for work_id, _ in source.WORKS])
def test_future_notice_binding_rejects_mutation(tmp_path: Path, work_id: str) -> None:
    index = json.loads((HOME / "notice-index.json").read_bytes())
    item = next(item for item in index["items"] if item["work_id"] == work_id)
    for original, relative in ((ROOT / item["source_path"], item["source_path"]),
                               (HOME / item["notice_path"], item["notice_path"])):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    acceptance_source = (STAGE / work_id / "library/works" / work_id / "forms" /
                         f"{work_id}-openmgh-retained" / "editions" /
                         f"{work_id}-openmgh-electronic" / "acceptance.json")
    acceptance = tmp_path / "acceptance.json"
    shutil.copy2(_io_path(acceptance_source), acceptance)
    binding = {key: item[key] for key in
               ("source_path", "source_sha256", "notice_path", "notice_sha256")}
    selected = {"work_id": work_id, "public_notices": [binding]}
    texts = notice_texts_for_item(tmp_path, selected, acceptance)
    assert len(texts) == 1 and "Monumenta Germaniae Historica" in texts[0]
    (tmp_path / item["notice_path"]).write_text(texts[0] + "changed\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        notice_texts_for_item(tmp_path, selected, acceptance)


def test_original_preflight_rejects_wrong_root(historical_context: tuple[Path, Path, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _root, receipt, digest = historical_context
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="stage or canonical root differs"):
        installer.preflight(receipt, expected_receipt_sha256=digest)
