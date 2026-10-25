"""Focused Ansbert hymn source-part, stage guard, notice, and rollback checks."""

from __future__ import annotations

import json
from hashlib import sha256
import shutil
from pathlib import Path

from lxml import etree
import pytest

from build.tei.openmgh_bsb752_ansbert_hymn_oracle import check
from build.tools import install_openmgh_bsb752_ansbert_hymn as installer
from build.tools import prepare_openmgh_bsb752_nested as source
from ocd_kernel.library._common import PipelineError
from tests.openmgh_historical_fixture import _recover_generation
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path


ROOT = Path(__file__).resolve().parents[1]
WORK_ID = "ymnus-de-sancto-ansberto"
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb752-ansbert-hymn-public-notice-20260928-v3")


def _example() -> tuple[bytes, bytes, dict, dict]:
    retained, tree, works = source._source()
    work = json.loads(_io_path(ROOT / "library/works" / WORK_ID / "work.json").read_bytes())
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    acquisition_path = (ROOT / "library/works" / WORK_ID / "forms" / form["textual_form_id"] /
                        "editions" / edition["edition_id"] / "acquisitions" /
                        f"{edition['acquisition_ids'][0]}.json")
    acquisition = json.loads(_io_path(acquisition_path).read_bytes())
    return retained, source._candidate(tree, [works[19][2]], work), work, acquisition


def test_complete_part_oracle_and_read_only_preflight(historical_context: tuple[Path, Path, str], monkeypatch: pytest.MonkeyPatch) -> None:
    retained, candidate, work, acquisition = _example()
    result = check(retained, candidate, work, acquisition)
    assert (result["source_work_div_index"], result["source_part_index"]) == (19, 2)
    assert (result["source_lb_count"], result["source_pb_count"]) == (70, 2)
    assert len(result["excluded_sibling_part_c14n_sha256"]) == 2
    root, stage, digest = historical_context
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer, "STAGE", stage)
    monkeypatch.setattr(installer, "STAGE_RECEIPT_SHA", digest)
    assert installer.preflight()["status"] == "ready-for-review"


def test_oracle_rejects_dropped_hymn_page() -> None:
    retained, candidate, work, acquisition = _example()
    tree = etree.fromstring(candidate)
    pages = tree.xpath("/t:TEI/t:text/t:body/t:div/t:div/t:ab/t:pb",
                       namespaces={"t": "http://www.tei-c.org/ns/1.0"})
    assert len(pages) == 2
    pages[0].getparent().remove(pages[0])
    with pytest.raises(ValueError, match="complete native part differs"):
        check(retained, etree.tostring(tree), work, acquisition)


def test_oracle_rejects_sibling_substitution() -> None:
    retained, candidate, work, acquisition = _example()
    _, _, works = source._source()
    tree = etree.fromstring(candidate)
    wrapper = tree.xpath("/t:TEI/t:text/t:body/t:div", namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0]
    wrapper.replace(wrapper[0], works[19][1])
    with pytest.raises(ValueError, match="complete native part differs"):
        check(retained, etree.tostring(tree), work, acquisition)


def test_stage_pin_rejects_wrong_receipt_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "STAGE_RECEIPT_SHA", "0" * 64)
    with pytest.raises(PipelineError, match="receipt differs"):
        installer.preflight()


def test_future_visible_notice_binding(tmp_path: Path) -> None:
    index = json.loads((HOME / "notice-index.json").read_bytes())
    for original, relative in ((ROOT / index["source_path"], index["source_path"]),
                               (HOME / index["notice_path"], index["notice_path"])):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    acceptance_source = (installer.STAGE / "library/works" / WORK_ID / "forms" /
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


def test_stock_transaction_rolls_back_after_new_live(tmp_path: Path) -> None:
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
            raise RuntimeError("injected Ansbert rollback")

    with pytest.raises(RuntimeError, match="injected Ansbert rollback"):
        _commit_generation(
            root, target, staged, work_id=WORK_ID, before=before, after=after,
            existed=True, replacement=False, operation_kind="openmgh-bsb752-ansbert-fixture",
            result_status="fixture", accepted_editions=1, fail_at=fail_after_live,
        )
    assert _files(target) == before
    journals = list((root / ".tmp_audit").glob("accepted-install-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"


@pytest.fixture(scope="module")
def historical_context(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    raw = _io_path(installer.STAGE / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == installer.STAGE_RECEIPT_SHA
    original = json.loads(raw)
    assert original["work_id"] == WORK_ID
    home = tmp_path_factory.mktemp("ansbert-historical")
    root, stage = home / "root", home / "stage"
    root.mkdir()
    shutil.copytree(_io_path(installer.STAGE), _io_path(stage))
    _recover_generation(installer.STAGE, root, WORK_ID, original["before"], category="poetry", language="la")
    prefix = "library/works/" + WORK_ID + "/"
    for relative in _files(installer.STAGE):
        if relative == "stage-receipt.json" or relative.startswith(prefix):
            continue
        target = _io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_io_path(installer.STAGE / relative).read_bytes())
    context = dict(original, canonical_root=root.as_posix(), stage_root=stage.as_posix())
    restored = dict(context, canonical_root=original["canonical_root"], stage_root=original["stage_root"])
    assert restored == original
    payload = (json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (stage / "stage-receipt.json").write_bytes(payload)
    assert _files(root / "library/works" / WORK_ID) == original["before"]
    assert _files(stage / "library/works" / WORK_ID) == original["after"]
    return root, stage, sha256(payload).hexdigest()


def test_original_preflight_rejects_wrong_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrong = tmp_path / "wrong-ansbert-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="Ansbert exact stage scope differs"):
        installer.preflight()
