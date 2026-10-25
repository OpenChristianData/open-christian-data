"""Focused bsb753 three-part source, guarded stage, notice, and rollback checks."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lxml import etree
import pytest

from build.tei.openmgh_bsb753_three_prose_oracle import check
from build.tools import install_openmgh_bsb753_three_prose as installer
from build.tools import prepare_openmgh_bsb753_three_prose as source
from ocd_kernel.library._common import PipelineError
from tests.openmgh_historical_fixture import historical_nested_installer_context
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path


ROOT = Path(__file__).resolve().parents[1]
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb753-three-prose-public-notices-20260928-v1")


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


def _example(work_id: str) -> tuple[bytes, bytes, dict, dict]:
    retained, tree, works = source._source()
    work = json.loads(_io_path(ROOT / "library/works" / work_id / "work.json").read_bytes())
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    acquisition_path = (ROOT / "library/works" / work_id / "forms" / form["textual_form_id"] /
                        "editions" / edition["edition_id"] / "acquisitions" /
                        f"{edition['acquisition_ids'][0]}.json")
    acquisition = json.loads(_io_path(acquisition_path).read_bytes())
    index, parts = source.SELECTIONS[work_id]
    return retained, source._candidate(tree, [works[index][part] for part in parts], work), work, acquisition


@pytest.mark.parametrize(("work_id", "index", "part"), [
    ("passio-desiderii-et-reginfridi", 2, 0),
    ("vita-sancti-ursmari", 11, 0),
    ("vita-sancti-erminonis", 11, 1),
])
def test_complete_native_part_and_read_only_preflight(work_id: str, index: int, part: int) -> None:
    retained, candidate, work, acquisition = _example(work_id)
    oracle = check(retained, candidate, work, acquisition)
    assert (oracle["source_work_div_index"], oracle["source_part_index"]) == (index, part)
    assert len(oracle["sibling_part_c14n_sha256"]) == 1
    assert installer.preflight(work_id)["status"] == "ready-for-review"


def test_oracle_rejects_hymn_substitution() -> None:
    work_id = "passio-desiderii-et-reginfridi"
    retained, candidate, work, acquisition = _example(work_id)
    _, _, works = source._source()
    tree = etree.fromstring(candidate)
    wrapper = tree.xpath("/t:TEI/t:text/t:body/t:div", namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0]
    wrapper.replace(wrapper[0], works[2][1])
    with pytest.raises(ValueError, match="complete native source part differs"):
        check(retained, etree.tostring(tree), work, acquisition)


def test_oracle_rejects_dropped_vita_page() -> None:
    work_id = "vita-sancti-ursmari"
    retained, candidate, work, acquisition = _example(work_id)
    tree = etree.fromstring(candidate)
    pages = tree.xpath("//t:pb", namespaces={"t": "http://www.tei-c.org/ns/1.0"})
    assert pages
    pages[0].getparent().remove(pages[0])
    with pytest.raises(ValueError, match="complete native source part differs"):
        check(retained, etree.tostring(tree), work, acquisition)


def test_freeze_pin_rejects_wrong_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "FREEZE_SHA", "0" * 64)
    with pytest.raises(PipelineError, match="reviewed freeze changed"):
        installer.preflight("vita-sancti-erminonis")


@pytest.mark.parametrize("work_id", sorted(source.SELECTIONS))
def test_future_visible_notice_binds_exact_source(work_id: str, tmp_path: Path) -> None:
    index = json.loads((HOME / "notice-index.json").read_bytes())
    item = next(record for record in index["items"] if record["work_id"] == work_id)
    for original, relative in ((ROOT / item["source_path"], item["source_path"]),
                               (HOME / item["notice_path"], item["notice_path"])):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    form = f"{work_id}-openmgh-retained"
    edition = f"{work_id}-openmgh-electronic"
    pin = next(record for record in installer._frozen()["works"] if record["work_id"] == work_id)
    acceptance_source = (Path(pin["stage_root"]) / "library/works" / work_id / "forms" /
                         form / "editions" / edition / "acceptance.json")
    acceptance = tmp_path / "acceptance.json"
    shutil.copy2(_io_path(acceptance_source), acceptance)
    binding = {key: item[key] for key in
               ("source_path", "source_sha256", "notice_path", "notice_sha256")}
    texts = notice_texts_for_item(tmp_path, {"work_id": work_id, "public_notices": [binding]}, acceptance)
    assert len(texts) == 1 and "Monumenta Germaniae Historica" in texts[0]
    assert "Bavarian State Library" in texts[0]
    (tmp_path / item["notice_path"]).write_text(texts[0] + "changed\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        notice_texts_for_item(tmp_path, {"work_id": work_id, "public_notices": [binding]}, acceptance)


def test_stock_transaction_rolls_back_after_new_live(tmp_path: Path) -> None:
    work_id = "vita-sancti-ursmari"
    root = tmp_path / "repo"
    target = root / "library/works" / work_id
    staged = tmp_path / "stage/library/works" / work_id
    target.mkdir(parents=True)
    staged.mkdir(parents=True)
    (target / "old.txt").write_text("before", encoding="utf-8")
    (staged / "new.txt").write_text("after", encoding="utf-8")
    before, after = _files(target), _files(staged)

    def fail_after_live(checkpoint: str) -> None:
        if checkpoint == "after-new-live":
            raise RuntimeError("injected bsb753 rollback")

    with pytest.raises(RuntimeError, match="injected bsb753 rollback"):
        _commit_generation(root, target, staged, work_id=work_id, before=before, after=after,
                           existed=True, replacement=False, operation_kind="openmgh-bsb753-fixture",
                           result_status="fixture", accepted_editions=1, fail_at=fail_after_live)
    assert _files(target) == before
    journals = list((root / ".tmp_audit").glob("accepted-install-*/operation.json"))
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
