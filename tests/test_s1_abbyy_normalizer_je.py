"""TDD tests for build/parsers/s1_abbyy_normalizer_je.py.

Covers:
- ia_abbyy_page_to_s1_sidecar: converts ia_abbyy.parse_page() output to S1 format
- normalize_je_abbyy_volume: streams GZ, emits sidecars for mapped pages
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import jsonschema
import pytest
from lxml import etree

ABBYY_NS = "http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml"

# Import module under test
import build.parsers.s1_abbyy_normalizer_je as mod

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"


# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------

def _make_abbyy_doc(n_pages: int) -> bytes:
    pages = []
    for i in range(n_pages):
        pages.append(
            f'<page width="2048" height="2828" xmlns="{ABBYY_NS}">'
            f'<block blockType="Text" l="100" t="100" r="900" b="200">'
            f"<text><par>"
            f'<line l="100" t="100" r="900" b="130" baseline="125">'
            f"<formatting>"
            f'<charParams l="100" t="100" r="120" b="130" charConfidence="92" wordStart="true">T</charParams>'
            f'<charParams l="121" t="100" r="140" b="130" charConfidence="91" wordStart="false">e</charParams>'
            f'<charParams l="141" t="100" r="160" b="130" charConfidence="90" wordStart="false">s</charParams>'
            f'<charParams l="161" t="100" r="180" b="130" charConfidence="93" wordStart="false">t</charParams>'
            f'<charParams l="181" t="100" r="185" b="130" charConfidence="255" wordStart="false"> </charParams>'
            f'<charParams l="186" t="100" r="206" b="130" charConfidence="88" wordStart="true">p</charParams>'
            f'<charParams l="207" t="100" r="227" b="130" charConfidence="89" wordStart="false">g</charParams>'
            f'<charParams l="228" t="100" r="248" b="130" charConfidence="90" wordStart="false">{i}</charParams>'
            f"</formatting>"
            f"</line></par></text>"
            f"</block></page>"
        )
    doc = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<document version="1.0" producer="ABBYY FineReader 11.0" '
        f'xmlns="{ABBYY_NS}">\n'
        + "\n".join(pages)
        + "\n</document>\n"
    )
    return doc.encode("utf-8")


def _write_gz(tmp_path: Path, n_pages: int = 5) -> Path:
    gz = tmp_path / "test_abbyy.gz"
    with gzip.open(gz, "wb") as fh:
        fh.write(_make_abbyy_doc(n_pages))
    return gz


def _make_manifest(tmp_path: Path, leaf_to_page: dict[int, int]) -> Path:
    manifest = {
        "ia_item_id": "cu31924091768196",
        "volume": 2,
        "page_count": len(leaf_to_page),
        "pages": [
            {
                "page_num": page_num,
                "ia_leaf_id": f"{leaf:04d}",
                "local_path": f"raw/jewish-encyclopedia/ia-pages/vol_02/page_{page_num:04d}.jpg",
            }
            for leaf, page_num in sorted(leaf_to_page.items())
        ],
    }
    path = tmp_path / "vol_02.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# ia_abbyy_page_to_s1_sidecar
# ---------------------------------------------------------------------------

def _sample_abbyy_page(page_index: int, page_num: int) -> dict:
    """Build a minimal ia_abbyy.parse_page()-like output dict."""
    return {
        "format_version": 1,
        "engine": "abbyy-finereader",
        "engine_version": "ABBYY FineReader 11.0",
        "page_index": page_index,
        "page_num": page_num,
        "page_size": {"width": 2048, "height": 2828},
        "confidence_mean": 92.0,
        "word_count": 2,
        "text": "Test word",
        "blocks": [
            {
                "block_type": "Text",
                "bbox": {"x": 100, "y": 100, "w": 800, "h": 100},
                "lines": [
                    {
                        "bbox": {"x": 100, "y": 100, "w": 800, "h": 30},
                        "baseline": 125,
                        "x_size": None,
                        "words": [
                            {
                                "text": "Test",
                                "confidence": 91.5,
                                "bbox": {"x": 100, "y": 100, "w": 50, "h": 30},
                            },
                            {
                                "text": "word",
                                "confidence": 89.0,
                                "bbox": {"x": 160, "y": 100, "w": 50, "h": 30},
                            },
                        ],
                    }
                ],
            }
        ],
    }


def test_sidecar_has_required_schema_version():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=1, manifest_id="m1")
    assert s["schema_version"] == "sidecar-page-v1"


def test_sidecar_page_sequence_is_as_passed():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=5, manifest_id="m1")
    assert s["page_sequence"] == 5


def test_sidecar_rendering_id_is_je_specific():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=1, manifest_id="m1")
    assert "jewish-encyclopedia" in s["rendering_id"]
    assert "schaff" not in s["rendering_id"]


def test_sidecar_page_dimensions_from_page_size():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=1, manifest_id="m1")
    dims = s["page_dimensions_native"]
    assert dims["width"] == 2048
    assert dims["height"] == 2828
    assert dims["unit"] == "pixel"


def test_sidecar_page_native_id_uses_printed_page_num():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=1, manifest_id="m1")
    assert s["page_native_id"] == "page_0038"


def test_sidecar_stamps_edition_page_key_and_clid_exempt_and_validates():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=1, manifest_id="m1")

    assert s["edition_page_key"] == {"section": "body", "anchor": 38, "ordinal": 0}
    assert s["clid_exempt"] is True
    jsonschema.validate(instance=s, schema=_schema("sidecar-page-v1"))


def test_sidecar_words_have_source_raw_not_text():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=1, manifest_id="m1")
    word = s["blocks"][0]["lines"][0]["words"][0]
    assert "source_raw" in word
    assert "text" not in word
    assert word["source_raw"] == "Test"


def test_sidecar_words_have_bbox_native_not_bbox():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=1, manifest_id="m1")
    word = s["blocks"][0]["lines"][0]["words"][0]
    assert "bbox_native" in word
    assert "bbox" not in word


def test_sidecar_words_have_observation_token_id():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=1, manifest_id="m1")
    word = s["blocks"][0]["lines"][0]["words"][0]
    assert "observation_token_id" in word
    assert word["observation_token_id"].startswith("ot-sha256:")


def test_sidecar_observation_token_ids_are_unique_per_word():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=1, manifest_id="m1")
    words = s["blocks"][0]["lines"][0]["words"]
    ids = [w["observation_token_id"] for w in words]
    assert len(ids) == len(set(ids)), "observation_token_ids must be unique"


def test_sidecar_blocks_have_bbox_native():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=1, manifest_id="m1")
    block = s["blocks"][0]
    assert "bbox_native" in block
    assert "bbox" not in block


def test_sidecar_lines_have_source_raw():
    page = _sample_abbyy_page(73, 38)
    s = mod.ia_abbyy_page_to_s1_sidecar(page, page_sequence=1, manifest_id="m1")
    line = s["blocks"][0]["lines"][0]
    assert "source_raw" in line
    assert line["source_raw"] == "Test word"


# ---------------------------------------------------------------------------
# normalize_je_abbyy_volume
# ---------------------------------------------------------------------------

def test_normalize_emits_sidecar_for_each_mapped_page(tmp_path):
    gz = _write_gz(tmp_path, n_pages=5)
    manifest = _make_manifest(tmp_path, {0: 10, 1: 11, 2: 12})
    out_dir = tmp_path / "sidecars"
    result = mod.normalize_je_abbyy_volume(gz, manifest, out_dir)
    assert result["emitted_pages"] == 3
    assert (out_dir / "pages" / "page_0010.json").exists()
    assert (out_dir / "pages" / "page_0011.json").exists()
    assert (out_dir / "pages" / "page_0012.json").exists()


def test_normalize_skip_existing_on_rerun(tmp_path):
    gz = _write_gz(tmp_path, n_pages=5)
    manifest = _make_manifest(tmp_path, {0: 10})
    out_dir = tmp_path / "sidecars"
    mod.normalize_je_abbyy_volume(gz, manifest, out_dir)
    result2 = mod.normalize_je_abbyy_volume(gz, manifest, out_dir, force=False)
    assert result2["skipped_pages"] == 1
    assert result2["emitted_pages"] == 0


def test_normalize_force_reruns_existing(tmp_path):
    gz = _write_gz(tmp_path, n_pages=5)
    manifest = _make_manifest(tmp_path, {0: 10})
    out_dir = tmp_path / "sidecars"
    mod.normalize_je_abbyy_volume(gz, manifest, out_dir)
    result2 = mod.normalize_je_abbyy_volume(gz, manifest, out_dir, force=True)
    assert result2["emitted_pages"] == 1
    assert result2["skipped_pages"] == 0


def test_normalize_writes_manifest_json(tmp_path):
    gz = _write_gz(tmp_path, n_pages=3)
    manifest = _make_manifest(tmp_path, {0: 10, 1: 11})
    out_dir = tmp_path / "sidecars"
    mod.normalize_je_abbyy_volume(gz, manifest, out_dir)
    m = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert m["engine_family"] == "abbyy"
    assert "jewish-encyclopedia" in m["rendering_id"]
    assert len(m["pages"]) == 2


def test_normalize_unmapped_leaves_skipped(tmp_path):
    gz = _write_gz(tmp_path, n_pages=5)
    # manifest only maps leaf 2 -> page 38; leaves 0,1,3,4 not in manifest
    manifest = _make_manifest(tmp_path, {2: 38})
    out_dir = tmp_path / "sidecars"
    result = mod.normalize_je_abbyy_volume(gz, manifest, out_dir)
    assert result["emitted_pages"] == 1
    assert (out_dir / "pages" / "page_0038.json").exists()
