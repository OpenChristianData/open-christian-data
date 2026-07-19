"""R19 — catalog/record pd_anchor consistency.

For every reconciled record under a work-edition, record.meta.pd_anchor must
equal catalog.pd_anchor_decision.chosen_rendering.  This test validates the
schema structures that make that invariant expressible and enforceable.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ocd_kernel.lib.schema_enums import resolve_schema_path

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"


def _schema(name: str) -> dict:
    return json.loads(resolve_schema_path(name).read_text(encoding="utf-8"))


_ANCHOR_RENDERING_ID = "ccel/schaff/encyclopedia/1908-1914/thml"

_CATALOG = {
    "work_id": "schaff.encyclopedia",
    "edition": "1908-1914",
    "modernisation_intent": "not_applicable",
    "pd_anchor_decision": {
        "chosen_rendering": _ANCHOR_RENDERING_ID,
        "rationale": "CCEL ThML preserves entry structure.",
        "decided_at": "2026-05-17T00:00:00+00:00",
        "alternates_considered": [],
    },
    "renderings": [
        {
            "rendering_id": _ANCHOR_RENDERING_ID,
            "role": "pd_anchor",
            "source": "ccel",
            "format": "thml",
            "license": "public-domain",
            "fetched_at": "2026-04-15",
            "source_hash": "sha256:" + "b" * 64,
            "coverage": {"volumes": [1]},
        }
    ],
}

_RECORD = {
    "meta": {
        "id": "schaff.encyclopedia.1908-1914",
        "title": "Schaff-Herzog Encyclopedia",
        "author_slug": "schaff",
        "author_display_name": "Philip Schaff",
        "author_birth_year": 1819,
        "author_death_year": 1893,
        "original_publication_year": 1908,
        "language": "en",
        "tradition": ["ecumenical"],
        "license": "public-domain",
        "schema_type": "reconciled_record",
        "schema_version": "3.0.0",
        "edition": "1908-1914",
        "pd_anchor": _ANCHOR_RENDERING_ID,
        "modernisation_ruleset_version": None,
        "attestation_summary": {
            "block_count": 1,
            "fully_attested_blocks": 1,
            "blocks_with_disagreements": 0,
            "blocks_with_structural_disagreements": 0,
        },
    },
    "blocks": [
        {
            "block_id": "b_0001aaaa",
            "block_id_history": [],
            "block_type": "headword",
            "language": "en",
            "language_confidence": 0.99,
            "language_alternates": [],
            "language_segments": [],
            "original_text": "Aachen.",
            "modern_text": "Aachen.",
            "annotations": {"headword_text": "Aachen"},
            "source_pages": [
                {"rendering_id": _ANCHOR_RENDERING_ID, "page_number": None}
            ],
            "attested_by": [_ANCHOR_RENDERING_ID],
            "disagreements": [],
            "structural_disagreements": [],
            "modernisations": [],
        }
    ],
    "match_explanations": [],
}


def test_catalog_and_record_schemas_both_valid() -> None:
    """Both schemas validate their golden instances — prerequisite for R19."""
    catalog_schema = _schema("rendering_catalog")
    jsonschema.validate(instance=_CATALOG, schema=catalog_schema)

    record_schema = _schema("reconciled_record")
    jsonschema.validate(instance=_RECORD, schema=record_schema)


def test_record_pd_anchor_matches_catalog_chosen_rendering() -> None:
    """R19 consistency: record.meta.pd_anchor == catalog.pd_anchor_decision.chosen_rendering."""
    catalog_anchor = _CATALOG["pd_anchor_decision"]["chosen_rendering"]
    record_anchor = _RECORD["meta"]["pd_anchor"]
    assert record_anchor == catalog_anchor, (
        f"Anchor drift: record.meta.pd_anchor={record_anchor!r} "
        f"!= catalog.pd_anchor_decision.chosen_rendering={catalog_anchor!r}"
    )


def test_stale_record_pd_anchor_detected() -> None:
    """Simulates a Reviewer anchor-swap: catalog updated, record not — mismatch is detectable."""
    swapped_catalog = {
        **_CATALOG,
        "pd_anchor_decision": {
            **_CATALOG["pd_anchor_decision"],
            "chosen_rendering": "ia/schaff/encyclopedia/1908-1914/ocr",
        },
    }
    catalog_anchor = swapped_catalog["pd_anchor_decision"]["chosen_rendering"]
    record_anchor = _RECORD["meta"]["pd_anchor"]
    assert catalog_anchor != record_anchor, (
        "Test setup error: expected catalog/record mismatch to be detectable"
    )
    # The Checker (Slot 7) uses this comparison at runtime; this test proves
    # the two fields are independently readable so drift can be caught.
    with pytest.raises(AssertionError):
        assert record_anchor == catalog_anchor, "catalog/record anchor drift"
