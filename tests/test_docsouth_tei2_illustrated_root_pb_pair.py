"""Source/image fidelity seams for Green and Robinson's root page breaks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei import docsouth_tei2_illustrated_root_pb_pair_oracle as oracle
from build.tools import install_docsouth_tei2_illustrated_root_pb_pair as installer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _io_path
from tests.openmgh_historical_fixture import historical_docsouth_context


ROOT = Path(__file__).resolve().parents[1]
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-root-pb-pair-direct-20260927-v3")
STAGES = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-root-pb-pair-stages-20260927-v2")
TEI = "{http://www.tei-c.org/ns/1.0}"
WORKS = ("wharton-jackson-green-recollections-and-reflections",
         "william-h-robinson-from-log-cabin-to-pulpit")


INPUT_ROOT = installer.ROOT


@pytest.fixture(scope="module")
def historical_context(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    return historical_docsouth_context(
        INPUT_ROOT, tmp_path_factory.mktemp("docsouth-historical"), installer.freezing.FREEZE,
        installer.FREEZE_SHA,
    )


@pytest.fixture(autouse=True)
def isolated_historical_installer(monkeypatch: pytest.MonkeyPatch, historical_context: tuple[Path, Path, str]) -> None:
    root, freeze, digest = historical_context
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer.source, "ROOT", root)
    monkeypatch.setattr(installer.freezing, "FREEZE", freeze)
    monkeypatch.setattr(installer, "FREEZE_SHA", digest)


def _pair(work_id: str) -> tuple[dict, bytes]:
    receipt = json.loads(_io_path(DIRECT / "receipt.json").read_bytes())
    entry = next(item for item in receipt["selected_works"] if item["work_id"] == work_id)
    return entry, _io_path(Path(entry["candidate_path"])).read_bytes()


def _check(entry: dict, candidate: bytes) -> dict:
    return oracle.check(ROOT / entry["source_path"], entry["source_sha256"], candidate,
                        ROOT / entry["acquisition_receipt_path"])


@pytest.mark.parametrize("work_id,figures,boundaries", ((WORKS[0], 11, 2), (WORKS[1], 16, 1)))
def test_complete_source_and_image_oracle_and_read_only_installer(
        work_id: str, figures: int, boundaries: int) -> None:
    entry, candidate = _pair(work_id)
    report = _check(entry, candidate)
    assert report == entry["oracle"]
    assert report["source_figure_count"] == figures
    assert report["root_page_break_count"] == boundaries
    assert report["back_text_sha256"] == entry["producer"]["source_back_text_sha256"]
    assert installer.preflight(work_id)["installation"] == "not-performed"


@pytest.mark.parametrize("work_id", WORKS)
def test_visible_credit_preserves_source_roles_funding_when_present_and_rights(work_id: str) -> None:
    entry, _ = _pair(work_id)
    source = etree.fromstring(_io_path(ROOT / entry["source_path"]).read_bytes())
    credit = _io_path(STAGES / work_id / "library/works" / work_id / "SOURCE_CREDIT.md").read_text(encoding="utf-8")
    for statement in source.findall("teiHeader/fileDesc/titleStmt/respStmt"):
        role = " ".join("".join(statement.find("resp").itertext()).split())
        name = " ".join("".join(statement.find("name").itertext()).split())
        assert f"- {role}: {name}" in credit
    funder = source.find("teiHeader/fileDesc/titleStmt/funder")
    if funder is None:
        assert "- Funding:" not in credit
    else:
        assert f"- Funding: {' '.join(''.join(funder.itertext()).split())}" in credit
    availability = " ".join("".join(source.find("teiHeader/fileDesc/publicationStmt/availability").itertext()).split())
    assert availability in credit


@pytest.mark.parametrize("work_id", WORKS)
def test_root_page_break_carrier_mutation_is_rejected(work_id: str) -> None:
    entry, candidate = _pair(work_id)
    tree = etree.fromstring(candidate)
    boundary = tree.find(".//" + TEI + "text/" + TEI + "front/" + TEI + "pb[@rend='source-text-boundary-after-front']")
    assert boundary is not None
    boundary.set("rend", "source-text-boundary-after-body")
    with pytest.raises(ValueError, match="root page-break carrier"):
        _check(entry, etree.tostring(tree))


def test_green_title_markup_and_literal_certainty_are_source_bound() -> None:
    entry, candidate = _pair(WORKS[0])
    tree = etree.fromstring(candidate)
    markup = tree.find(".//" + TEI + "note[@type='source-electronic-title-markup']")
    assert markup is not None
    markup.text = markup.text.replace('rend="bold"', 'rend="italic"')
    with pytest.raises(ValueError, match="title emphasis reading"):
        _check(entry, etree.tostring(tree))

    tree = etree.fromstring(candidate)
    certainty = tree.find(".//" + TEI + "seg[@rend='source-cert-colassal']")
    assert certainty is not None
    certainty.set("rend", "source-cert-changed")
    with pytest.raises(ValueError, match="unpaired correction carrier"):
        _check(entry, etree.tostring(tree))


def test_robinson_title_page_byline_carrier_is_source_bound() -> None:
    entry, candidate = _pair(WORKS[1])
    tree = etree.fromstring(candidate)
    byline = tree.find(".//" + TEI + "p[@rend='source-byline']")
    assert byline is not None
    byline.set("rend", "changed")
    with pytest.raises(ValueError, match="unit attributes"):
        _check(entry, etree.tostring(tree))


def test_exact_retained_jpeg_byte_mutation_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    entry, candidate = _pair(WORKS[1])
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
