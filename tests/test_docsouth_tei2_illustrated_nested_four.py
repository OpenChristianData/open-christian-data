"""Source/image fidelity seams for four illustrated DocSouth nested-quote works."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei import docsouth_tei2_illustrated_oracle as oracle
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[1]
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-nested-four-direct-20260927-v1")
STAGES = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-nested-four-stages-20260927-v2")
TEI = "{http://www.tei-c.org/ns/1.0}"
WORKS = (
    "amanda-smith-autobiography",
    "daniel-alexander-payne-recollections-seventy-years",
    "james-l-smith-autobiography",
    "levi-jenkins-coppin-unwritten-history",
)


def _pair(work_id: str) -> tuple[dict, bytes]:
    receipt = json.loads((DIRECT / "receipt.json").read_bytes())
    entry = next(item for item in receipt["selected_works"] if item["work_id"] == work_id)
    return entry, Path(entry["candidate_path"]).read_bytes()


def _check(entry: dict, candidate: bytes) -> dict:
    return oracle.check(ROOT / entry["source_path"], entry["source_sha256"], candidate,
                        ROOT / entry["acquisition_receipt_path"])


@pytest.mark.parametrize("work_id", WORKS)
def test_complete_candidate_matches_independent_source_image_oracle(work_id: str) -> None:
    entry, candidate = _pair(work_id)
    assert _check(entry, candidate) == entry["oracle"]
    assert entry["oracle"]["source_nested_text_count"] > 0
    assert entry["oracle"]["source_figure_count"] > 0


@pytest.mark.parametrize("work_id", WORKS)
def test_visible_stage_credit_names_source_roles_and_rights(work_id: str) -> None:
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
    work = json.loads(_io_path(stage / "library/works" / work_id / "work.json").read_bytes())
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    readme = (stage / "library/works" / work_id / "forms" / form["textual_form_id"]
              / "editions" / edition["edition_id"] / "README.source.md")
    assert _io_path(readme).read_text(encoding="utf-8") == credit


def test_nested_text_and_figure_url_mutations_are_rejected() -> None:
    entry, candidate = _pair(WORKS[2])
    tree = etree.fromstring(candidate)
    nested = tree.find(".//" + TEI + "floatingText")
    assert nested is not None
    nested.getparent().remove(nested)
    with pytest.raises(ValueError, match="nested-text"):
        _check(entry, etree.tostring(tree))

    tree = etree.fromstring(candidate)
    graphic = tree.find(".//" + TEI + "graphic")
    assert graphic is not None
    graphic.set("url", "https://docsouth.unc.edu/changed.jpg")
    with pytest.raises(ValueError, match="figure"):
        _check(entry, etree.tostring(tree))


def test_source_credit_and_jpeg_byte_mutations_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    entry, candidate = _pair(WORKS[1])
    tree = etree.fromstring(candidate)
    name = tree.find(".//" + TEI + "respStmt/" + TEI + "name")
    assert name is not None
    name.text = "Changed encoder"
    with pytest.raises(ValueError, match="credit"):
        _check(entry, etree.tostring(tree))

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
