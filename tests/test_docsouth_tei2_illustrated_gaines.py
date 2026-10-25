"""Source, grid, image, and stage fidelity seams for Gaines's table witness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei import docsouth_tei2_illustrated_gaines_oracle as oracle
from build.tools import install_docsouth_tei2_illustrated_gaines as installer
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.library._common import PipelineError
from tests.openmgh_historical_fixture import historical_docsouth_context


ROOT = Path(__file__).resolve().parents[1]
WORK_ID = "w-j-gaines-negro-and-white-man"
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-gaines-direct-20260927-v2")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-gaines-stages-20260927-v2") / WORK_ID
TEI = "{http://www.tei-c.org/ns/1.0}"


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
    monkeypatch.setattr(installer.source, "ROOT", root)
    monkeypatch.setattr(installer.freezing, "FREEZE", freeze)
    monkeypatch.setattr(installer, "FREEZE_SHA", digest)


def _pair() -> tuple[dict, bytes]:
    receipt = json.loads(_io_path(DIRECT / "receipt.json").read_bytes())
    entry = receipt["selected_works"][0]
    assert entry["work_id"] == WORK_ID
    return entry, _io_path(Path(entry["candidate_path"])).read_bytes()


def _check(entry: dict, candidate: bytes) -> dict:
    return oracle.check(ROOT / entry["source_path"], entry["source_sha256"], candidate,
                        ROOT / entry["acquisition_receipt_path"])


def test_complete_table_image_oracle_and_frozen_read_only_installer() -> None:
    entry, candidate = _pair()
    report = _check(entry, candidate)
    assert report == entry["oracle"]
    assert (report["source_table_count"], report["source_row_count"], report["source_cell_count"]) == (1, 49, 441)
    assert report["source_figure_count"] == len(report["source_images"]) == 3
    assert installer.preflight(WORK_ID)["installation"] == "not-performed"


def test_grid_roles_spans_and_mixed_cell_children_are_source_bound() -> None:
    entry, candidate = _pair()
    tree = etree.fromstring(candidate)
    table = tree.find(".//" + TEI + "table")
    assert table is not None
    rows = table.findall(TEI + "row")
    assert len(rows) == 49 and all(len(row.findall(TEI + "cell")) == 9 for row in rows)
    assert len(table.findall(".//" + TEI + "cell")) == 441
    first = rows[0]
    assert first.get("ana") == "source-role-label"
    first.set("ana", "source-role-data")
    with pytest.raises(ValueError, match="unit attributes"):
        _check(entry, etree.tostring(tree))

    tree = etree.fromstring(candidate)
    first_cell = tree.find(".//" + TEI + "cell")
    assert first_cell is not None
    assert first_cell.get("rend") == "source-rows-1" and first_cell.get("cols") == "1"
    first_cell.set("rend", "source-rows-2")
    with pytest.raises(ValueError, match="unit attributes"):
        _check(entry, etree.tostring(tree))

    tree = etree.fromstring(candidate)
    mixed = next(cell for cell in tree.findall(".//" + TEI + "cell") if len(cell))
    assert [child.tag for child in mixed] == [TEI + "ref", TEI + "note"]
    mixed.remove(mixed[-1])
    with pytest.raises(ValueError, match="structure/text"):
        _check(entry, etree.tostring(tree))


def test_source_title_markup_and_visible_credit_are_retained() -> None:
    entry, candidate = _pair()
    source = etree.fromstring(_io_path(ROOT / entry["source_path"]).read_bytes())
    credit = _io_path(STAGE / "library/works" / WORK_ID / "SOURCE_CREDIT.md").read_text(encoding="utf-8")
    for statement in source.findall("teiHeader/fileDesc/titleStmt/respStmt"):
        role = " ".join("".join(statement.find("resp").itertext()).split())
        name = " ".join("".join(statement.find("name").itertext()).split())
        assert f"- {role}: {name}" in credit
    funder = " ".join("".join(source.find("teiHeader/fileDesc/titleStmt/funder").itertext()).split())
    assert f"- Funding: {funder}" in credit
    availability = " ".join("".join(source.find("teiHeader/fileDesc/publicationStmt/availability").itertext()).split())
    assert availability in credit

    tree = etree.fromstring(candidate)
    title = tree.find(".//" + TEI + "note[@type='source-electronic-title-markup']")
    assert title is not None and "<emph" in title.text
    title.text = title.text.replace("<emph", "<changed")
    with pytest.raises(ValueError, match="title markup"):
        _check(entry, etree.tostring(tree))


def test_exact_retained_jpeg_byte_mutation_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    entry, candidate = _pair()
    image_path = ROOT / next(iter(entry["oracle"]["source_images"].values()))["path"]
    original_io = oracle._io_path

    class ChangedImage:
        def read_bytes(self) -> bytes:
            data = bytearray(original_io(image_path).read_bytes())
            data[100] ^= 1
            return bytes(data)

    def redirect(path: Path) -> Path | ChangedImage:
        return ChangedImage() if path == image_path else original_io(path)

    monkeypatch.setattr(oracle, "_io_path", redirect)
    with pytest.raises(ValueError, match="JPEG"):
        _check(entry, candidate)


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
