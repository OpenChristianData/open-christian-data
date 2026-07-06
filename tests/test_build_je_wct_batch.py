"""Tests for build/tools/build_je_wct_batch.py.

Covers the helper functions for loading per-page rendering-v1 files,
loading the IA pages manifest, building source_image dicts, and the
page-level WCT build for the JE WCT batch builder.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.build_je_wct_batch import (  # noqa: E402
    _collect_page_rendering_paths,
    _load_ia_manifest,
    _source_image,
)

# ---------------------------------------------------------------------------
# Minimal per-page rendering fixture (post-R4: one page per file)
# ---------------------------------------------------------------------------

_PAGE_RENDERING_FIXTURE = {
    "schema_version": "rendering-v1",
    "engine_family": "tesseract",
    "engine_version": "5.3.4",
    "work_id": "schaff-herzog-encyclopedia",
    "edition_id": "1908-1914",
    "volume": 2,
    "rendering_id": "tesseract-py314-v1/schaff/encyclopedia/1908-1914/v1",
    "source_lineage_id": "tesseract-py314-v1",
    "pipeline_config_hash": "abc123",
    "typography_snapshot_id": "snap-1",
    "typography_snapshot_approval_state": "approved",
    "ccel_annotation_source_id": None,
    "dictionary_snapshot_ids": [],
    "nfkc_allowlist_hash": "xyz",
    "fingerprint_function_hash": "def",
    "source_sidecar_refs": [{"sha256": "aabbccdd"}],
    "parsed_keys_index_refs": [],
    "witness_coverage": {},
    "candidate_articles": [],
    "derived_spans_by_block": [],
    "structural_uncertainty_queue": [],
    "operations_ledger_ref": None,
    "operations_ledger_hash": None,
    "replay_verification": None,
    "admission_state": "provisional",
    "pages": [
        {
            "page_native_id": "page_0010",
            "page_sequence": 10,
            "page_dimensions_native": {"width": 2048, "height": 2828, "unit": "pixel"},
            "blocks": [],
        }
    ],
}


# ---------------------------------------------------------------------------
# _collect_page_rendering_paths
# ---------------------------------------------------------------------------


class TestCollectPageRenderingPaths:
    """_collect_page_rendering_paths returns {engine: path} for engines that
    have a per-page rendering file for the given page_id."""

    def test_finds_existing_rendering(self, tmp_path: Path) -> None:
        # Set up a fake rendering tree: s2-root/engine/pages/page_0010.rendering-v1.json
        engine = "tesseract-py314-v1"
        pages_dir = tmp_path / engine / "pages"
        pages_dir.mkdir(parents=True)
        page_file = pages_dir / "page_0010.rendering-v1.json"
        page_file.write_text(json.dumps(_PAGE_RENDERING_FIXTURE), encoding="utf-8")

        result = _collect_page_rendering_paths("page_0010", tmp_path, [engine])
        assert engine in result
        assert result[engine] == page_file

    def test_skips_missing_engine(self, tmp_path: Path) -> None:
        engines = ["tesseract-py314-v1", "kraken-py312-v1"]
        # Only create tesseract page
        pages_dir = tmp_path / "tesseract-py314-v1" / "pages"
        pages_dir.mkdir(parents=True)
        (pages_dir / "page_0010.rendering-v1.json").write_text(
            json.dumps(_PAGE_RENDERING_FIXTURE), encoding="utf-8"
        )

        result = _collect_page_rendering_paths("page_0010", tmp_path, engines)
        assert "tesseract-py314-v1" in result
        assert "kraken-py312-v1" not in result

    def test_returns_empty_when_no_engines_have_page(self, tmp_path: Path) -> None:
        result = _collect_page_rendering_paths(
            "page_0010", tmp_path, ["tesseract-py314-v1"]
        )
        assert result == {}

    def test_skips_page_not_present_for_engine(self, tmp_path: Path) -> None:
        engine = "tesseract-py314-v1"
        pages_dir = tmp_path / engine / "pages"
        pages_dir.mkdir(parents=True)
        # Only page_0011 exists, not page_0010
        (pages_dir / "page_0011.rendering-v1.json").write_text(
            json.dumps(_PAGE_RENDERING_FIXTURE), encoding="utf-8"
        )

        result = _collect_page_rendering_paths("page_0010", tmp_path, [engine])
        assert result == {}


# ---------------------------------------------------------------------------
# _load_ia_manifest
# ---------------------------------------------------------------------------

_IA_MANIFEST_FIXTURE = {
    "ia_item_id": "cu31924091768196",
    "ia_derivative_type": "jp2",
    "volume": 2,
    "created_at": "2026-06-05T09:10:35.346214+00:00",
    "page_count": 3,
    "manifest_warnings": [],
    "pages": [
        {
            "page_num": 10,
            "ia_leaf_id": "0041",
            "ia_filename": "cu31924091768196_jp2.zip/cu31924091768196_jp2/cu31924091768196_0041.jp2",
            "local_path": "raw/jewish-encyclopedia/ia-pages/vol_02/page_0010.jpg",
            "sha256": "sha256:cc7dfc066531135243667f5032621f9efba0ce7d2d8419a2080e1cc49ca54cca",
            "fetched_at": "2026-06-05T09:10:35.346214+00:00",
            "image_mode": "L",
            "image_size": [2048, 2828],
        },
        {
            "page_num": 11,
            "ia_leaf_id": "0042",
            "ia_filename": "cu31924091768196_jp2.zip/cu31924091768196_jp2/cu31924091768196_0042.jp2",
            "local_path": "raw/jewish-encyclopedia/ia-pages/vol_02/page_0011.jpg",
            "sha256": "sha256:aabbcc0011",
            "fetched_at": "2026-06-05T09:10:36.000000+00:00",
            "image_mode": "L",
            "image_size": [2048, 2828],
        },
        {
            "page_num": 378,
            "ia_leaf_id": "0423",
            "ia_filename": "cu31924091768196_jp2.zip/cu31924091768196_jp2/cu31924091768196_0423.jp2",
            "local_path": "raw/jewish-encyclopedia/ia-pages/vol_02/page_0378.jpg",
            "sha256": "sha256:ddeeff9900",
            "fetched_at": "2026-06-05T09:10:37.000000+00:00",
            "image_mode": "L",
            "image_size": [2048, 2828],
        },
    ],
}


class TestLoadIaManifest:
    def test_keys_are_page_id_format(self, tmp_path: Path) -> None:
        manifest_file = tmp_path / "vol_02.manifest.json"
        manifest_file.write_text(json.dumps(_IA_MANIFEST_FIXTURE), encoding="utf-8")
        result = _load_ia_manifest(manifest_file)
        assert "page_0010" in result
        assert "page_0011" in result
        assert "page_0378" in result

    def test_page_num_padded_to_4_digits(self, tmp_path: Path) -> None:
        manifest_file = tmp_path / "vol_02.manifest.json"
        manifest_file.write_text(json.dumps(_IA_MANIFEST_FIXTURE), encoding="utf-8")
        result = _load_ia_manifest(manifest_file)
        assert "page_0378" in result
        assert result["page_0378"]["page_num"] == 378

    def test_preserves_page_info(self, tmp_path: Path) -> None:
        manifest_file = tmp_path / "vol_02.manifest.json"
        manifest_file.write_text(json.dumps(_IA_MANIFEST_FIXTURE), encoding="utf-8")
        result = _load_ia_manifest(manifest_file)
        info = result["page_0010"]
        assert info["local_path"] == "raw/jewish-encyclopedia/ia-pages/vol_02/page_0010.jpg"


# ---------------------------------------------------------------------------
# _source_image
# ---------------------------------------------------------------------------


class TestSourceImage:
    def test_strips_sha256_prefix(self) -> None:
        info = {
            "local_path": "raw/jewish-encyclopedia/ia-pages/vol_02/page_0010.jpg",
            "sha256": "sha256:cc7dfc066531135243667f5032621f9efba0ce7d2d8419a2080e1cc49ca54cca",
        }
        result = _source_image(info)
        assert result["sha256"] == "cc7dfc066531135243667f5032621f9efba0ce7d2d8419a2080e1cc49ca54cca"
        assert not result["sha256"].startswith("sha256:")

    def test_no_prefix_left_intact(self) -> None:
        info = {
            "local_path": "raw/jewish-encyclopedia/ia-pages/vol_02/page_0011.jpg",
            "sha256": "aabb1122",
        }
        result = _source_image(info)
        assert result["sha256"] == "aabb1122"

    def test_path_is_relative(self) -> None:
        """OUT-03: paths in committed JSON must be relative to repo root."""
        info = {
            "local_path": "raw/jewish-encyclopedia/ia-pages/vol_02/page_0010.jpg",
            "sha256": "sha256:aabb",
        }
        result = _source_image(info)
        assert not result["path"].startswith("/")
        assert not result["path"].startswith("C:")
        assert result["path"].startswith("raw/")

    def test_returns_required_keys(self) -> None:
        info = {
            "local_path": "raw/jewish-encyclopedia/ia-pages/vol_02/page_0010.jpg",
            "sha256": "sha256:ccdd",
        }
        result = _source_image(info)
        assert set(result.keys()) == {"path", "sha256"}
