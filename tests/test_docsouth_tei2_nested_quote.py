"""Focused nested-quote DocSouth source, freeze, mutation, and rollback proof."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tei import docsouth_tei2_nested_quote as source
from build.tei.docsouth_tei2_nested_quote_oracle import check
from build.tools import install_docsouth_tei2_nested_quote as installer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from tests.openmgh_historical_fixture import historical_docsouth_context, historical_docsouth_source_note


INPUT_ROOT = installer.ROOT
ORIGINAL_FREEZE_SHA = installer.FREEZE_SHA


@pytest.fixture(scope="module")
def historical_context(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    return historical_docsouth_context(
        INPUT_ROOT, tmp_path_factory.mktemp("docsouth-historical"), installer.freezing.FREEZE,
        ORIGINAL_FREEZE_SHA,
    )


@pytest.fixture(autouse=True)
def isolated_historical_installer(monkeypatch: pytest.MonkeyPatch, historical_context: tuple[Path, Path, str]) -> None:
    root, freeze, digest = historical_context
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer.freezing, "FREEZE", freeze)
    monkeypatch.setattr(installer, "FREEZE_SHA", digest)
    monkeypatch.setattr(source, "ROOT", root)


def _direct() -> dict:
    return json.loads(_io_path(installer.staging.DIRECT / "receipt.json").read_bytes())


@pytest.mark.parametrize("work_id,nested,rows", [
    ("elijah-p-marrs-life-and-history", 14, 4),
    ("george-white-brief-account-life-experience-travels", 1, 3),
    ("peter-randolph-from-slave-cabin-to-pulpit", 3, 6),
])
def test_exact_source_oracle_and_guarded_preflight(work_id: str, nested: int, rows: int) -> None:
    entry = next(item for item in _direct()["selected_works"] if item["work_id"] == work_id)
    candidate = _io_path(Path(entry["candidate_path"])).read_bytes()
    reproduced, producer = source.convert(work_id)
    assert reproduced == candidate and producer == entry["producer"]
    oracle = check(source.ROOT / entry["source_path"], entry["source_sha256"], candidate)
    assert oracle == entry["oracle"] and oracle["source_nested_text_count"] == nested
    assert _io_path(installer.staging.REPRO / work_id / "candidate.tei.xml").read_bytes() == candidate
    result = installer.preflight(work_id)
    assert result["projection_rows"] == rows
    assert result["source_nested_text_count"] == nested
    assert result["source_entity_declarations"] == 0
    assert result["installation"] == "not-performed"


def test_freeze_scope_and_exclusion() -> None:
    assert sha256(_io_path(installer.freezing.FREEZE).read_bytes()).hexdigest() == installer.FREEZE_SHA
    frozen = installer._frozen()
    assert {item["work_id"] for item in frozen["works"]} == source.SELECTIONS
    assert frozen["other_inventory_work_count"] == 24
    with pytest.raises(PipelineError, match="absent"):
        installer.preflight("slave-songs-of-the-united-states")


def test_oracle_rejects_nested_ownership_and_link_carrier_mutation() -> None:
    entry = next(item for item in _direct()["selected_works"] if item["work_id"] == "george-white-brief-account-life-experience-travels")
    original = _io_path(Path(entry["candidate_path"])).read_bytes()
    document = etree.fromstring(original)
    floating = document.xpath("//*[local-name()='floatingText']")[0]
    floating.getparent().remove(floating)
    with pytest.raises(ValueError, match="nested-text|structure|unit"):
        check(source.ROOT / entry["source_path"], entry["source_sha256"], etree.tostring(document))
    document = etree.fromstring(original)
    link = document.xpath("//*[local-name()='ref' and @subtype='source-targOrder-U']")[0]
    link.set("subtype", "source-targOrder-X")
    with pytest.raises(ValueError, match="attributes"):
        check(source.ROOT / entry["source_path"], entry["source_sha256"], etree.tostring(document))
    document = etree.fromstring(original)
    note = document.xpath("//*[local-name()='note' and starts-with(@type,'source-target-')]")[0]
    note.set("type", "source-target-wrong")
    with pytest.raises(ValueError, match="attributes"):
        check(source.ROOT / entry["source_path"], entry["source_sha256"], etree.tostring(document))


def test_oracle_rejects_rights_mutation() -> None:
    entry = _direct()["selected_works"][0]
    document = etree.fromstring(_io_path(Path(entry["candidate_path"])).read_bytes())
    availability = document.xpath("//*[local-name()='publicationStmt']/*[local-name()='availability']")[0]
    availability.text = "Worldwide public domain."
    with pytest.raises(ValueError, match="wording"):
        check(source.ROOT / entry["source_path"], entry["source_sha256"], etree.tostring(document))


def test_future_public_notices_are_source_bound(tmp_path: Path) -> None:
    home = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-nested-public-notices-20260927-v1")
    index = json.loads(_io_path(home / "notice-index.json").read_bytes())
    assert {item["work_id"] for item in index["items"]} == source.SELECTIONS
    assert index["freeze_sha256"] == ORIGINAL_FREEZE_SHA
    for item in index["items"]:
        source_note = historical_docsouth_source_note(
            _io_path(INPUT_ROOT / item["source_path"]).read_bytes(), item["source_sha256"]
        )
        notice = _io_path(home / item["notice_path"]).read_bytes()
        assert sha256(source_note).hexdigest() == item["source_sha256"]
        assert sha256(notice).hexdigest() == item["notice_sha256"]
        for relative, content in ((item["source_path"], source_note), (item["notice_path"], notice)):
            destination = tmp_path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        acceptance = tmp_path / "acceptance.json"
        acceptance.write_text(json.dumps({"identity": {"work_id": item["work_id"]}}), encoding="utf-8")
        selected = {key: item[key] for key in ("source_path", "source_sha256", "notice_path", "notice_sha256")}
        assert len(notice_texts_for_item(tmp_path, {"work_id": item["work_id"], "public_notices": [selected]}, acceptance)) == 1


def test_stock_transaction_rolls_back_isolated_work(tmp_path: Path) -> None:
    work_id = "george-white-brief-account-life-experience-travels"
    _, stage, record = installer._work_pin(installer._frozen(), work_id)
    fixture = tmp_path / "r"
    work = Path("library/works") / work_id
    target = fixture / work
    for relative in _files(installer.ROOT / work):
        original, copied = _io_path(installer.ROOT / work / relative), _io_path(target / relative)
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes(original.read_bytes())
    before = _files(target)
    assert before == record["before"]

    def fail(point: str) -> None:
        if point == "after-new-live":
            raise RuntimeError("injected DocSouth nested rollback")

    with pytest.raises(RuntimeError, match="injected DocSouth nested rollback"):
        _commit_generation(fixture, target, stage / work, work_id=work_id,
                           before=record["before"], after=record["after"], existed=True, replacement=False,
                           operation_kind="docsouth-tei2-nested-quote-fixture",
                           result_status="installed-and-validated", accepted_editions=1, fail_at=fail)
    assert _files(target) == before
    journals = list((fixture / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"


def test_original_frozen_guard_rejects_wrong_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="DocSouth frozen roots differ"):
        installer._frozen()


def test_current_generation_is_rejected_by_original_preflight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import hashlib

    frozen = json.loads(_io_path(installer.freezing.FREEZE).read_bytes())
    frozen["canonical_root"] = INPUT_ROOT.as_posix()
    raw = (json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path = tmp_path / "current-root-freeze-context.json"
    path.write_bytes(raw)
    monkeypatch.setattr(installer, "ROOT", INPUT_ROOT)
    monkeypatch.setattr(installer.freezing, "FREEZE", path)
    monkeypatch.setattr(installer, "FREEZE_SHA", hashlib.sha256(raw).hexdigest())
    work_id = frozen["works"][0]["work_id"]
    with pytest.raises(PipelineError, match="DocSouth canonical or staged work generation changed"):
        installer.preflight(work_id)
