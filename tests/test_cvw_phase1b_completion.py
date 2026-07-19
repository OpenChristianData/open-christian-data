"""Contract tests for the aggregate Phase 1B exit gate."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from cvw_phase1b.completion import Phase1BCompletionError, generate_phase1b_completion
from cvw_phase1b.corpus_inventory import generate_corpus_inventory
from cvw_phase1b.phase2_input import generate_phase2_inputs
from tests.test_cvw_phase1b_corpus_inventory import corpus_inputs


def _completion_inputs(
    inputs: tuple[Path, dict[str, object], dict[str, object], dict[str, object]],
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    root, catalog, ir, publication = inputs
    catalog = copy.deepcopy(catalog)
    ir = copy.deepcopy(ir)
    publication = copy.deepcopy(publication)
    catalog["counts"] = {
        "total": 1,
        "reconstruction_authenticated": 0,
        "reconstruction_referenced_only": 1,
        "reconstruction_unavailable": 0,
    }
    catalog["canonical_data"] = {"artifacts_owned": 1, "work_units_owned": 1}
    catalog["works"][0]["canonical_ownership"]["schema_types"] = ["structured_text"]
    ir["counts"] = {"artifacts_owned": 1, "renderings_owned": 1, "work_units_with_ir": 1}
    publication["counts"] = {"export_files": 1, "rows_owned": 1, "work_units_included": 1}
    inventory = generate_corpus_inventory(root, catalog, ir, publication)
    for path in (
        "cvw_phase1b/phase2_input.py",
        "schemas/v1/verification_phase2_input.schema.json",
    ):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((Path(__file__).resolve().parents[1] / path).read_bytes())
    phase2_inputs = generate_phase2_inputs(root, inventory)
    return catalog, ir, publication, inventory, phase2_inputs


def test_referenced_only_provenance_is_owned_but_reported_separately(
    corpus_inputs: tuple[Path, dict[str, object], dict[str, object], dict[str, object]],
) -> None:
    catalog, ir, publication, inventory, phase2_inputs = _completion_inputs(corpus_inputs)

    completion = generate_phase1b_completion(
        catalog, ir, publication, inventory, phase2_inputs
    )

    assert completion["state"] == "READY"
    assert completion["counts"] == {
        "work_units": 1,
        "canonical_artifacts": 1,
        "ir_artifacts": 1,
        "publication_exports": 1,
        "publication_rows": 1,
        "schema_types": 1,
        "phase2_routes": 1,
    }
    assert completion["reconstruction_depth"] == {
        "authenticated": 0,
        "referenced_only": 1,
        "unavailable": 0,
        "total": 1,
    }


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("unavailable", "catalog accounting is not READY"),
        ("work-count", "work ownership"),
        ("canonical-count", "canonical artifact"),
        ("ir-count", "IR artifact"),
        ("row-count", "row ownership"),
        ("schema-type", "schema-type coverage"),
        ("phase2-route", "Phase 2 route coverage"),
    ],
)
def test_completion_reconciliation_defects_fail_closed(
    corpus_inputs: tuple[Path, dict[str, object], dict[str, object], dict[str, object]],
    defect: str,
    message: str,
) -> None:
    catalog, ir, publication, inventory, phase2_inputs = _completion_inputs(corpus_inputs)
    if defect == "unavailable":
        catalog["counts"] = {
            "total": 1,
            "reconstruction_authenticated": 0,
            "reconstruction_referenced_only": 0,
            "reconstruction_unavailable": 1,
        }
        catalog["phase1b_exit"] = {
            "reasons": ["registered reconstruction adapters unavailable: 1"],
            "state": "BLOCKED",
        }
    elif defect == "work-count":
        inventory["catalog_snapshot"]["work_units"] = 2
    elif defect == "canonical-count":
        catalog["canonical_data"]["artifacts_owned"] = 2
    elif defect == "ir-count":
        ir["counts"]["artifacts_owned"] = 2
    elif defect == "row-count":
        publication["counts"]["rows_owned"] = 2
    elif defect == "schema-type":
        catalog["works"][0]["canonical_ownership"]["schema_types"] = ["other"]
    else:
        phase2_inputs["routes"] = []

    with pytest.raises(Phase1BCompletionError, match=message):
        generate_phase1b_completion(catalog, ir, publication, inventory, phase2_inputs)
