"""Focused bsb830 bsb830 residual-part source, guarded stage, and notice checks."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lxml import etree
import pytest

from build.tei.openmgh_bsb830_residual_parts_oracle import check
from build.tools import install_openmgh_bsb830_residual_parts as installer
from build.tools import prepare_openmgh_bsb830_residual_parts as source
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _io_path
from tests.openmgh_historical_fixture import historical_nested_installer_context


ROOT = Path(__file__).resolve().parents[1]
HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb830-residual-parts-public-notices-20260928-v1")


INPUT_ROOT = installer.ROOT


@pytest.fixture(scope="module")
def historical_context(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    return historical_nested_installer_context(
        INPUT_ROOT, tmp_path_factory.mktemp("mgh-historical"), installer.FREEZE,
        installer.FREEZE_SHA, ((source.SOURCE, source.SOURCE_SHA),
        (source.PACKAGE, source.PACKAGE_SHA), (source.ACQUISITION_RECEIPT, source.ACQUISITION_RECEIPT_SHA)),
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


@pytest.mark.parametrize(("work_id", "part", "sections"), [
    ("anonymous-priest-letter-to-innocent-on-secular-and-regular-clergy", 1, 0),
    ("gerhoh-commentary-on-psalms", 9, 17),
])
def test_complete_native_part_and_read_only_preflight(work_id: str, part: int, sections: int) -> None:
    retained, candidate, work, acquisition = _example(work_id)
    oracle = check(retained, candidate, work, acquisition)
    assert (oracle["source_work_div_index"], oracle["source_part_index"]) == (6, part)
    assert oracle["source_section_count"] == sections and oracle["sibling_part_count"] == 10
    assert installer.preflight(work_id)["status"] == "ready-for-review"


def test_oracle_rejects_sibling_substitution() -> None:
    work_id = "anonymous-priest-letter-to-innocent-on-secular-and-regular-clergy"
    retained, candidate, work, acquisition = _example(work_id)
    _, _, works = source._source()
    tree = etree.fromstring(candidate)
    wrapper = tree.xpath("/t:TEI/t:text/t:body/t:div", namespaces={"t": "http://www.tei-c.org/ns/1.0"})[0]
    wrapper.replace(wrapper[0], works[6][9])
    with pytest.raises(ValueError, match="complete native Gerhoh source part differs"):
        check(retained, etree.tostring(tree), work, acquisition)


def test_oracle_rejects_dropped_internal_page() -> None:
    work_id = "gerhoh-commentary-on-psalms"
    retained, candidate, work, acquisition = _example(work_id)
    tree = etree.fromstring(candidate)
    pages = tree.xpath("//t:pb", namespaces={"t": "http://www.tei-c.org/ns/1.0"})
    assert len(pages) > 1
    pages[1].getparent().remove(pages[1])
    with pytest.raises(ValueError, match="complete native Gerhoh source part differs"):
        check(retained, etree.tostring(tree), work, acquisition)


def test_freeze_pin_rejects_wrong_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "FREEZE_SHA", "0" * 64)
    with pytest.raises(PipelineError, match="reviewed freeze changed"):
        installer.preflight("anonymous-priest-letter-to-innocent-on-secular-and-regular-clergy")


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



def test_original_guard_rejects_wrong_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="freeze scope or authority differs"):
        installer._frozen()
