"""Focused exact source, page ownership, and future notice checks for Reimundi."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lxml import etree
import pytest

from build.tei.openmgh_bsb720_reimundi_oracle import check_candidate
from build.tools import install_openmgh_bsb720_reimundi as installer
from build.tools import prepare_openmgh_bsb720_reimundi as source
from build.tools.stage_openmgh_inspected_acceptance import _files
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _commit_generation, _io_path
from tests.openmgh_historical_fixture import historical_receipt_context


ROOT = Path(__file__).resolve().parents[1]
WORK_ID = "lambertus-epitaphium-reimundi"
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb720-reimundi-public-notice-20260928-v2")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb720-reimundi-stage-20260928-v2")


def _example() -> tuple[bytes, bytes, dict, dict]:
    retained, tree = source._source(source.ROOT)
    work, acquisition, _work_path, _acquisition_path = source._work(source.ROOT, WORK_ID)
    return retained, source._candidate(tree, work, 21), work, acquisition


@pytest.fixture(scope="module")
def historical_context(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    assert len(installer.PINS) == 1
    receipt, digest = installer._receipt(next(iter(installer.PINS)))
    return historical_receipt_context(
        ROOT, tmp_path_factory.mktemp("mgh-historical"), receipt, digest,
        ((source.SOURCE, source.SOURCE_SHA256), (source.PACKAGE, source.PACKAGE_SHA256),
         (source.RECEIPT, source.RECEIPT_SHA256)),
    )


def test_complete_span_internal_page_and_read_only_preflight(historical_context: tuple[Path, Path, str], monkeypatch: pytest.MonkeyPatch) -> None:
    retained, candidate, work, acquisition = _example()
    checked = check_candidate(retained, candidate, work, acquisition, number=21)
    assert (checked["source_child_start"], checked["source_child_end"]) == (123, 130)
    assert checked["internal_page_break"] == "bsb00000720_00273"
    assert checked["line_count"] == 6
    tree = etree.fromstring(candidate)
    block = tree.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='ab']")[0]
    assert [etree.QName(node).localname for node in block] == ["lb", "lb", "lb", "pb", "lb", "lb", "lb", "lb"]
    root, receipt, digest = historical_context
    monkeypatch.setattr(installer, "ROOT", root)
    assert installer.preflight(receipt, expected_receipt_sha256=digest)["status"] == "ready-for-review"


def test_oracle_rejects_dropped_internal_page() -> None:
    retained, candidate, work, acquisition = _example()
    tree = etree.fromstring(candidate)
    block = tree.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='ab']")[0]
    block.remove(block[3])
    with pytest.raises(ValueError, match="candidate source block differs"):
        check_candidate(retained, etree.tostring(tree), work, acquisition, number=21)


def test_oracle_rejects_changed_internal_page_id() -> None:
    retained, candidate, work, acquisition = _example()
    tree = etree.fromstring(candidate)
    block = tree.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='ab']")[0]
    block[3].set("{http://www.w3.org/XML/1998/namespace}id", "changed")
    with pytest.raises(ValueError, match="candidate native source line changed"):
        check_candidate(retained, etree.tostring(tree), work, acquisition, number=21)


def test_future_notice_exact_binding(tmp_path: Path) -> None:
    index = json.loads((HOME / "notice-index.json").read_bytes())
    for original, relative in ((ROOT / index["source_path"], index["source_path"]),
                               (HOME / index["notice_path"], index["notice_path"])):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    acceptance_source = (STAGE / "library/works" / WORK_ID / "forms" /
                         f"{WORK_ID}-openmgh-retained" / "editions" /
                         f"{WORK_ID}-openmgh-electronic" / "acceptance.json")
    acceptance = tmp_path / "acceptance.json"
    shutil.copy2(_io_path(acceptance_source), acceptance)
    binding = {key: index[key] for key in
               ("source_path", "source_sha256", "notice_path", "notice_sha256")}
    selected = {"work_id": WORK_ID, "public_notices": [binding]}
    texts = notice_texts_for_item(tmp_path, selected, acceptance)
    assert len(texts) == 1 and "Monumenta Germaniae Historica" in texts[0]
    assert "Bavarian State Library" in texts[0]
    (tmp_path / index["notice_path"]).write_text(texts[0] + "changed\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        notice_texts_for_item(tmp_path, selected, acceptance)


def test_stock_work_transaction_rolls_back_after_new_live(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    target = root / "library/works" / WORK_ID
    staged = tmp_path / "stage/library/works" / WORK_ID
    target.mkdir(parents=True)
    staged.mkdir(parents=True)
    (target / "old.txt").write_text("before", encoding="utf-8")
    (staged / "new.txt").write_text("after", encoding="utf-8")
    before, after = _files(target), _files(staged)

    def fail_after_live(checkpoint: str) -> None:
        if checkpoint == "after-new-live":
            raise RuntimeError("injected Reimundi rollback")

    with pytest.raises(RuntimeError, match="injected Reimundi rollback"):
        _commit_generation(
            root, target, staged, work_id=WORK_ID,
            before=before, after=after, existed=True, replacement=False,
            operation_kind="openmgh-bsb720-reimundi-fixture", result_status="fixture",
            accepted_editions=1, fail_at=fail_after_live,
        )
    assert _files(target) == before
    journals = list((root / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"


def test_original_preflight_rejects_wrong_root(historical_context: tuple[Path, Path, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _root, receipt, digest = historical_context
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="stage or canonical root differs"):
        installer.preflight(receipt, expected_receipt_sha256=digest)
