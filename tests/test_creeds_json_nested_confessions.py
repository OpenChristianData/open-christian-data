"""Chapter/section mapping and mutation probes for four retained confessions."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.creeds_json_nested_confessions import ROUTES, project_units, shape, verify_units


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("work_id", sorted(ROUTES))
def test_nested_sections_keep_chapter_parent_and_exact_labels(work_id: str) -> None:
    route = ROUTES[work_id]
    source = json.loads((ROOT / route["source_path"]).read_bytes())
    identity = {"work_id": work_id, "textual_form_id": f"{work_id}-retained-electronic", "edition_id": f"{work_id}-creeds-json"}
    context = {
        "work_id": work_id, "identity": identity, "edition_title": source["Metadata"]["Title"],
        "source_url": "https://example.invalid/retained-source", "source_path": route["source_path"],
        "accepted": {"representation_revision": {"id": "exact-source-test"}}, "document": source,
    }
    loci = {
        f"$/Data/{chapter_index}/Sections/{section_index}#item": f"section-{chapter_index + 1}-{section_index + 1}"
        for chapter_index, chapter in enumerate(source["Data"])
        for section_index, _ in enumerate(chapter["Sections"])
    }
    rows = project_units(context, source, loci)
    assert len(rows) == route["row_count"]
    assert rows[0]["locator"]["divisions"][0]["number"] == source["Data"][0]["Chapter"]
    assert rows[-1]["number"] == source["Data"][-1]["Sections"][-1]["Section"]
    crosswalk = {(path.removesuffix("#item"), "item"): value for path, value in loci.items()}
    assert verify_units(context, rows, crosswalk) == []
    changed = deepcopy(rows)
    changed[-1]["locator"]["divisions"][0]["number"] = "invented"
    assert verify_units(context, changed, crosswalk)
    altered_source = deepcopy(source)
    altered_source["Data"][0]["Sections"][0]["Extra"] = "omitted"
    with pytest.raises(PipelineError, match="section 1/1 differs"):
        shape(work_id, altered_source)
