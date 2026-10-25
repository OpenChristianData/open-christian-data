"""Focused source, stage guard, and future notice tests for three whole works."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lxml import etree
import pytest

from build.tei.openmgh_three_whole_oracle import check_candidate
from build.tools import install_openmgh_three_whole as installer
from build.tools import prepare_openmgh_three_whole as source
from ocd_kernel.library._common import PipelineError
from tests.openmgh_historical_fixture import historical_receipt_context
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[1]
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/three-whole-public-notices-20260928-v1")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/three-whole-stage-20260928-v1")


@pytest.fixture(scope="module")
def historical_contexts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, Path, str]]:
    contexts = {}
    for work_id in source.WORKS:
        receipt, digest = installer._receipt(work_id)
        xml, package, acquired_receipt = source._paths(work_id)
        spec = source.SOURCES[work_id]
        contexts[work_id] = historical_receipt_context(
            ROOT, tmp_path_factory.mktemp("mgh-three-historical"), receipt, digest,
            ((xml, spec["sha256"]), (package, spec["zip_sha256"]),
             (acquired_receipt, spec["receipt_sha256"])),
        )
    return contexts


@pytest.mark.parametrize("work_id", source.WORKS)
def test_complete_work_and_read_only_preflight(work_id: str, historical_contexts: dict[str, tuple[Path, Path, str]], monkeypatch: pytest.MonkeyPatch) -> None:
    retained, tree = source._source(source.ROOT, work_id)
    work, acquisition, _work_path, _acquisition_path = source._work(source.ROOT, work_id)
    candidate = source._candidate(tree, work, work_id)
    checked = check_candidate(retained, candidate, work, acquisition, work_id=work_id)
    spec = source.SOURCES[work_id]
    assert (checked["source_child_start"], checked["source_child_end"]) == (0, spec["parts"] - 1)
    assert checked["source_heading_id"] == spec["heading_id"]
    assert checked["source_end_id"] == spec["end_id"]
    receipt, digest = installer._receipt(work_id)
    # The original pinned receipt stays unchanged; the fixture changes only root context.
    context_root, context_receipt, context_digest = historical_contexts[work_id]
    with monkeypatch.context() as context:
        context.setattr(installer, "ROOT", context_root)
        assert installer.preflight(context_receipt, expected_receipt_sha256=context_digest)["installation"] == "not-performed"


@pytest.mark.parametrize("work_id", source.WORKS)
def test_oracle_rejects_changed_marker_or_missing_book(work_id: str) -> None:
    retained, tree = source._source(source.ROOT, work_id)
    work, acquisition, _work_path, _acquisition_path = source._work(source.ROOT, work_id)
    candidate = source._candidate(tree, work, work_id)
    parsed = etree.fromstring(candidate)
    marker = parsed.xpath("//*[local-name()='body']/*[local-name()='div']//*[local-name()='lb']")[0]
    marker.set("{http://www.w3.org/XML/1998/namespace}id", "changed")
    with pytest.raises(ValueError, match="candidate native whole work changed"):
        check_candidate(retained, etree.tostring(parsed), work, acquisition, work_id=work_id)
    parsed = etree.fromstring(candidate)
    work_div = parsed.xpath("//*[local-name()='body']/*[local-name()='div']")[0]
    work_div.remove(work_div[-1])
    with pytest.raises(ValueError, match="candidate native whole work changed"):
        check_candidate(retained, etree.tostring(parsed), work, acquisition, work_id=work_id)


@pytest.mark.parametrize("work_id", source.WORKS)
def test_oracle_rejects_changed_word_marker(work_id: str) -> None:
    retained, tree = source._source(source.ROOT, work_id)
    work, acquisition, _work_path, _acquisition_path = source._work(source.ROOT, work_id)
    parsed = etree.fromstring(source._candidate(tree, work, work_id))
    words = parsed.xpath("//*[local-name()='w']")
    words[0].set("corresp", "#missing")
    with pytest.raises(ValueError, match="candidate native whole work changed"):
        check_candidate(retained, etree.tostring(parsed), work, acquisition, work_id=work_id)


@pytest.mark.parametrize("work_id", source.WORKS)
def test_future_notice_binding_rejects_mutation(tmp_path: Path, work_id: str) -> None:
    index = json.loads(_io_path(HOME / "notice-index.json").read_bytes())
    item = next(item for item in index["items"] if item["work_id"] == work_id)
    for original, relative in ((ROOT / item["source_path"], item["source_path"]),
                               (HOME / item["notice_path"], item["notice_path"])):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(original), target)
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


def test_original_preflight_rejects_wrong_context_root(historical_contexts: dict[str, tuple[Path, Path, str]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    work_id = next(iter(source.WORKS))
    _root, receipt, digest = historical_contexts[work_id]
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="three-volume stage or canonical root differs"):
        installer.preflight(receipt, expected_receipt_sha256=digest)


def test_current_generation_rejected_by_original_preflight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import hashlib

    receipt, digest = installer._receipt(next(iter(source.WORKS)))
    raw = _io_path(receipt).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    record = json.loads(raw)
    record["canonical_root"] = ROOT.as_posix()
    derived = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path = tmp_path / "current-root-context.json"
    path.write_bytes(derived)
    monkeypatch.setattr(installer, "ROOT", ROOT)
    with pytest.raises(PipelineError, match="canonical or staged work generation changed"):
        installer.preflight(path, expected_receipt_sha256=hashlib.sha256(derived).hexdigest())
