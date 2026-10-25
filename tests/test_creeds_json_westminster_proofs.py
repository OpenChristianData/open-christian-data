"""Exact Westminster chapter, section, proof, and reference mapping probes."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.creeds_json_carrier import _decode
from ocd_kernel.projection.categories.creeds_json_westminster_proofs import ROUTES, project_units, shape, verify_units


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("work_id", sorted(ROUTES))
def test_westminster_proofs_keep_source_order_and_hierarchy(work_id: str) -> None:
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
    assert sum(len(row["proofs"]) for row in rows) == route["proof_count"]
    assert sum(len(proof["references"]) for row in rows for proof in row["proofs"]) == route["reference_count"]
    assert [proof["id"] for proof in rows[0]["proofs"]] == [1, 3, 2, 5, 4, 6]
    assert rows[0]["locator"]["divisions"][0]["number"] == source["Data"][0]["Chapter"]
    assert rows[-1]["number"] == source["Data"][-1]["Sections"][-1]["Section"]
    crosswalk = {(path.removesuffix("#item"), "item"): value for path, value in loci.items()}
    assert verify_units(context, rows, crosswalk) == []
    changed = deepcopy(rows)
    changed[0]["proofs"][0]["references"][0]["raw"] = "invented"
    assert verify_units(context, changed, crosswalk)
    altered_source = deepcopy(source)
    altered_source["Data"][0]["Sections"][0]["Proofs"][0]["References"] = []
    with pytest.raises(PipelineError, match="proof at section 1/1 differs"):
        shape(work_id, altered_source)


def test_json_integer_proof_id_carrier_is_typed_and_closed() -> None:
    ns = "http://www.tei-c.org/ns/1.0"
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    carrier = ET.Element(f"{{{ns}}}div", {"type": "json-number", xml_id: "proof-id"})
    ET.SubElement(carrier, f"{{{ns}}}ab", {"type": "json-scalar"}).text = "3"
    assert _decode(carrier, "$/Data/0/Sections/0/Proofs/0/Id", {}) == 3
    carrier[0].text = "03"
    with pytest.raises(PipelineError, match="integer carrier differs"):
        _decode(carrier, "$/Data/0/Sections/0/Proofs/0/Id", {})
