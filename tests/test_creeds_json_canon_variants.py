"""Exact source-label and front/body/back tests for Canon-shaped Creeds."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.creeds_json_canon_variants import ROUTES, project_units, shape, verify_units


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("work_id", sorted(ROUTES))
def test_exact_labels_and_parts_survive_native_rows(work_id: str) -> None:
    route = ROUTES[work_id]
    source_bytes = (ROOT / "raw/Creeds.json/creeds" / f"{work_id.replace('-', '_')}.json").read_bytes()
    source = json.loads(source_bytes)
    carrier_ids = {f"$/Data/{index}#item": f"source-unit-{index + 1}" for index in range(len(source["Data"]))}
    identity = {"work_id": work_id, "textual_form_id": f"{work_id}-retained-electronic", "edition_id": f"{work_id}-creeds-json"}
    context = {
        "work_id": work_id, "identity": identity, "edition_title": source["Metadata"]["Title"],
        "source_url": "https://example.invalid/retained-source", "source_path": f"raw/Creeds.json/creeds/{work_id.replace('-', '_')}.json",
        "accepted": {"representation_revision": {"id": "exact-source-test"}}, "document": source,
        "source_bytes": source_bytes,
    }
    rows = project_units(context, source, carrier_ids)
    assert [row["number"] for row in rows] == route["labels"]
    assert [row["locator"]["text_part"] for row in rows] == [
        "front" if index in route["front_indices"] else "back" if index in route["back_indices"] else "body"
        for index in range(len(rows))
    ]
    crosswalk = {(f"$/Data/{index}", "item"): f"source-unit-{index + 1}" for index in range(len(rows))}
    assert verify_units(context, rows, crosswalk) == []
    mutated = deepcopy(rows)
    mutated[-1]["number"] = "invented"
    assert verify_units(context, mutated, crosswalk)
    altered_source = deepcopy(source)
    altered_source["Data"][0]["Article"] += "altered"
    with pytest.raises(PipelineError, match="label sequence"):
        shape(work_id, altered_source)
