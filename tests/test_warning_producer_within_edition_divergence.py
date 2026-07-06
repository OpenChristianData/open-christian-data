from __future__ import annotations


EXPECTED_CODE = "WITHIN_EDITION_DIVERGENCE"


def _codes(output: dict) -> set[str]:
    return {warning["code"] for warning in output["warnings"]}


def test_within_edition_divergence_checker() -> None:
    from build.lib.warning_producers import within_edition_divergence

    divergent_meta = {
        "resource_id": "sample",
        "renderings": [
            {"rendering_id": "source-a", "block_count": 10, "anchor_graph_density": 0.40, "auto_resolve_rate": 0.80},
            {"rendering_id": "source-b", "block_count": 4, "anchor_graph_density": 0.40, "auto_resolve_rate": 0.80},
        ],
    }
    clean_meta = {
        "resource_id": "sample",
        "renderings": [
            {"rendering_id": "source-a", "block_count": 10, "anchor_graph_density": 0.40, "auto_resolve_rate": 0.80},
            {"rendering_id": "source-b", "block_count": 10, "anchor_graph_density": 0.40, "auto_resolve_rate": 0.80},
        ],
    }

    assert EXPECTED_CODE in _codes(within_edition_divergence.run({}, divergent_meta, {}))
    assert EXPECTED_CODE not in _codes(within_edition_divergence.run({}, clean_meta, {}))
