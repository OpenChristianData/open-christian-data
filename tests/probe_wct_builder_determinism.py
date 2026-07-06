"""Probe: build one WCT page from minimal in-process renderings and write to argv[1].

Called by test_wct_builder_deterministic_across_hash_seeds under different
PYTHONHASHSEED values to verify that build_wct_page produces byte-identical
output regardless of hash seed.

The renderings are hard-coded to create a rep_key tie-break scenario:
  - Tesseract (geometry-bearing) reads "c" at position 1
  - ABBYY (geometry-bearing) reads "e" at position 1
  - "c" and "e" are a confusion pair (cost 0.30), so they land in the same
    alignment column, creating a count-1 tie in _Column.rep_key.
  - Surya (geometry-less) reads "c" at position 1 and aligns against the spine
    whose rep_key was non-deterministic before the fix.

Usage:
    PYTHONHASHSEED=0 py -3 tests/probe_wct_builder_determinism.py /tmp/wct_0.json
    PYTHONHASHSEED=1 py -3 tests/probe_wct_builder_determinism.py /tmp/wct_1.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from build.lib.wct_builder import build_wct_page  # noqa: E402


def _rendering(
    engine_family: str,
    lineage: str,
    version: str,
    run_id: str,
    words: list[tuple[str, dict | None]],
) -> dict:
    """Build a minimal rendering-v1 dict with one body block and one line."""
    word_list = [
        {
            "observation_token_id": f"{lineage}-w{i}",
            "layers": {"structured": text},
            "bbox_native": bbox,
            "confidence_raw": 0.85,
        }
        for i, (text, bbox) in enumerate(words)
    ]
    return {
        "schema_version": "rendering-v1",
        "rendering_id": run_id,
        "engine_family": engine_family,
        "source_lineage_id": lineage,
        "work_id": "test-work",
        "volume": 1,
        "engine_version": version,
        "pages": [
            {
                "page_native_id": "page_0001",
                "page_dimensions_native": {"width": 200, "height": 100},
                "blocks": [
                    {
                        "bbox_canonical": [0.0, 0.0, 1.0, 1.0],
                        "zone_label": "body",
                        "lines": [
                            {
                                "rendering_line_id": f"{lineage}-line-001",
                                "words": word_list,
                            }
                        ],
                    }
                ],
            }
        ],
    }


# Surya: layout authority + geometry-less OCR (bbox_native=None).
# Words: "c" and "valid".
surya = _rendering(
    "surya", "surya-py312-v1", "0.17.1", "surya-run-001",
    [("c", None), ("valid", None)],
)

# Tesseract: geometry-bearing (has bbox_native), reads "c" and "valid".
tess = _rendering(
    "tesseract", "tesseract-py314-v1", "5.5.0", "tess-run-001",
    [
        ("c",     {"x": 10, "y": 20, "w": 20, "h": 20}),
        ("valid", {"x": 40, "y": 20, "w": 60, "h": 20}),
    ],
)

# ABBYY: geometry-bearing, reads "e" at position 1 ("e" confusable with "c",
# confusion cost 0.30 -- this is the rep_key tie-break case).
abbyy = _rendering(
    "abbyy", "ia-abbyy-v1", "ia-2014", "abbyy-run-001",
    [
        ("e",     {"x": 10, "y": 20, "w": 20, "h": 20}),
        ("valid", {"x": 40, "y": 20, "w": 60, "h": 20}),
    ],
)

source_image = {
    "path": "raw/internet-archive/schaff-herzog-pages/vol_01/page_0001.jpg",
    "sha256": "a" * 64,
}

wct = build_wct_page(
    [surya, tess, abbyy],
    work_id="test-work",
    volume_id="vol_01",
    page_id="page_0001",
    source_image=source_image,
)

out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(wct, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
