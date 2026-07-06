from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_pipeline.run_ocr_pipeline import (  # noqa: E402
    DEFAULT_VOLUMES,
    _parse_pages_arg,
    _run_abbyy_lineages,
)


def test_default_volumes_include_vol_01() -> None:
    """Default corpus fan-out covers the full 13-volume set."""
    assert DEFAULT_VOLUMES == list(range(1, 14))


def test_parse_pages_arg_range() -> None:
    """1-10 expands to [1, 2, ..., 10]."""
    assert _parse_pages_arg(["1-10"]) == list(range(1, 11))


def test_parse_pages_arg_individual_integers() -> None:
    """Space-separated integers are collected as-is."""
    assert _parse_pages_arg(["1", "3", "5"]) == [1, 3, 5]


def test_parse_pages_arg_mixed_range_and_integers() -> None:
    """Mix of range and individual values, deduped and sorted."""
    assert _parse_pages_arg(["1-3", "5"]) == [1, 2, 3, 5]


def test_parse_pages_arg_empty_returns_none() -> None:
    """No --pages values means process whole volume (None)."""
    assert _parse_pages_arg([]) is None


def test_parse_pages_arg_deduplicates() -> None:
    """Overlapping ranges are deduped."""
    assert _parse_pages_arg(["1-3", "2-4"]) == [1, 2, 3, 4]


def _write_rich_sidecar(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "coordinate_unit": "pixel",
        "coordinate_frame": "source_image",
        "engine": "abbyy-finereader",
        "engine_version": "ABBYY FineReader",
        "page_index": 46,
        "page_num": 10,
        "page_size": {"width": 5034, "height": 6959},
        "word_count": 2,
        "text": "Grace peace",
        "blocks": [
            {
                "block_type": "Text",
                "bbox": {"x": 1136, "y": 684, "w": 516, "h": 120},
                "lines": [
                    {
                        "bbox": {"x": 1170, "y": 697, "w": 470, "h": 49},
                        "words": [
                            {"text": "Grace", "confidence": 80.0,
                             "bbox": {"x": 1170, "y": 697, "w": 259, "h": 49}},
                            {"text": "peace", "confidence": 60.0,
                             "bbox": {"x": 1440, "y": 697, "w": 200, "h": 49}},
                        ],
                    }
                ],
            }
        ],
    }
    path.write_text(json.dumps(record), encoding="utf-8")


def test_run_abbyy_lineages_reads_rich_sidecars_with_geometry(tmp_path: Path) -> None:
    """The re-point: ABBYY S1 reads raw/ rich sidecars, emitting word geometry.

    Before the fix, _run_abbyy_lineages read the flattened data/reference assembled
    JSON (no word boxes). Now it reads page_NNNN.<suffix>.json under input_root, so
    ABBYY joins Tesseract as a word-geometry engine.
    """
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_rich_sidecar(input_root / "vol_01" / "page_0010.ia-abbyy.json")
    s1_root = tmp_path / "reports" / "s1-sidecars"

    summaries, failures = _run_abbyy_lineages(
        1,
        s1_root=s1_root,
        input_root=input_root,
        repo_root=tmp_path,
        pages=[10],
    )

    assert failures == {}
    assert len(summaries) == 1
    assert summaries[0].manifest["engine_family"] == "abbyy"
    page_path = s1_root / "ia-abbyy-v1" / "vol_01" / "pages" / "page_0010.json"
    page = json.loads(page_path.read_text(encoding="utf-8"))
    words = [w for b in page["blocks"] for line in b["lines"] for w in line["words"]]
    assert len(words) == 2
    assert all(isinstance(w["bbox_native"], dict) for w in words)
    assert page["page_dimensions_native"]["unit"] == "pixel"
