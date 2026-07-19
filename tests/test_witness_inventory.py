"""Witness inventory superseded by rendering_catalog. Smoke test verifies the replacement schema works."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from ocd_kernel.lib.schema_enums import resolve_schema_path

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"


def test_rendering_catalog_supersedes_witness_inventory() -> None:
    schema = json.loads(resolve_schema_path("rendering_catalog").read_text(encoding="utf-8"))
    catalog = {
        "work_id": "adam-clarke.commentary",
        "edition": "1810-1826",
        "modernisation_intent": "intended",
        "pd_anchor_decision": {
            "chosen_rendering": "ccel/clarke/commentary/1810-1826/thml",
            "rationale": "CCEL ThML is structured.",
            "decided_at": "2026-05-17T00:00:00+00:00",
            "alternates_considered": [],
        },
        "renderings": [
            {
                "rendering_id": "ccel/clarke/commentary/1810-1826/thml",
                "role": "pd_anchor",
                "source": "ccel",
                "format": "thml",
                "license": "public-domain",
                "fetched_at": "2026-04-15",
                "source_hash": "sha256:" + "a" * 64,
                "coverage": {"volumes": [1]},
            }
        ],
    }
    jsonschema.validate(instance=catalog, schema=schema)
