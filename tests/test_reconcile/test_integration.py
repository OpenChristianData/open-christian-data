"""Integration tests for build.lib.reconcile.reconcile().

All tests (except test_golden_fixture_reconcile which skips when expected_output.json absent,
and schema-based tests) import from build.lib.reconcile and will fail with ImportError
until production code exists (Task 2). That ImportError IS the RED state.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "reconcile_goldens" / "schaff_herzog"


def _assert_span_matches_chosen_reading(disagreements):
    """Per-op invariant: span width equals chosen_reading token count when the
    reading is non-empty."""
    for d in disagreements:
        cr = d.get("chosen_reading")
        if cr is None or cr == "":
            continue
        span = d["span"]
        width = span["end_token"] - span["start_token"]
        assert width == len(cr.split()), (
            f"span width {width} != chosen_reading token count {len(cr.split())} "
            f"for entry {d!r}"
        )


def _make_rendering(rendering_id, role, blocks):
    return {"rendering_id": rendering_id, "role": role, "blocks": blocks}


def _make_block(text, block_type="paragraph", annotations=None, page=1, rendering_id="r1"):
    return {
        "block_type": block_type,
        "original_text": text,
        "annotations": annotations or {},
        "source_pages": [{"rendering_id": rendering_id, "page_number": page}],
        "language": "en",
        "language_confidence": 0.95,
        "language_alternates": [],
        "language_segments": [],
    }


def _make_catalog(anchor_id, renderings):
    return {"pd_anchor": anchor_id, "renderings": renderings}


# --- N=1 trivial path ---


def test_n1_trivial_path():
    """Single pd_anchor → empty disagreements, structural_disagreements, match_explanations."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415  # ImportError = RED

    anchor_id = "ccel/test/thml"
    blocks = [
        _make_block("The Lord is my shepherd.", rendering_id=anchor_id),
        _make_block("I shall not want.", rendering_id=anchor_id),
    ]
    renderings = [_make_rendering(anchor_id, "pd_anchor", blocks)]
    catalog = _make_catalog(anchor_id, [{"rendering_id": anchor_id, "role": "pd_anchor", "format": "thml"}])

    result = reconcile(renderings, catalog)

    assert result["match_explanations"] == []
    for block in result["blocks"]:
        assert block["disagreements"] == []
        assert block["structural_disagreements"] == []
    assert result["meta"]["attestation_summary"]["block_count"] == 2


def test_r20_n1_empty_match_explanations():
    """R20: N=1 → match_explanations is the empty list (not None, not absent)."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    anchor_id = "r1"
    renderings = [_make_rendering(anchor_id, "pd_anchor", [_make_block("Grace and peace.", rendering_id=anchor_id)])]
    catalog = _make_catalog(anchor_id, [{"rendering_id": anchor_id, "role": "pd_anchor", "format": "thml"}])

    result = reconcile(renderings, catalog)
    assert isinstance(result["match_explanations"], list)
    assert len(result["match_explanations"]) == 0


def test_n2_anchor_wins_tie_breaker():
    """ADR-0013 §d: N=2 split/merge — anchor structure canonical; attestor merge surfaces as structural_disagreement."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    anchor_id = "ccel/test/thml"
    attestor_id = "ia/test/ocr"

    anchor_blocks = [
        _make_block("First paragraph.", rendering_id=anchor_id),
        _make_block("Second paragraph.", rendering_id=anchor_id),
    ]
    # Attestor merges the two anchor blocks into one
    attestor_blocks = [
        _make_block("First paragraph. Second paragraph.", rendering_id=attestor_id),
    ]

    renderings = [
        _make_rendering(anchor_id, "pd_anchor", anchor_blocks),
        _make_rendering(attestor_id, "pd_attestor", attestor_blocks),
    ]
    catalog = _make_catalog(anchor_id, [
        {"rendering_id": anchor_id, "role": "pd_anchor", "format": "thml"},
        {"rendering_id": attestor_id, "role": "pd_attestor", "format": "ocr"},
    ])

    result = reconcile(renderings, catalog)

    # Anchor structure wins: two blocks in the output
    assert len(result["blocks"]) == 2

    # At least one block has a structural_disagreement (the merge conflict)
    all_structural = [sd for block in result["blocks"] for sd in block["structural_disagreements"]]
    assert len(all_structural) >= 1
    kinds = {sd["kind"] for sd in all_structural}
    assert kinds & {"neighbour_merged_in_source", "block_split_in_source", "unclassified"}

    # Per-op invariant holds across any token-level disagreements emitted.
    all_disagreements = [d for block in result["blocks"] for d in block["disagreements"]]
    _assert_span_matches_chosen_reading(all_disagreements)


def test_n3_majority_and_split_vote():
    """N=3 with 1-1-1 split → chosen_reading is None (null); routes to Reviewer."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    r1, r2, r3 = "r1", "r2", "r3"
    renderings = [
        _make_rendering(r1, "pd_anchor", [_make_block("alpha text", rendering_id=r1)]),
        _make_rendering(r2, "pd_attestor", [_make_block("beta text", rendering_id=r2)]),
        _make_rendering(r3, "pd_attestor", [_make_block("gamma text", rendering_id=r3)]),
    ]
    catalog = _make_catalog(r1, [
        {"rendering_id": r1, "role": "pd_anchor", "format": "thml"},
        {"rendering_id": r2, "role": "pd_attestor", "format": "ocr"},
        {"rendering_id": r3, "role": "pd_attestor", "format": "ocr"},
    ])

    result = reconcile(renderings, catalog)

    # Per-op semantics: each attestor's "alpha"/"beta"/"gamma" word differs from
    # the anchor at exactly one token position. Two attestors → two per-op
    # entries (one per attestor, since each has a single differing op).
    all_disagreements = [d for block in result["blocks"] for d in block["disagreements"]]
    assert len(all_disagreements) == 2, (
        f"expected one per-op entry per attestor (2 total), got {len(all_disagreements)}"
    )

    # Gap 4.0 - 3.0 = 1.0 < 2.0 → no auto-choice; every entry routes to Reviewer.
    split_vote_disag = [d for d in all_disagreements if d.get("chosen_reading") is None]
    assert len(split_vote_disag) == 2

    # Each span covers exactly one token (the differing word).
    for d in all_disagreements:
        width = d["span"]["end_token"] - d["span"]["start_token"]
        assert width == 1, f"expected single-token span, got width {width}: {d!r}"

    _assert_span_matches_chosen_reading(all_disagreements)


def test_block_id_stability_across_re_reconcile():
    """R7: identical inputs → identical block_ids; re-reconcile with same anchor → same IDs."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    anchor_id = "ccel/test/thml"
    blocks = [_make_block("The grace of God.", rendering_id=anchor_id)]
    renderings = [_make_rendering(anchor_id, "pd_anchor", blocks)]
    catalog = _make_catalog(anchor_id, [{"rendering_id": anchor_id, "role": "pd_anchor", "format": "thml"}])

    result1 = reconcile(renderings, catalog)
    result2 = reconcile(renderings, catalog)

    ids1 = [b["block_id"] for b in result1["blocks"]]
    ids2 = [b["block_id"] for b in result2["blocks"]]
    assert ids1 == ids2

    # block_id_history is empty on first reconcile (no prior IDs)
    for block in result1["blocks"]:
        assert isinstance(block["block_id_history"], list)


def test_r30_catalog_requires_schema_and_parser_checks():
    """R30: catalog_meta missing renderings key → reconcile raises ValueError."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    anchor_id = "r1"
    renderings = [_make_rendering(anchor_id, "pd_anchor", [_make_block("Text.", rendering_id=anchor_id)])]

    # Missing 'renderings' key in catalog
    bad_catalog = {"pd_anchor": anchor_id}  # no 'renderings' key

    with pytest.raises((ValueError, KeyError)):
        reconcile(renderings, bad_catalog)


def test_r37_rendering_handle_tagged_segments_and_percent_encoded_slash():
    """R37: original_text with HTML tags and %2F percent-encoding passes through intact."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    anchor_id = "ccel/test/thml"
    blocks = [
        _make_block("<em>αγαπη</em> is love", rendering_id=anchor_id),
        _make_block("path%2Fto%2Fresource", rendering_id=anchor_id),
    ]
    renderings = [_make_rendering(anchor_id, "pd_anchor", blocks)]
    catalog = _make_catalog(anchor_id, [{"rendering_id": anchor_id, "role": "pd_anchor", "format": "thml"}])

    result = reconcile(renderings, catalog)

    texts = [b["original_text"] for b in result["blocks"]]
    assert "<em>αγαπη</em> is love" in texts
    assert "path%2Fto%2Fresource" in texts


def test_golden_fixture_reconcile():
    """Reconcile on the 10-block Schaff-Herzog fixture reproduces golden output byte-for-byte."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    anchor = json.loads((FIXTURE_DIR / "renderings" / "pd_anchor.json").read_text(encoding="utf-8"))
    attestor = json.loads((FIXTURE_DIR / "renderings" / "pd_attestor.json").read_text(encoding="utf-8"))
    catalog = json.loads((FIXTURE_DIR / "catalog.json").read_text(encoding="utf-8"))

    expected_path = FIXTURE_DIR / "expected_output.json"
    if not expected_path.exists():
        pytest.skip("expected_output.json not yet generated — run after Task 2")

    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    result = reconcile([anchor, attestor], catalog)

    assert json.dumps(result, sort_keys=True, ensure_ascii=False) == json.dumps(expected, sort_keys=True, ensure_ascii=False)


def test_reviewer_split_merge_re_keying():
    """Reviewer split: original block_id preserved in block_id_history of child blocks; child IDs deterministic."""
    from build.lib.reconcile.structural import split_block  # noqa: PLC0415

    # This tests the split_block helper that the Reviewer calls
    parent_block = {
        "block_id": "b_parent",
        "block_id_history": [],
        "block_type": "paragraph",
        "original_text": "First sentence. Second sentence.",
        "modern_text": "",
        "annotations": {},
        "source_pages": [],
        "attested_by": ["r1"],
        "disagreements": [],
        "structural_disagreements": [],
        "modernisations": [],
        "language": "en",
        "language_confidence": 0.95,
        "language_alternates": [],
        "language_segments": [],
    }

    children = split_block(parent_block, ["First sentence.", "Second sentence."])
    assert len(children) == 2
    for child in children:
        assert "b_parent" in child["block_id_history"]
    # Determinism: same split → same IDs
    children2 = split_block(parent_block, ["First sentence.", "Second sentence."])
    assert [c["block_id"] for c in children] == [c["block_id"] for c in children2]
