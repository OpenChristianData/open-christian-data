"""Source fidelity seams for two illustrated DocSouth front/body/back works."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei import docsouth_tei2_illustrated_back_pair_oracle as oracle
from build.tools import install_docsouth_tei2_illustrated_back_pair as installer
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.library._common import PipelineError
from tests.openmgh_historical_fixture import historical_docsouth_context, historical_docsouth_source_note


ROOT = Path(__file__).resolve().parents[1]
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-back-pair-direct-20260927-v2")
STAGES = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-back-pair-stages-20260927-v2")
TEI = "{http://www.tei-c.org/ns/1.0}"
WORKS = ("sojourner-truth-narrative-1875", "thomas-l-johnson-twenty-eight-years-a-slave")


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


def _pair(work_id: str) -> tuple[dict, bytes]:
    receipt = json.loads(_io_path(DIRECT / "receipt.json").read_bytes())
    entry = next(item for item in receipt["selected_works"] if item["work_id"] == work_id)
    return entry, _io_path(Path(entry["candidate_path"])).read_bytes()


def _check(entry: dict, candidate: bytes) -> dict:
    return oracle.check(ROOT / entry["source_path"], entry["source_sha256"], candidate,
                        ROOT / entry["acquisition_receipt_path"])


@pytest.mark.parametrize("work_id", WORKS)
def test_candidate_matches_independent_source_image_oracle_and_read_only_installer(work_id: str) -> None:
    entry, candidate = _pair(work_id)
    assert _check(entry, candidate) == entry["oracle"]
    assert entry["oracle"]["back_text_sha256"] == entry["producer"]["source_back_text_sha256"]
    assert entry["oracle"]["source_figure_count"] == (8 if work_id == WORKS[0] else 55)
    assert installer.preflight(work_id)["installation"] == "not-performed"


@pytest.mark.parametrize("work_id", WORKS)
def test_visible_source_credit_preserves_roles_funder_and_rights(work_id: str) -> None:
    entry, _ = _pair(work_id)
    source = etree.fromstring(_io_path(ROOT / entry["source_path"]).read_bytes())
    stage = STAGES / work_id
    credit = _io_path(stage / "library/works" / work_id / "SOURCE_CREDIT.md").read_text(encoding="utf-8")
    for statement in source.findall("teiHeader/fileDesc/titleStmt/respStmt"):
        role = " ".join("".join(statement.find("resp").itertext()).split())
        name = " ".join("".join(statement.find("name").itertext()).split())
        assert f"- {role}: {name}" in credit
    funder = " ".join("".join(source.find("teiHeader/fileDesc/titleStmt/funder").itertext()).split())
    assert f"- Funding: {funder}" in credit
    availability = " ".join("".join(source.find("teiHeader/fileDesc/publicationStmt/availability").itertext()).split())
    assert availability in credit


def test_back_and_secondary_print_title_mutations_are_rejected() -> None:
    entry, candidate = _pair(WORKS[0])
    tree = etree.fromstring(candidate)
    back = tree.find(".//" + TEI + "text/" + TEI + "back")
    assert back is not None
    back.getparent().remove(back)
    with pytest.raises(ValueError, match="text part ownership"):
        _check(entry, etree.tostring(tree))

    tree = etree.fromstring(candidate)
    print_titles = tree.findall(".//" + TEI + "sourceDesc/" + TEI + "biblFull/" + TEI + "titleStmt/" + TEI + "title")
    assert len(print_titles) == 2
    print_titles[1].text = "Changed half title"
    with pytest.raises(ValueError, match="print title sequence"):
        _check(entry, etree.tostring(tree))


def test_thomas_legacy_carriers_are_source_bound() -> None:
    entry, candidate = _pair(WORKS[1])
    tree = etree.fromstring(candidate)
    ref = next(item for item in tree.findall(".//" + TEI + "ref") if item.get("rend") == "source-lang-john5")
    ref.set("rend", "source-lang-john6")
    with pytest.raises(ValueError, match="unit attributes"):
        _check(entry, etree.tostring(tree))

    tree = etree.fromstring(candidate)
    pb = next(item for item in tree.findall(".//" + TEI + "pb") if item.get("rend") == "source-single-space")
    pb.set("rend", "source-two-spaces")
    with pytest.raises(ValueError, match="unit attributes"):
        _check(entry, etree.tostring(tree))

    tree = etree.fromstring(candidate)
    epigraph = next(item for item in tree.findall(".//" + TEI + "lg") if item.get("rend") == "source-epigraph")
    epigraph.set("rend", "changed")
    with pytest.raises(ValueError, match="unit attributes"):
        _check(entry, etree.tostring(tree))


def test_exact_jpeg_byte_mutation_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
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
