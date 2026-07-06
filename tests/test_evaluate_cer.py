from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.evaluate_cer import cer, evaluate_sidecar  # noqa: E402


def test_cer_identical_text_returns_zero() -> None:
    assert cer("abc", "abc") == 0.0


def test_cer_all_substitutions_returns_one() -> None:
    assert cer("xyz", "abc") == 1.0


def test_cer_modern_rnodern_is_partial_error() -> None:
    value = cer("modern", "rnodern")
    assert 0.0 < value < 1.0


def test_sidecar_without_matching_gt_warns_and_skips(capsys) -> None:
    sidecar = {
        "blocks": [
            {
                "block_type": "text",
                "lines": [
                    {"source_raw": "No matching transcript", "words": []},
                ],
            },
        ],
    }
    stats = {}

    evaluate_sidecar(
        engine="test-engine",
        sidecar=sidecar,
        sidecar_name="page_0001.json",
        gt_by_name={},
        stats_by_engine=stats,
    )

    captured = capsys.readouterr()
    assert "WARNING: missing GT for page_0001.json" in captured.err
    assert stats == {}
