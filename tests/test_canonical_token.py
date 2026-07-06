"""Contract tests for build/lib/canonical_token.py (TEI-reviewer batch 01).

These are the RED tests authored before implementation (TDD). They pin the
scan-independent token identity contract from the TEI-reviewer architecture
plan v5 (plans/2026-07-02-tei-reviewer-architecture-plan.md) section 5:

    token identity = (work_id, volume_id, edition_page_key,
                      edition_position_ordinal)

- ``edition_position_ordinal`` is a body token's reading-order slot within the
  edition page, derived from the WCT ``reading_order`` (NOT the raw position_id).
- ``canonical_token_id`` is the stable ``ct-sha256:<64hex>`` hash of that tuple;
  it is the ``decision-event-v1`` fold key and depends ONLY on the edition
  tuple, never on scan fingerprints (source sha, bbox, raw position_id).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from build.lib.canonical_token import canonical_token_id, edition_position_ordinal

REPO_ROOT = Path(__file__).resolve().parents[1]

# Bind the id-format test to the schema's own pattern so the two cannot drift.
_DECISION_EVENT_SCHEMA = json.loads(
    (REPO_ROOT / "schemas" / "v1" / "decision-event-v1.schema.json").read_text(encoding="utf-8")
)
CT_TOKEN_ID_PATTERN = _DECISION_EVENT_SCHEMA["$defs"]["ct_token_id"]["pattern"]

# A real JE vol_02 WCT page (gitignored crop); tests that need it skip when absent.
_REAL_WCT_PAGE = REPO_ROOT / "reports" / "je-wct" / "vol_02" / "page_0038.json"

# Fixed inputs whose golden id is pinned below. Changing the canonical
# serialization in any way must change this hash and fail test_golden.
_GOLD_WORK_ID = "jewish-encyclopedia.vol_02"
_GOLD_VOLUME_ID = "vol_02"
_GOLD_EPK = {"section": "body", "anchor": 38, "ordinal": 0}
_GOLD_ORDINAL = 5
_GOLD_ID = "ct-sha256:9648f77988671a8701984c083acfd8147e6b1c2d37356019b6bfb630ca7edfc9"


# --- edition_position_ordinal ------------------------------------------------

def test_ordinal_is_index_in_reading_order():
    page = {
        "reading_order": ["p:a", "p:b", "p:c"],
        "positions": [{"position_id": "p:a"}, {"position_id": "p:b"}, {"position_id": "p:c"}],
    }
    assert edition_position_ordinal(page, "p:a") == 0
    assert edition_position_ordinal(page, "p:c") == 2


def test_ordinal_is_none_for_non_body_position():
    # A footnote/header position is absent from reading_order -> no body ordinal.
    page = {
        "reading_order": ["p:a", "p:b"],
        "positions": [{"position_id": "p:a"}, {"position_id": "p:fn"}],
    }
    assert edition_position_ordinal(page, "p:fn") is None


def test_ordinal_reads_reading_order_not_positions_order():
    # reading_order deliberately differs from positions[] order; the ordinal
    # must follow reading_order (two-column resolved), not array position.
    page = {
        "reading_order": ["p:b", "p:a"],
        "positions": [{"position_id": "p:a"}, {"position_id": "p:b"}],
    }
    assert edition_position_ordinal(page, "p:b") == 0
    assert edition_position_ordinal(page, "p:a") == 1


@pytest.mark.skipif(not _REAL_WCT_PAGE.exists(), reason="gitignored JE vol_02 crop absent")
def test_ordinal_round_trips_on_real_vol02_page():
    page = json.loads(_REAL_WCT_PAGE.read_text(encoding="utf-8"))
    reading_order = page["reading_order"]
    assert reading_order, "real page must have a non-empty reading_order"
    # Every reading_order entry resolves to its own index.
    for i, pid in enumerate(reading_order):
        assert edition_position_ordinal(page, pid) == i


# --- canonical_token_id ------------------------------------------------------

def test_canonical_token_id_golden():
    assert (
        canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, _GOLD_EPK, _GOLD_ORDINAL)
        == _GOLD_ID
    )


def test_canonical_token_id_matches_schema_pattern():
    got = canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, _GOLD_EPK, _GOLD_ORDINAL)
    assert re.match(CT_TOKEN_ID_PATTERN, got), f"{got!r} !~ {CT_TOKEN_ID_PATTERN}"


def test_canonical_token_id_is_deterministic():
    a = canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, _GOLD_EPK, _GOLD_ORDINAL)
    b = canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, dict(_GOLD_EPK), _GOLD_ORDINAL)
    assert a == b


def test_canonical_token_id_ignores_key_order_and_coerces_scalars():
    # Reordered edition_page_key, string-typed anchor/ordinal, and an extra
    # junk field must all produce the identical id (the tuple is normalized).
    messy_epk = {"ordinal": "0", "junk": "ignore-me", "anchor": "38", "section": "body"}
    assert (
        canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, messy_epk, _GOLD_ORDINAL)
        == _GOLD_ID
    )


def test_canonical_token_id_distinct_per_component():
    base = canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, _GOLD_EPK, _GOLD_ORDINAL)
    variants = [
        canonical_token_id("other-work", _GOLD_VOLUME_ID, _GOLD_EPK, _GOLD_ORDINAL),
        canonical_token_id(_GOLD_WORK_ID, "vol_99", _GOLD_EPK, _GOLD_ORDINAL),
        canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, {**_GOLD_EPK, "section": "front_matter"}, _GOLD_ORDINAL),
        canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, {**_GOLD_EPK, "anchor": 39}, _GOLD_ORDINAL),
        canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, {**_GOLD_EPK, "ordinal": 1}, _GOLD_ORDINAL),
        canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, _GOLD_EPK, _GOLD_ORDINAL + 1),
    ]
    assert all(v != base for v in variants), "each component change must flip the id"
    assert len(set(variants)) == len(variants), "distinct components -> distinct ids"


def test_canonical_token_id_rejects_negative_ordinal():
    with pytest.raises((ValueError, AssertionError)):
        canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, _GOLD_EPK, -1)


def test_canonical_token_id_rejects_malformed_edition_page_key():
    with pytest.raises((ValueError, KeyError, TypeError, AssertionError)):
        canonical_token_id(_GOLD_WORK_ID, _GOLD_VOLUME_ID, {"section": "body"}, _GOLD_ORDINAL)
