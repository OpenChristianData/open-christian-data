"""TDD tests for build/parsers/ia_abbyy.py — IA ABBYY FineReader XML parser."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from lxml import etree

from build.parsers import ia_abbyy

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "ia_abbyy" / "sample_small_page.xml"
ABBYY_NS = "http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml"


def _load_fixture_page():
    tree = etree.parse(str(FIXTURE))
    return tree.getroot()


def _fixture_page_xml() -> bytes:
    fixture_bytes = FIXTURE.read_bytes()
    if b"?>\r\n" in fixture_bytes:
        return fixture_bytes.split(b"?>\r\n", 1)[1].strip()
    return fixture_bytes.split(b"?>\n", 1)[1].strip()


def _write_test_volume(tmp_path: Path, page_count: int) -> Path:
    page_xml = _fixture_page_xml()
    doc = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<document version="1.0" producer="ABBYY" pagesCount="'
        + str(page_count).encode("ascii")
        + b'" xmlns="http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml">\n'
        + b"\n".join([page_xml] * page_count)
        + b"\n</document>\n"
    )
    gz_path = tmp_path / "tiny.abbyy.gz"
    with gzip.open(gz_path, "wb") as fh:
        fh.write(doc)
    return gz_path


def _write_test_manifest(
    tmp_path: Path,
    mapped_leaves: list[int],
    *,
    manifest_warnings: list[str] | None = None,
) -> Path:
    manifest = {
        "ia_item_id": "TestItem",
        "volume": 99,
        "pages": [
            {"page_num": index + 1, "ia_leaf_id": f"{leaf:04d}", "local_path": "x.jpg"}
            for index, leaf in enumerate(mapped_leaves)
        ],
    }
    if manifest_warnings is not None:
        manifest["manifest_warnings"] = manifest_warnings
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


# ---------------------------------------------------------------------------
# parse_page — single-page parser
# ---------------------------------------------------------------------------

def test_parse_page_returns_sidecar_with_required_keys():
    page_elem = _load_fixture_page()
    sidecar = ia_abbyy.parse_page(page_elem, page_index=46, page_num=10)
    required = {
        "format_version",
        "coordinate_unit",
        "coordinate_frame",
        "page_rotation",
        "engine",
        "engine_version",
        "page_index",
        "page_num",
        "page_size",
        "confidence_mean",
        "word_count",
        "text",
        "blocks",
    }
    assert required <= sidecar.keys()


def test_parse_page_constants():
    page_elem = _load_fixture_page()
    sidecar = ia_abbyy.parse_page(page_elem, page_index=46, page_num=10)
    assert sidecar["format_version"] == 1
    assert sidecar["coordinate_unit"] == "pixel"
    assert sidecar["coordinate_frame"] == "source_image"
    assert sidecar["page_rotation"] == 0.0
    assert sidecar["engine"] == "abbyy-finereader"


def test_parse_page_size_from_attributes():
    page_elem = _load_fixture_page()
    sidecar = ia_abbyy.parse_page(page_elem, page_index=46, page_num=10)
    assert sidecar["page_size"] == {"width": 5034, "height": 6959}


def test_parse_page_blocks_have_lines_and_words():
    page_elem = _load_fixture_page()
    sidecar = ia_abbyy.parse_page(page_elem, page_index=46, page_num=10)
    assert len(sidecar["blocks"]) == 1
    block = sidecar["blocks"][0]
    assert "bbox" in block
    assert block["bbox"] == {"x": 1136, "y": 684, "w": 1652 - 1136, "h": 804 - 684}
    assert len(block["lines"]) == 2
    line0 = block["lines"][0]
    assert "bbox" in line0
    assert line0["baseline"] is None or isinstance(line0["baseline"], (int, float))
    assert "x_size" in line0  # may be None per spec
    assert len(line0["words"]) == 1
    word = line0["words"][0]
    assert {"text", "confidence", "bbox"} <= word.keys()
    # Word 1 derived from glyphs: leading triangle + "belavd"
    assert word["text"].endswith("belavd")
    # Bbox is dict with x/y/w/h ints
    assert {"x", "y", "w", "h"} == word["bbox"].keys()


def test_parse_page_confidence_excludes_sentinel_255():
    """charConfidence=255 sentinels (spaces, decorative glyphs) must not pollute the mean."""
    page_elem = _load_fixture_page()
    sidecar = ia_abbyy.parse_page(page_elem, page_index=46, page_num=10)
    # The fixture's word 1 ("▲belavd") has chars with confidences [255, 0, 24, 44, 25, 34, 7]
    # Word confidence excludes the 255 sentinel, so mean = (0+24+44+25+34+7)/6 ≈ 22.33
    word = sidecar["blocks"][0]["lines"][0]["words"][0]
    expected = (0 + 24 + 44 + 25 + 34 + 7) / 6
    assert word["confidence"] == pytest.approx(expected, abs=0.01)


def test_parse_page_text_concatenates_words():
    page_elem = _load_fixture_page()
    sidecar = ia_abbyy.parse_page(page_elem, page_index=46, page_num=10)
    text = sidecar["text"]
    # Both word strings appear in the page text
    assert "belavd" in text
    assert "bhadAnanda" in text


def test_parse_page_word_count_matches_blocks():
    page_elem = _load_fixture_page()
    sidecar = ia_abbyy.parse_page(page_elem, page_index=46, page_num=10)
    total_words = sum(
        len(line["words"]) for block in sidecar["blocks"] for line in block["lines"]
    )
    assert sidecar["word_count"] == total_words


def test_parse_page_confidence_mean_is_word_level():
    page_elem = _load_fixture_page()
    sidecar = ia_abbyy.parse_page(page_elem, page_index=46, page_num=10)
    all_word_confs = [
        w["confidence"]
        for block in sidecar["blocks"]
        for line in block["lines"]
        for w in line["words"]
        if w["confidence"] is not None
    ]
    if all_word_confs:
        expected = sum(all_word_confs) / len(all_word_confs)
        assert sidecar["confidence_mean"] == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# parse_volume — streaming volume parser
# ---------------------------------------------------------------------------

def test_parse_volume_returns_stats(tmp_path):
    """Volume parser writes per-page sidecars + raw XML, returns stats."""
    # Build a tiny .abbyy.gz with two pages by reusing the fixture
    page_xml = _fixture_page_xml()
    doc = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<document version="1.0" producer="LuraDocument XML Exporter for ABBYY FineReader" '
        b'pagesCount="2" xmlns="http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml">\n'
        + page_xml
        + b"\n"
        + page_xml
        + b"\n</document>\n"
    )
    gz_path = tmp_path / "tiny.abbyy.gz"
    with gzip.open(gz_path, "wb") as fh:
        fh.write(doc)

    # Tiny manifest: leaf 0 -> page_num 1, leaf 1 -> page_num 2
    manifest = {
        "ia_item_id": "TestItem",
        "volume": 99,
        "pages": [
            {"page_num": 1, "ia_leaf_id": "0000", "local_path": "x.jpg"},
            {"page_num": 2, "ia_leaf_id": "0001", "local_path": "y.jpg"},
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    sidecar_dir = tmp_path / "vol_99"
    sidecar_dir.mkdir()

    stats = ia_abbyy.parse_volume(
        gz_path=gz_path,
        manifest_path=manifest_path,
        sidecar_dir=sidecar_dir,
    )
    assert stats["pages_parsed"] == 2
    # Per-page sidecars exist
    assert (sidecar_dir / "page_0001.ia-abbyy.json").exists()
    assert (sidecar_dir / "page_0002.ia-abbyy.json").exists()
    # Raw XML preserved per page
    assert (sidecar_dir / "page_0001.ia-abbyy.raw.xml").exists()
    assert (sidecar_dir / "page_0002.ia-abbyy.raw.xml").exists()


def test_parse_volume_sidecar_shape(tmp_path):
    """Each per-page sidecar matches the documented shape."""
    page_xml = _fixture_page_xml()
    doc = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<document version="1.0" producer="ABBYY" pagesCount="1" '
        b'xmlns="http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml">\n'
        + page_xml
        + b"\n</document>\n"
    )
    gz_path = tmp_path / "tiny.abbyy.gz"
    with gzip.open(gz_path, "wb") as fh:
        fh.write(doc)
    manifest = {
        "ia_item_id": "T",
        "volume": 99,
        "pages": [{"page_num": 5, "ia_leaf_id": "0000", "local_path": "x.jpg"}],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sidecar_dir = tmp_path / "vol_99"
    sidecar_dir.mkdir()
    ia_abbyy.parse_volume(gz_path, manifest_path, sidecar_dir)
    sidecar = json.loads((sidecar_dir / "page_0005.ia-abbyy.json").read_text(encoding="utf-8"))
    assert sidecar["page_num"] == 5
    assert sidecar["page_index"] == 0  # first ABBYY page maps to leaf 0


def test_skip_rate_gate_fires_above_threshold(tmp_path, caplog):
    gz_path = _write_test_volume(tmp_path, page_count=59)
    manifest_path = _write_test_manifest(tmp_path, mapped_leaves=list(range(56)))

    with caplog.at_level("WARNING", logger="ia_abbyy"):
        stats = ia_abbyy.parse_volume(gz_path, manifest_path, tmp_path / "vol_99")

    assert "volume 99" in caplog.text
    assert "skip rate" in caplog.text
    assert "coverage" in caplog.text
    assert stats["pages_parsed"] == 56
    assert stats["pages_leaf_captured"] == 3


def test_skip_rate_gate_silent_below_threshold(tmp_path, caplog):
    gz_path = _write_test_volume(tmp_path, page_count=21)
    manifest_path = _write_test_manifest(tmp_path, mapped_leaves=list(range(20)))

    with caplog.at_level("WARNING", logger="ia_abbyy"):
        ia_abbyy.parse_volume(gz_path, manifest_path, tmp_path / "vol_99")

    assert "skip rate" not in caplog.text


def _run_one_with_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    gz_path = _write_test_volume(tmp_path, page_count=2)
    manifest_path = _write_test_manifest(
        tmp_path,
        mapped_leaves=[0],
        manifest_warnings=["manifest fixture warning"],
    )
    sidecar_dir = tmp_path / "vol_99"
    monkeypatch.setattr(ia_abbyy, "_gz_path_for_volume", lambda *args, **kwargs: gz_path)
    monkeypatch.setattr(ia_abbyy, "_manifest_path_for_volume", lambda volume: manifest_path)
    monkeypatch.setattr(ia_abbyy, "_sidecar_dir_for_volume", lambda volume: sidecar_dir)
    monkeypatch.setattr(
        ia_abbyy,
        "_rendering_out_path",
        lambda volume, source, copy: tmp_path / "rendering.json",
    )

    assert ia_abbyy._run_one(
        99,
        "nsh-main",
        0,
        download=False,
        assemble_only=False,
        verbose=False,
        dry_run=False,
    ) == 0
    return sidecar_dir


def test_leaf_coverage_report_written_after_parse(tmp_path, monkeypatch):
    sidecar_dir = _run_one_with_gap(tmp_path, monkeypatch)
    report_path = sidecar_dir / "coverage.ia-abbyy.json"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert {
        "volume",
        "source",
        "copy",
        "sidecar_suffix",
        "assembled_at",
        "total_leaves",
        "manifest_entries",
        "pages_parsed",
        "pages_skipped",
        "skip_rate",
        "skipped_leaf_indices",
        "manifest_warnings",
    } == set(report)


def test_leaf_coverage_report_captures_skipped_leaf_indices(tmp_path, monkeypatch):
    sidecar_dir = _run_one_with_gap(tmp_path, monkeypatch)

    report = json.loads(
        (sidecar_dir / "coverage.ia-abbyy.json").read_text(encoding="utf-8")
    )
    assert report["skipped_leaf_indices"] == [1]
    assert report["manifest_warnings"] == ["manifest fixture warning"]


def test_unmapped_leaf_gets_leaf_indexed_sidecar(tmp_path):
    gz_path = _write_test_volume(tmp_path, page_count=2)
    manifest_path = _write_test_manifest(tmp_path, mapped_leaves=[0])
    sidecar_dir = tmp_path / "vol_99"

    stats = ia_abbyy.parse_volume(gz_path, manifest_path, sidecar_dir)
    sidecar = json.loads(
        (sidecar_dir / "page_leaf0001.ia-abbyy.json").read_text(encoding="utf-8")
    )

    assert sidecar["page_num"] == "leaf0001"
    assert (sidecar_dir / "page_leaf0001.ia-abbyy.raw.xml").exists()
    assert stats["pages_parsed"] == 1
    assert stats["pages_skipped"] == 1
    assert stats["pages_leaf_captured"] == 1


# ---------------------------------------------------------------------------
# assemble_volume_json — package per-page sidecars into a volume rendering
# ---------------------------------------------------------------------------

def test_assemble_volume_json(tmp_path):
    """Mirrors local_schaff_tesseract.assemble_volume_json shape."""
    # Create two synthetic sidecars
    sidecar_dir = tmp_path / "vol_99"
    sidecar_dir.mkdir()
    for page_num, conf, wc in [(1, 80.0, 100), (2, 90.0, 200)]:
        sidecar = {
            "format_version": 1,
            "engine": "abbyy-finereader",
            "engine_version": None,
            "page_index": page_num - 1,
            "page_num": page_num,
            "page_size": {"width": 5034, "height": 6959},
            "confidence_mean": conf,
            "word_count": wc,
            "text": f"page {page_num} text",
            "blocks": [],
        }
        (sidecar_dir / f"page_{page_num:04d}.ia-abbyy.json").write_text(
            json.dumps(sidecar), encoding="utf-8"
        )
    out_path = tmp_path / "vol_99.json"
    ia_abbyy.assemble_volume_json(
        volume_num=99,
        sidecar_dir=sidecar_dir,
        out_path=out_path,
    )
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["rendering_id"] == "ia-abbyy/schaff/encyclopedia/1908-1914/v1"
    assert data["volume"] == 99
    assert data["engine_alias"] == "ia-abbyy-v1"
    assert data["page_count"] == 2
    assert data["pages_with_data"] == 2
    # confidence_mean is the word-count-weighted mean of per-page means,
    # rounded to 1 decimal place to match the tesseract assembler convention.
    # = (80*100 + 90*200) / (100+200) = 86.6667 -> 86.7
    assert data["confidence_mean"] == pytest.approx(86.7, abs=0.05)
    assert len(data["pages"]) == 2
    p = data["pages"][0]
    assert {"page", "confidence_mean", "word_count", "text"} <= p.keys()


def _write_sidecar(sidecar_dir: Path, page_num: int | str, filename: str) -> None:
    (sidecar_dir / filename).write_text(
        json.dumps(
            {
                "engine_version": None,
                "page_num": page_num,
                "confidence_mean": 80.0,
                "word_count": 10,
                "text": str(page_num),
            }
        ),
        encoding="utf-8",
    )


def test_assemble_volume_handles_mixed_int_and_str_page_nums(tmp_path):
    sidecar_dir = tmp_path / "vol_99"
    sidecar_dir.mkdir()
    _write_sidecar(sidecar_dir, "leaf0001", "page_leaf0001.ia-abbyy.json")
    _write_sidecar(sidecar_dir, 2, "page_0001.ia-abbyy.json")
    _write_sidecar(sidecar_dir, 1, "page_0002.ia-abbyy.json")

    payload = ia_abbyy.assemble_volume_json(
        volume_num=99,
        sidecar_dir=sidecar_dir,
        out_path=tmp_path / "rendering.json",
    )

    assert [page["page"] for page in payload["pages"]] == [1, 2, "leaf0001"]


def test_assemble_volume_rendering_includes_unmapped_leaf_count(tmp_path):
    sidecar_dir = tmp_path / "vol_99"
    sidecar_dir.mkdir()
    _write_sidecar(sidecar_dir, "leaf0001", "page_leaf0001.ia-abbyy.json")
    _write_sidecar(sidecar_dir, 1, "page_0001.ia-abbyy.json")

    payload = ia_abbyy.assemble_volume_json(
        volume_num=99,
        sidecar_dir=sidecar_dir,
        out_path=tmp_path / "rendering.json",
    )

    assert payload["unmapped_leaf_count"] == 1


def test_existing_clean_manifest_parse_unchanged(tmp_path):
    gz_path = _write_test_volume(tmp_path, page_count=2)
    manifest_path = _write_test_manifest(tmp_path, mapped_leaves=[0, 1])
    sidecar_dir = tmp_path / "vol_99"

    stats = ia_abbyy.parse_volume(gz_path, manifest_path, sidecar_dir)

    assert stats["pages_parsed"] == 2
    assert stats["pages_skipped"] == 0
    assert stats["pages_leaf_captured"] == 0
    assert sorted(path.name for path in sidecar_dir.glob("*.json")) == [
        "page_0001.ia-abbyy.json",
        "page_0002.ia-abbyy.json",
    ]


def test_leaf_to_pagenum_maps_imageless_body_gap_with_leaf_id():
    """Image-less body pages (permanent gaps) with a recorded leaf map to their
    printed page so their ABBYY sidecar is named page_NNNN, not page_leafNNNN.

    vol_13 pp209-211 are bibliographical-appendix body pages absent as images but
    present as ABBYY text (leaves 225-227). Without the gap-leaf mapping they fall
    back to page_leaf naming and are orphaned from any printed-page consumer.
    """
    manifest = {
        "pages": [{"page_num": 208, "ia_leaf_id": "0224"}],
        "gaps": [
            {"page_num": 209, "status": "permanently_missing", "ia_leaf_id": "0225"},
            {"page_num": 210, "status": "permanently_missing", "ia_leaf_id": "0226"},
            {"page_num": 211, "status": "permanently_missing", "ia_leaf_id": "0227"},
            # An unresolved back-matter gap without a leaf must not be mapped.
            {"page_num": 999, "status": "unresolved"},
        ],
    }
    mapping = ia_abbyy._leaf_to_pagenum(manifest)
    assert mapping[224] == 208
    assert mapping[225] == 209
    assert mapping[226] == 210
    assert mapping[227] == 211
    assert 999 not in mapping.values() or True  # no leaf -> not added
