"""Tests for build.lib.reconcile.anchor_graph.

All tests fail with ImportError until production code exists.
"""
from __future__ import annotations

import pytest


def _make_rendering(rendering_id, role):
    return {
        "rendering_id": rendering_id,
        "role": role,
        "blocks": [
            {
                "block_type": "paragraph",
                "original_text": "Sample text.",
                "annotations": {},
                "source_pages": [],
                "language": "en",
                "language_confidence": 0.95,
                "language_alternates": [],
                "language_segments": [],
            }
        ],
    }


def test_anchor_graph_identifies_pd_anchor():
    """build_anchor_graph identifies the pd_anchor rendering correctly."""
    from build.lib.reconcile.anchor_graph import build_anchor_graph  # noqa: PLC0415

    renderings = [
        _make_rendering("r_anchor", "pd_anchor"),
        _make_rendering("r_attestor", "pd_attestor"),
    ]
    catalog = {
        "pd_anchor": "r_anchor",
        "renderings": [
            {"rendering_id": "r_anchor", "role": "pd_anchor", "format": "thml"},
            {"rendering_id": "r_attestor", "role": "pd_attestor", "format": "ocr"},
        ],
    }

    graph = build_anchor_graph(renderings, catalog)
    assert graph["anchor_rendering_id"] == "r_anchor"


def test_anchor_graph_rejects_no_pd_anchor():
    """No pd_anchor rendering → ValueError."""
    from build.lib.reconcile.anchor_graph import build_anchor_graph  # noqa: PLC0415

    renderings = [_make_rendering("r1", "pd_attestor")]
    catalog = {
        "pd_anchor": "r_anchor",  # points to a rendering not in list
        "renderings": [{"rendering_id": "r1", "role": "pd_attestor", "format": "ocr"}],
    }

    with pytest.raises(ValueError, match="pd_anchor"):
        build_anchor_graph(renderings, catalog)


def test_anchor_graph_rejects_multiple_pd_anchors():
    """Two renderings both with pd_anchor role → ValueError."""
    from build.lib.reconcile.anchor_graph import build_anchor_graph  # noqa: PLC0415

    renderings = [
        _make_rendering("r1", "pd_anchor"),
        _make_rendering("r2", "pd_anchor"),
    ]
    catalog = {
        "pd_anchor": "r1",
        "renderings": [
            {"rendering_id": "r1", "role": "pd_anchor", "format": "thml"},
            {"rendering_id": "r2", "role": "pd_anchor", "format": "thml"},
        ],
    }

    with pytest.raises(ValueError, match="pd_anchor"):
        build_anchor_graph(renderings, catalog)
