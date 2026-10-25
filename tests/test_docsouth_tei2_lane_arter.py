"""Focused fidelity checks for the distinct Lane and Arter DocSouth witnesses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei import docsouth_tei2_lane_arter_oracle as oracle


ROOT = Path(__file__).resolve().parents[1]
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-lane-arter-direct-20260927-v9")
TEI = "{http://www.tei-c.org/ns/1.0}"
WORKS = ("isaac-lane-autobiography", "jared-maurice-arter-echoes-from-pioneer-life")


def _pair(work_id: str) -> tuple[dict, bytes]:
    receipt = json.loads((DIRECT / "receipt.json").read_bytes())
    entry = next(item for item in receipt["selected_works"] if item["work_id"] == work_id)
    return entry, Path(entry["candidate_path"]).read_bytes()


def _check(entry: dict, candidate: bytes) -> dict:
    return oracle.check(ROOT / entry["source_path"], entry["source_sha256"], candidate,
                        ROOT / entry["acquisition_receipt_path"])


@pytest.mark.parametrize("work_id", WORKS)
def test_exact_source_image_and_header_oracle(work_id: str) -> None:
    entry, candidate = _pair(work_id)
    assert _check(entry, candidate) == entry["oracle"]
    assert entry["oracle"]["source_figure_count"] == (23 if work_id == WORKS[0] else 16)


def test_arter_typography_marker_mutations_are_rejected() -> None:
    entry, candidate = _pair(WORKS[1])
    assert entry["oracle"]["typography_milestone_count"] == 4
    tree = etree.fromstring(candidate)
    markers = tree.findall(".//" + TEI + "seg[@type='source-milestone']")
    assert len(markers) == 4
    markers[0].set("n", "* *")
    with pytest.raises(ValueError, match="typography milestone"):
        _check(entry, etree.tostring(tree))
    tree = etree.fromstring(candidate)
    marker = tree.find(".//" + TEI + "seg[@type='source-milestone']")
    assert marker is not None
    marker.getparent().remove(marker)
    with pytest.raises(ValueError, match="structure/text differs"):
        _check(entry, etree.tostring(tree))


def test_print_bibl_and_figure_binding_mutations_are_rejected() -> None:
    entry, candidate = _pair(WORKS[0])
    tree = etree.fromstring(candidate)
    title = tree.find(".//" + TEI + "sourceDesc/" + TEI + "biblFull/" + TEI + "titleStmt/" + TEI + "title")
    assert title is not None
    title.text = "Changed print title"
    with pytest.raises(ValueError, match="print title"):
        _check(entry, etree.tostring(tree))
    tree = etree.fromstring(candidate)
    graphic = tree.find(".//" + TEI + "graphic")
    assert graphic is not None
    graphic.set("url", "https://docsouth.unc.edu/changed.jpg")
    with pytest.raises(ValueError, match="figure"):
        _check(entry, etree.tostring(tree))


def test_source_credit_id_and_jpeg_byte_mutations_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    entry, candidate = _pair(WORKS[1])
    tree = etree.fromstring(candidate)
    name = tree.find(".//" + TEI + "respStmt/" + TEI + "name[@key='source-id-cg']")
    assert name is not None
    name.set("key", "source-id-wrong")
    with pytest.raises(ValueError, match="responsibility identifiers"):
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
