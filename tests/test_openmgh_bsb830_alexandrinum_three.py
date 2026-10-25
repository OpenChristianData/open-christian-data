"""Focused bsb830 three-poem source, notice, and transaction proof."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
import pytest

from build.tei import openmgh_bsb830_alexandrinum_three as source
from build.tei.openmgh_bsb830_alexandrinum_three_oracle import SPANS, check
from build.tools import install_openmgh_bsb830_alexandrinum_three as installer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from tests.openmgh_late_historical_fixture import historical_mgh_freeze_context


INPUT_ROOT = installer.ROOT
ORIGINAL_FREEZE_SHA = installer.FREEZE_SHA


@pytest.fixture(scope="module")
def historical_context(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    bindings = [(source.SOURCE, source.SOURCE_SHA), (source.PACKAGE, source.PACKAGE_SHA),
                (source.ACQUISITION_RECEIPT, source.ACQUISITION_RECEIPT_SHA)]
    return historical_mgh_freeze_context(
        INPUT_ROOT, tmp_path_factory.mktemp("mgh-historical"), installer.freezing.FREEZE,
        ORIGINAL_FREEZE_SHA, tuple(bindings),
    )


@pytest.fixture(autouse=True)
def isolated_historical_installer(monkeypatch: pytest.MonkeyPatch, historical_context: tuple[Path, Path, str]) -> None:
    root, freeze, digest = historical_context
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer, "FREEZE_SHA", digest)
    monkeypatch.setattr(installer.freezing, "FREEZE", freeze)
    monkeypatch.setattr(source, "ROOT", root)


def _direct() -> dict:
    return json.loads(_io_path(installer.staging.DIRECT / "receipt.json").read_bytes())


def test_exact_source_partition_and_all_three_candidates() -> None:
    with ZipFile(source.ROOT / source.PACKAGE) as package:
        assert package.namelist() == ["bsb00000830.xml"]
        assert package.read("bsb00000830.xml") == _io_path(source.ROOT / source.SOURCE).read_bytes()
    entries = {item["work_id"]: item for item in _direct()["selected_works"]}
    assert set(entries) == set(source.SELECTED)
    assert sum(end - start + 1 for start, end, _, _ in SPANS.values()) == 230
    assert sorted((start, end) for start, end, _, _ in SPANS.values()) == [
        (5, 116), (117, 194), (195, 234)
    ]
    assert _direct()["boundary_page"] == dict(
        child_index=117, xml_id="bsb00000830_00560", owner="verses-against-octavian")
    for work_id, entry in entries.items():
        candidate = _io_path(Path(entry["candidate_path"])).read_bytes()
        reproduced, producer = source.convert(work_id)
        assert reproduced == candidate and producer == entry["producer"]
        assert check(work_id, candidate) == entry["oracle"]
        assert _io_path(installer.staging.REPRO / work_id / "candidate.tei.xml").read_bytes() == candidate


def test_freeze_is_complete_and_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    freeze_bytes = _io_path(installer.freezing.FREEZE).read_bytes()
    assert sha256(freeze_bytes).hexdigest() == installer.FREEZE_SHA
    frozen = installer._frozen()
    assert frozen["source_division_child_count"] == 235
    assert frozen["shared_heading_child_indexes"] == [0, 1, 2, 3, 4]
    assert frozen["boundary_page"]["owner"] == "verses-against-octavian"
    assert frozen["other_source_work_divisions"] == 28
    assert {item["work_id"] for item in frozen["works"]} == set(source.SELECTED)
    for work_id in source.SELECTED:
        preflight = installer.preflight(work_id)
        assert preflight["status"] == "ready-for-review"
        assert preflight["installation"] == "not-performed"
        assert preflight["projection_rows"] == 1
    with pytest.raises(PipelineError, match="absent"):
        installer.preflight("bsb830-not-selected")
    monkeypatch.setattr(installer, "FREEZE_SHA", "0" * 64)
    with pytest.raises(PipelineError, match="freeze changed"):
        installer.preflight("verses-against-octavian")


def test_oracle_rejects_missing_line_neighbor_and_header_mutations() -> None:
    entries = _direct()["selected_works"]
    first = next(item for item in entries if item["work_id"] == "cause-of-the-two-popes-octavian-and-alexander")
    neighbor = next(item for item in entries if item["work_id"] == "verses-against-octavian")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
    candidate = _io_path(Path(first["candidate_path"])).read_bytes()
    document = etree.fromstring(candidate, parser)
    ab = document.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='ab']")[0]
    ab.remove(ab[1])
    with pytest.raises(ValueError, match="trees differ"):
        check(first["work_id"], etree.tostring(document))
    document = etree.fromstring(_io_path(Path(neighbor["candidate_path"])).read_bytes(), parser)
    ab = document.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='ab']")[0]
    assert ab[0].tag.rsplit("}", 1)[-1] == "pb"
    ab.remove(ab[0])
    with pytest.raises(ValueError, match="trees differ"):
        check(neighbor["work_id"], etree.tostring(document))
    document = etree.fromstring(candidate, parser)
    ab = document.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='ab']")[0]
    other = etree.fromstring(_io_path(Path(neighbor["candidate_path"])).read_bytes(), parser)
    other_ab = other.xpath("//*[local-name()='body']/*[local-name()='div']/*[local-name()='ab']")[0]
    ab[1].getparent().replace(ab[1], other_ab[1])
    with pytest.raises(ValueError, match="trees differ"):
        check(first["work_id"], etree.tostring(document))
    document = etree.fromstring(candidate, parser)
    publisher = document.xpath("//*[local-name()='publicationStmt']/*[local-name()='publisher']")[0]
    publisher.text = "No source credit"
    with pytest.raises(ValueError, match="publication"):
        check(first["work_id"], etree.tostring(document))
    with pytest.raises(ValueError, match="retained XML changed"):
        check(first["work_id"], candidate, source_override=_io_path(source.ROOT / source.SOURCE).read_bytes() + b" ")


def test_future_public_notices_bind_visible_credit(tmp_path: Path) -> None:
    home = Path("D:/Library/Open Christian Data/candidate-reviews/bsb830-alexandrinum-three-public-notices-20260927-v1")
    index = json.loads(_io_path(home / "notice-index.json").read_bytes())
    assert index["freeze_sha256"] == ORIGINAL_FREEZE_SHA
    assert {item["work_id"] for item in index["items"]} == set(source.SELECTED)
    for item in index["items"]:
        note = _io_path(INPUT_ROOT / item["source_path"]).read_bytes()
        notice = _io_path(home / item["notice_path"]).read_bytes()
        assert sha256(note).hexdigest() == item["source_sha256"]
        assert sha256(notice).hexdigest() == item["notice_sha256"]
        assert b"Monumenta Germaniae Historica" in notice and b"Bavarian State Library" in notice
        for relative, content in ((item["source_path"], note), (item["notice_path"], notice)):
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        acceptance = tmp_path / "acceptance.json"
        acceptance.write_text(json.dumps({"identity": {"work_id": item["work_id"]}}), encoding="utf-8")
        selection = {key: item[key] for key in ("source_path", "source_sha256", "notice_path", "notice_sha256")}
        assert len(notice_texts_for_item(tmp_path, {"work_id": item["work_id"],
                                                    "public_notices": [selection]}, acceptance)) == 1
        (tmp_path / item["notice_path"]).write_text("# Changed notice\n", encoding="utf-8")
        with pytest.raises(PipelineError, match="SHA-256 mismatch"):
            notice_texts_for_item(tmp_path, {"work_id": item["work_id"],
                                             "public_notices": [selection]}, acceptance)


def test_stock_transaction_rolls_back_isolated_work(tmp_path: Path) -> None:
    work_id = "cause-of-the-two-popes-octavian-and-alexander"
    _, stage, record = installer._work_pin(installer._frozen(), work_id)
    fixture = tmp_path / "r"
    work = Path("library/works") / work_id
    target = fixture / work
    for relative in _files(source.ROOT / work):
        original, copied = _io_path(source.ROOT / work / relative), _io_path(target / relative)
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes(original.read_bytes())
    before = _files(target)
    assert before == record["before"]

    def fail(point: str) -> None:
        if point == "after-new-live":
            raise RuntimeError("injected bsb830 rollback")

    with pytest.raises(RuntimeError, match="injected bsb830 rollback"):
        _commit_generation(fixture, target, stage / work, work_id=work_id,
                           before=record["before"], after=record["after"], existed=True, replacement=False,
                           operation_kind="bsb830-Alexandrinum-fixture", result_status="installed-and-validated",
                           accepted_editions=1, fail_at=fail)
    assert _files(target) == before
    journals = list((fixture / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"


def test_original_frozen_guard_rejects_wrong_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="bsb830.*frozen roots differ"):
        installer._frozen()
