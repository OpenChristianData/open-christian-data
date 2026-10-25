"""Focused source and image mutation seams for the illustrated DocSouth pilot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei import docsouth_tei2_illustrated_oracle as oracle


ROOT = Path(__file__).resolve().parents[1]
DIRECT = Path("D:/Library/Open Christian Data/candidate-reviews/docsouth-illustrated-direct-20260927-v7")
WORK = "g-w-offley-narrative-life-labors"
TEI = "{http://www.tei-c.org/ns/1.0}"


def _inputs() -> tuple[dict, bytes]:
    receipt = json.loads((DIRECT / "receipt.json").read_bytes())
    entry = next(item for item in receipt["selected_works"] if item["work_id"] == WORK)
    return entry, Path(entry["candidate_path"]).read_bytes()


def _check(entry: dict, candidate: bytes) -> dict:
    return oracle.check(ROOT / entry["source_path"], entry["source_sha256"], candidate,
                        ROOT / entry["acquisition_receipt_path"])


def test_exact_candidate_matches_independent_source_image_oracle() -> None:
    entry, candidate = _inputs()
    assert _check(entry, candidate) == entry["oracle"]


def test_graphic_url_and_header_credit_mutations_are_rejected() -> None:
    entry, candidate = _inputs()
    tree = etree.fromstring(candidate)
    graphic = tree.find(".//" + TEI + "graphic")
    assert graphic is not None
    graphic.set("url", "https://docsouth.unc.edu/neh/offley/not-source.jpg")
    with pytest.raises(ValueError, match="figure"):
        _check(entry, etree.tostring(tree))
    tree = etree.fromstring(candidate)
    name = tree.find(".//" + TEI + "respStmt/" + TEI + "name")
    assert name is not None
    name.text = "Wrong scanner"
    with pytest.raises(ValueError, match="credit"):
        _check(entry, etree.tostring(tree))


def test_one_byte_jpeg_mutation_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    entry, candidate = _inputs()
    image = ROOT / "raw/docsouth/l766-offley/offlecv.jpg"
    original = oracle._io_path

    class ChangedImage:
        def read_bytes(self) -> bytes:
            data = bytearray(original(image).read_bytes())
            data[100] ^= 1
            return bytes(data)

    def redirect(path: Path) -> Path | ChangedImage:
        return ChangedImage() if path == image else original(path)

    monkeypatch.setattr(oracle, "_io_path", redirect)
    with pytest.raises(ValueError, match="JPEG"):
        _check(entry, candidate)
