"""Focused bsb752 nested source ownership, frozen stages, and rollback."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tools import install_openmgh_bsb752_nested as installer
from build.tools import prepare_openmgh_bsb752_nested as source
from ocd_kernel.library._common import PipelineError
from tests.openmgh_historical_fixture import historical_nested_installer_context
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
    return json.loads(_io_path(Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb752-nested-direct-20260927-v1/receipt.json")).read_bytes())


def test_all_26_source_divisions_and_16_shared_parts_are_accounted() -> None:
    direct = _direct()
    selected = {(item["source_work_div_index"], j) for item in direct["selected_works"] for j in item["source_part_indexes"]}
    held = {(item["source_work_div_index"], item["source_part_index"]) for item in direct["held_parts"]}
    assert len(direct["selected_works"]) == 11
    assert len(selected) == 13
    assert held == {(8, 2), (8, 3), (19, 2)}
    assert selected.isdisjoint(held)
    assert selected | held == {(i, j) for i, n in ((8, 4), (14, 3), (15, 4), (17, 2), (19, 3)) for j in range(n)}
    assert {item["index"] for item in direct["other_source_divisions"]} == set(range(26)) - {8, 14, 15, 17, 19}
    assert {item["index"] for item in direct["other_source_divisions"] if not item["catalog_owners"]} == {4, 11, 25}
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
    reproduced = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb752-nested-direct-20260927-v2") / work_id / "candidate.tei.xml"
    assert _io_path(reproduced).read_bytes() == candidate


def test_oracle_rejects_lost_source_page_marker() -> None:
    direct = _direct()
    entry = next(item for item in direct["selected_works"] if item["work_id"] == "vita-sancti-faronis")
    _, _, source_works = source._source()
    selected = [source_works[8][j] for j in (0, 1)]
    work = json.loads(_io_path(source.ROOT / "library/works/vita-sancti-faronis/work.json").read_bytes())
    candidate = etree.fromstring(_io_path(Path(entry["candidate_path"])).read_bytes())
    marker = candidate.xpath("//*[local-name()='body']//*[local-name()='pb']")[0]
    marker.getparent().remove(marker)
    with pytest.raises(ValueError, match="C14N"):
        source._check(selected, etree.tostring(candidate), source._locators(work, source.SOURCE))


def test_oracle_rejects_neighbor_locator() -> None:
    direct = _direct()
    entry = next(item for item in direct["selected_works"] if item["work_id"] == "vita-sancti-amandi")
    _, _, source_works = source._source()
    selected = [source_works[14][0]]
    candidate = _io_path(Path(entry["candidate_path"])).read_bytes()
    with pytest.raises(ValueError, match="locator"):
        source._check(selected, candidate, ("bsb00000752_00458_1", entry["oracle"]["end_xml_id"]))


def test_batch_freeze_hash_and_allowlist() -> None:
    assert sha256(_io_path(installer.FREEZE).read_bytes()).hexdigest() == installer.FREEZE_SHA
    frozen = installer._frozen()
    assert {item["work_id"] for item in frozen["works"]} == set(source.SELECTIONS)
    assert len(frozen["works"]) == 11
    with pytest.raises(PipelineError, match="absent"):
        installer.preflight("conversio-othgerii-militis")


def test_stock_transaction_rolls_back_isolated_work(tmp_path: Path) -> None:
    work_id = "epistola-pauli-ad-wambam"
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
            raise RuntimeError("injected bsb752 rollback")

    with pytest.raises(RuntimeError, match="injected bsb752 rollback"):
        _commit_generation(fixture, target, stage / work, work_id=work_id,
                           before=record["before"], after=record["after"],
                           existed=True, replacement=False, operation_kind="openmgh-bsb752-nested-fixture",
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
