"""Lossless bounded packing of verified reader projections."""

import json

import pytest

from cvw_app.ingest_cache import (
    PackedContexts, PackedOutline, PackedValues, VerifiedIngestCache,
    compact_projection, estimate_retained_bytes,
)
from cvw_app.review_contract import serialized_payload_size

pytest_plugins = ("cvw_app.tests.test_review_work_catalog",)


def test_packed_blocks_preserve_boundaries_unicode_and_detached_values():
    values = [{"label": f"節 {i}", "nodes": [{"text": "é 😀"}]} for i in range(131)]
    packed = PackedValues(values)
    assert list(packed) == values
    for index in (0, 63, 64, 127, 130, -1):
        assert packed[index] == values[index]
    assert packed[61:67] == values[61:67]
    assert packed[::-1] == values[::-1]
    with pytest.raises(IndexError):
        packed[131]
    with pytest.raises(IndexError):
        packed[-132]
    packed[0]["nodes"].clear()
    assert packed[0] == values[0]
    outline = PackedOutline(values)
    assert serialized_payload_size(outline) == len(json.dumps(values, ensure_ascii=False).encode("utf-8"))
    contexts = PackedContexts({str(i): value for i, value in enumerate(values)})
    assert contexts.get("64") == values[64]
    sentinel = object()
    assert contexts.get("missing", sentinel) is sentinel
    with pytest.raises(KeyError):
        contexts["missing"]


def test_large_projection_packing_reduces_retention_and_respects_budget():
    # Repeated labels and contexts model a dense outline; unique locations stay exact.
    outline = [{"location": str(i), "label": ("Readable heading " * 25) + str(i), "level": 1}
               for i in range(8000)]
    contexts = {item["location"]: {"location": item["location"], "label": item["label"],
                "nodes": [{"type": "paragraph", "text": item["label"]}], "text": item["label"]}
                for item in outline}
    original = {"outline": outline, "contexts": contexts, "nodes": [], "_pages": [[]], "segments": []}
    packed = compact_projection(original, threshold=0)
    original_size = estimate_retained_bytes(original)
    packed_size = estimate_retained_bytes(packed)
    assert packed_size < original_size / 3
    assert list(packed["outline"]) == outline
    assert packed["contexts"]["7999"] == contexts["7999"]
    cache = VerifiedIngestCache(max_retained_bytes=packed_size)
    cache.admit(("packed",), packed)
    assert cache.get(("packed",)) is packed
    cache.admit(("expanded",), original)
    assert cache.get(("expanded",)) is None
    assert cache.get(("packed",)) is packed
    print(f"synthetic retained bytes: expanded={original_size}, packed={packed_size}")


def test_packed_stage_view_matches_expanded_and_rechecks_changed_bytes(evidence_pair, monkeypatch):
    from cvw_app import review_contract

    app, selection, _ = evidence_pair(
        source_bytes=b'<h1 id="same">First</h1><p>Body</p><h1 id="same">Second</h1><p>More</p>'
    )
    recorded = selection["left_recorded"]
    expected = app.stage_view("brief-example", "source", recorded=recorded, segment_start=0, segment_limit=1)
    app._cache = VerifiedIngestCache()
    monkeypatch.setattr(review_contract, "compact_projection", lambda value: compact_projection(value, threshold=0))
    actual = app.stage_view("brief-example", "source", recorded=recorded, segment_start=0, segment_limit=1)
    assert actual == expected
    warm = app.stage_view("brief-example", "source", recorded=recorded, segment_start=0, segment_limit=1)
    assert warm["paging"]["cache_resident"] is True
    warm["paging"]["cache_resident"] = False
    assert warm["presentation"]["freshness"] == "admitted-snapshot"
    warm["presentation"]["freshness"] = expected["presentation"]["freshness"]
    assert warm == expected
    artifact = app.manifest["works"][0]["stages"]["source"]["artifacts"][0]
    path = app.roots[artifact["root"]] / artifact["path"]
    path.write_bytes(b"Changed bytes")
    snapshot = app.stage_view("brief-example", "source", recorded=recorded)
    assert snapshot["presentation"]["freshness"] == "admitted-snapshot"
    with pytest.raises(review_contract.ReviewContractError, match="sha256"):
        app.exact("brief-example", "source", recorded.artifact_id, recorded.version)
    app._cache = VerifiedIngestCache()
    stale = app.stage_view("brief-example", "source", recorded=recorded)
    assert stale["availability"] == "unsupported"
    assert "sha256" in stale["message"]
