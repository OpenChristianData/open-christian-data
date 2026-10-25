"""Focused source and guarded-stage checks for two Passio Dormientium editions."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tei import openmgh_passio_dormientium_dual as source
from build.tei.openmgh_passio_dormientium_dual_oracle import check
from build.tools import freeze_openmgh_passio_dormientium_dual as freezing
from build.tools import install_openmgh_passio_dormientium_dual as installer
from build.tools import stage_openmgh_passio_dormientium_dual as staging
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from tests.openmgh_late_historical_fixture import historical_mgh_freeze_context
from ocd_kernel.tei.validate import validate_file


INPUT_ROOT = installer.ROOT
ORIGINAL_FREEZE_SHA = installer.FREEZE_SHA


@pytest.fixture(scope="module")
def historical_context(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    bindings = []
    for code, spec in source.WITNESSES.items():
        xml, package, acquired = source.paths(code)
        bindings.extend(((xml, spec["source_sha256"]), (package, spec["package_sha256"]),
                         (acquired, spec["receipt_sha256"])))
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


def _frozen() -> dict:
    return json.loads(_io_path(freezing.FREEZE).read_bytes())


def test_both_complete_divisions_are_distinct_reproduced_and_p5(tmp_path: Path) -> None:
    frozen = _frozen()
    assert frozen["selected_edition_count"] == 2
    assert frozen["total_sibling_work_divisions"] == 24
    assert len(frozen["before"]) == 4 and len(frozen["after"]) == 31
    for item in frozen["editions"]:
        code = item["code"]
        candidate, report = source.convert(code)
        assert report["candidate_sha256"] == item["direct_candidate_sha256"]
        assert candidate == _io_path(staging.REPRO / code / "candidate.tei.xml").read_bytes()
        assert check(code, candidate) == item["oracle"]
        assert item["oracle"]["source_div_c14n_sha256"] == report["source_div_c14n_sha256"]
        path = tmp_path / f"{code}.xml"
        path.write_bytes(candidate)
        assert validate_file(path) == []


def test_independent_oracle_rejects_line_header_and_neighbor_mutations() -> None:
    original, _ = source.convert("bsb00000754")
    other, _ = source.convert("bsb00050862")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
    candidate = etree.fromstring(original, parser)
    body = candidate.xpath("//*[local-name()='body']")[0]
    line = body[0][0].xpath(".//*[local-name()='lb']")[3]
    line.getparent().remove(line)
    with pytest.raises(ValueError, match="full Passio Dormientium tree"):
        check("bsb00000754", etree.tostring(candidate))
    candidate = etree.fromstring(original, parser)
    candidate.xpath("//*[local-name()='publicationStmt']/*[local-name()='publisher']")[0].text = "Unknown"
    with pytest.raises(ValueError, match="header"):
        check("bsb00000754", etree.tostring(candidate))
    candidate = etree.fromstring(original, parser)
    other_body = etree.fromstring(other, parser).xpath("//*[local-name()='body']")[0]
    body = candidate.xpath("//*[local-name()='body']")[0]
    body.replace(body[0], other_body[0])
    with pytest.raises(ValueError, match="full Passio Dormientium tree"):
        check("bsb00000754", etree.tostring(candidate))


def test_guarded_read_only_preflight_and_freeze_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    result = installer.preflight()
    assert result == {
        "status": "ready-for-review", "work_id": source.WORK_ID,
        "before_files": 4, "after_files": 31, "accepted_editions": 2,
        "projection_rows": 2,
        "stage_receipt": (freezing.STAGE / "stage-receipt.json").as_posix(),
        "installation": "not-performed",
    }
    monkeypatch.setattr(installer, "FREEZE_SHA", "0" * 64)
    with pytest.raises(PipelineError, match="freeze changed"):
        installer.preflight()


def test_future_visible_notice_binding_rejects_mutation(tmp_path: Path) -> None:
    home = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-passio-dormientium-dual-public-notice-20260928-v2")
    index = json.loads(_io_path(home / "notice-index.json").read_bytes())
    assert index["freeze_sha256"] == ORIGINAL_FREEZE_SHA
    assert {item["code"] for item in index["editions"]} == set(source.WITNESSES)
    note = _io_path(INPUT_ROOT / index["source_path"]).read_bytes()
    notice = _io_path(home / index["notice_path"]).read_bytes()
    assert sha256(note).hexdigest() == index["source_sha256"]
    assert sha256(notice).hexdigest() == index["notice_sha256"]
    assert b"Monumenta Germaniae Historica" in notice and b"Bavarian State Library" in notice
    for relative, content in ((index["source_path"], note), (index["notice_path"], notice)):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps({"identity": {"work_id": source.WORK_ID}}), encoding="utf-8")
    selection = {key: index[key] for key in ("source_path", "source_sha256", "notice_path", "notice_sha256")}
    assert len(notice_texts_for_item(tmp_path, {"work_id": source.WORK_ID,
                                                "public_notices": [selection]}, acceptance)) == 1
    (tmp_path / index["notice_path"]).write_text("# Changed\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        notice_texts_for_item(tmp_path, {"work_id": source.WORK_ID,
                                        "public_notices": [selection]}, acceptance)


def test_stock_transaction_rolls_back_both_editions(tmp_path: Path) -> None:
    record = json.loads(_io_path(freezing.STAGE / "stage-receipt.json").read_bytes())
    fixture = tmp_path / "r"
    work = Path("library/works") / source.WORK_ID
    target = fixture / work
    for rel in _files(source.ROOT / work):
        copied = _io_path(target / rel)
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes(_io_path(source.ROOT / work / rel).read_bytes())
    before = _files(target)
    assert before == record["before"]

    def fail(point: str) -> None:
        if point == "after-new-live":
            raise RuntimeError("injected dual-edition rollback")

    with pytest.raises(RuntimeError, match="injected dual-edition rollback"):
        _commit_generation(fixture, target, freezing.STAGE / work, work_id=source.WORK_ID,
                           before=record["before"], after=record["after"], existed=True,
                           replacement=False, operation_kind="passio-dormientium-dual-fixture",
                           result_status="installed-and-validated", accepted_editions=2, fail_at=fail)
    assert _files(target) == before
    journals = list((fixture / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"



def test_original_frozen_guard_rejects_wrong_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="Passio Dormientium.*(scope|authority)"):
        installer._frozen()
