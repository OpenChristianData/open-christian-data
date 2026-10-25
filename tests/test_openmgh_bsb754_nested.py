"""Focused bsb754 nested source ownership, frozen stages, and rollback."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tools import install_openmgh_bsb754_nested as installer
from build.tools import prepare_openmgh_bsb754_nested as source
from ocd_kernel.library._common import PipelineError
from tests.openmgh_historical_fixture import historical_nested_installer_context
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path


INPUT_ROOT = source.ROOT


@pytest.fixture(scope="module")
def historical_context(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    return historical_nested_installer_context(
        INPUT_ROOT, tmp_path_factory.mktemp("mgh-nested-historical"), installer.FREEZE,
        installer.FREEZE_SHA, ((source.SOURCE, source.SOURCE_SHA),
                              (source.PACKAGE, source.PACKAGE_SHA),
                              (source.ACQUISITION_RECEIPT, source.ACQUISITION_RECEIPT_SHA)),
    )


@pytest.fixture(autouse=True)
def isolated_historical_installer(monkeypatch: pytest.MonkeyPatch, historical_context: tuple[Path, Path, str]) -> None:
    root, freeze, digest = historical_context
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer, "FREEZE", freeze)
    monkeypatch.setattr(installer, "FREEZE_SHA", digest)


def _direct() -> dict:
    return json.loads(_io_path(Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-nested-direct-20260927-v3/receipt.json")).read_bytes())


def test_all_20_source_divisions_and_seven_shared_parts_are_accounted() -> None:
    direct = _direct()
    selected = {(item["source_work_div_index"], j) for item in direct["selected_works"] for j in item["source_part_indexes"]}
    held = {(item["source_work_div_index"], item["source_part_index"]) for item in direct["held_parts"]}
    assert len(direct["selected_works"]) == 5
    assert len(selected) == 5
    assert held == {(4, 1), (12, 1)}
    assert selected.isdisjoint(held)
    assert selected | held == {(i, j) for i, n in ((0, 2), (4, 2), (12, 3)) for j in range(n)}
    assert {item["index"] for item in direct["other_source_divisions"]} == set(range(20)) - {0, 4, 12}
    assert {item["index"] for item in direct["other_source_divisions"] if not item["catalog_owners"]} == {7, 14, 16, 19}
    assert {item["index"] for item in direct["other_source_divisions"] if "another retained" in item["disposition"]} == {9, 11, 18}
    assert source.SOURCE.suffix == ".xml" and source.PACKAGE.suffix == ".zip"


@pytest.mark.parametrize("work_id", sorted(source.SELECTIONS))
def test_complete_native_parts_match_source_and_reproduction(work_id: str) -> None:
    direct = _direct()
    entry = next(item for item in direct["selected_works"] if item["work_id"] == work_id)
    _, _, source_works = source._source()
    index, indexes = source.SELECTIONS[work_id]
    selected = [source_works[index][j] for j in indexes]
    work = json.loads(_io_path(source.ROOT / "library/works" / work_id / "work.json").read_bytes())
    candidate = _io_path(Path(entry["candidate_path"])).read_bytes()
    assert source._check(selected, candidate, source._locators(work, source.SOURCE)) == entry["oracle"]
    assert sha256(candidate).hexdigest() == entry["candidate_sha256"]
    reproduced = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-nested-direct-20260927-v4") / work_id / "candidate.tei.xml"
    assert _io_path(reproduced).read_bytes() == candidate


def test_oracle_rejects_lost_source_page_marker() -> None:
    direct = _direct()
    entry = next(item for item in direct["selected_works"] if item["work_id"] == "vita-sancti-leutfredi")
    _, _, source_works = source._source()
    selected = [source_works[0][0]]
    work = json.loads(_io_path(source.ROOT / "library/works/vita-sancti-leutfredi/work.json").read_bytes())
    candidate = etree.fromstring(_io_path(Path(entry["candidate_path"])).read_bytes())
    marker = candidate.xpath("//*[local-name()='body']//*[local-name()='pb']")[0]
    marker.getparent().remove(marker)
    with pytest.raises(ValueError, match="C14N"):
        source._check(selected, etree.tostring(candidate), source._locators(work, source.SOURCE))


def test_oracle_rejects_neighbor_locator() -> None:
    direct = _direct()
    entry = next(item for item in direct["selected_works"] if item["work_id"] == "vita-sancti-leutfredi")
    _, _, source_works = source._source()
    selected = [source_works[0][0]]
    candidate = _io_path(Path(entry["candidate_path"])).read_bytes()
    with pytest.raises(ValueError, match="locator"):
        source._check(selected, candidate, ("bsb00000754_00026_16", entry["oracle"]["end_xml_id"]))


def test_all_literal_locator_pairs_are_in_source_order() -> None:
    direct = _direct()
    pins = {item["work_id"]: item for item in installer._frozen()["works"]}
    for entry in direct["selected_works"]:
        assert entry["catalog_locator_ids"] == entry["ordered_source_locator_ids"]
        assert pins[entry["work_id"]]["catalog_locator_ids"] == entry["catalog_locator_ids"]


def test_batch_freeze_hash_and_allowlist() -> None:
    assert sha256(_io_path(installer.FREEZE).read_bytes()).hexdigest() == installer.FREEZE_SHA
    frozen = installer._frozen()
    assert {item["work_id"] for item in frozen["works"]} == set(source.SELECTIONS)
    assert len(frozen["works"]) == 5
    with pytest.raises(PipelineError, match="absent"):
        installer.preflight("hymnus-sancti-gangulfi")


def test_future_public_notices_are_source_bound(tmp_path: Path) -> None:
    handoff = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb754-public-notices-20260927-v1")
    index = json.loads(_io_path(handoff / "notice-index.json").read_bytes())
    assert {item["work_id"] for item in index["items"]} == set(source.SELECTIONS)
    for item in index["items"]:
        source_note = _io_path(source.ROOT / item["source_path"]).read_bytes()
        public_notice = _io_path(handoff / item["notice_path"]).read_bytes()
        assert sha256(source_note).hexdigest() == item["source_sha256"]
        assert sha256(public_notice).hexdigest() == item["notice_sha256"]
        for relative, content in ((item["source_path"], source_note), (item["notice_path"], public_notice)):
            destination = tmp_path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        acceptance = tmp_path / "acceptance.json"
        acceptance.write_text(json.dumps({"identity": {"work_id": item["work_id"]}}), encoding="utf-8")
        selected = {key: item[key] for key in ("source_path", "source_sha256", "notice_path", "notice_sha256")}
        assert len(notice_texts_for_item(tmp_path, {"work_id": item["work_id"], "public_notices": [selected]}, acceptance)) == 1


def test_stock_transaction_rolls_back_isolated_work(tmp_path: Path) -> None:
    work_id = "miracula-ad-sepulchrum-leutfredi"
    frozen = installer._frozen()
    _, stage, record = installer._work_pin(frozen, work_id)
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
            raise RuntimeError("injected bsb754 rollback")

    with pytest.raises(RuntimeError, match="injected bsb754 rollback"):
        _commit_generation(fixture, target, stage / work, work_id=work_id,
                           before=record["before"], after=record["after"],
                           existed=True, replacement=False, operation_kind="openmgh-bsb754-nested-fixture",
                           result_status="installed-and-validated", accepted_editions=1, fail_at=fail)
    assert _files(target) == before
    journals = list((fixture / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"


def test_original_frozen_guard_rejects_wrong_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="frozen roots differ|freeze scope or authority differs"):
        installer._frozen()


def test_current_generation_is_rejected_by_original_preflight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Keep the real strict installer and current metadata; only root context is adapted.
    frozen = json.loads(_io_path(installer.FREEZE).read_bytes())
    frozen["canonical_root"] = INPUT_ROOT.as_posix()
    raw = (json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path = tmp_path / "current-root-freeze-context.json"
    path.write_bytes(raw)
    import hashlib
    monkeypatch.setattr(installer, "ROOT", INPUT_ROOT)
    monkeypatch.setattr(installer, "FREEZE", path)
    monkeypatch.setattr(installer, "FREEZE_SHA", hashlib.sha256(raw).hexdigest())
    with pytest.raises(PipelineError, match="canonical or staged work generation changed"):
        installer.preflight(next(iter(source.SELECTIONS)))
