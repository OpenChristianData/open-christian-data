"""Contract tests for the immutable Phase 2 route-input seam."""

from pathlib import Path

import pytest

from cvw_phase1b import generate_catalog_accounting, generate_ir_accounting
from cvw_phase1b.corpus_inventory import generate_corpus_inventory
from cvw_phase1b.phase2_input import generate_phase2_inputs, serialize_phase2_inputs
from cvw_phase1b.publication_accounting import generate_publication_accounting
from tests.test_cvw_phase1b_corpus_inventory import corpus_inputs


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_corpus_produces_one_immutable_complete_route(corpus_inputs) -> None:
    root, catalog, ir, publication = corpus_inputs
    inventory = generate_corpus_inventory(root, catalog, ir, publication)
    for path in (
        "cvw_phase1b/phase2_input.py",
        "schemas/v1/verification_phase2_input.schema.json",
    ):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / path).read_bytes())

    result = generate_phase2_inputs(root, inventory)

    assert len(result["routes"]) == 1
    route = result["routes"][0]
    assert route["work"]["title"] == "Example"
    assert route["rendering"]["renderer_adapter"] == "canonical-json-v1"
    assert route["source_panel"]["status"] == "referenced_only"
    assert route["ir_panel"]["status"] == "available"
    assert route["publication_panel"]["status"] == "schema_projection_available"
    assert serialize_phase2_inputs(result) == serialize_phase2_inputs(
        generate_phase2_inputs(root, inventory)
    )


@pytest.mark.slow
@pytest.mark.requires_local_artifacts
def test_live_selected_catalog_produces_routes_for_all_402_works() -> None:
    catalog = generate_catalog_accounting(
        REPO_ROOT, REPO_ROOT / "cvw_phase1b/fixtures/catalog_accounting.json"
    )
    ir = generate_ir_accounting(
        REPO_ROOT, REPO_ROOT / "cvw_phase1b/fixtures/ir_accounting.json", catalog
    )
    publication = generate_publication_accounting(
        REPO_ROOT,
        REPO_ROOT / "cvw_phase1b/fixtures/publication_accounting.json",
        catalog,
    )
    inventory = generate_corpus_inventory(REPO_ROOT, catalog, ir, publication)

    result = generate_phase2_inputs(REPO_ROOT, inventory)

    assert len(result["routes"]) == 402
    assert len({route["route_id"] for route in result["routes"]}) == 402
    assert sum(len(route["canonical_artifacts"]) for route in result["routes"]) == 1806
    assert all(route["canonical_artifacts"] for route in result["routes"])
