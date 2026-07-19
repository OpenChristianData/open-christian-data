"""Coverage proof for the all-schema Phase 1B fixture corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cvw_phase1b.completion import generate_phase1b_completion
from cvw_phase1b.corpus_inventory import generate_corpus_inventory
from cvw_phase1b.phase2_input import generate_phase2_inputs


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "cvw_phase1b/fixtures/corpus_cases.json"
PUBLICATION_REGISTRY = REPO_ROOT / "cvw_phase1b/fixtures/publication_accounting.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_fixture_corpus_generates_owned_inventory_for_every_production_schema_type(
    tmp_path: Path,
) -> None:
    fixture = json.loads(FIXTURE.read_bytes())
    schema_types = fixture["schema_types"]
    registered_types = [
        item["schema_type"]
        for item in json.loads(PUBLICATION_REGISTRY.read_bytes())["exports"]
    ]
    assert fixture["identity"] == "verification-fixture-corpus-v1"
    assert schema_types == registered_types
    assert len(schema_types) == len(set(schema_types))

    root = tmp_path / "all-schema-corpus"
    catalog_bytes = b"# All-schema fixture catalog\n"
    _write(root / "docs/WORK_CATALOG.md", catalog_bytes)
    _write(
        root / "cvw_phase1b/corpus_inventory.py",
        (REPO_ROOT / "cvw_phase1b/corpus_inventory.py").read_bytes(),
    )
    _write(
        root / "schemas/v1/verification_inventory.schema.json",
        (REPO_ROOT / "schemas/v1/verification_inventory.schema.json").read_bytes(),
    )
    works = []
    exports = []
    for index, schema_type in enumerate(schema_types):
        work_id = f"fixture-{schema_type}"
        canonical_path = f"data/{schema_type}/{work_id}.json"
        source_hash = f"{index + 1:064x}"
        canonical_bytes = (
            json.dumps(
                {
                    "meta": {
                        "id": work_id,
                        "title": f"Fixture {schema_type}",
                        "schema_type": schema_type,
                        "schema_version": "1.0.0",
                        "provenance": {
                            "source_url": f"https://example.test/{schema_type}",
                            "source_hash": f"sha256:{source_hash}",
                        },
                    },
                    "data": [],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        _write(root / canonical_path, canonical_bytes)
        works.append(
            {
                "title": f"Fixture {schema_type}",
                "author": "Fixture Author",
                "category": "Fixture Works",
                "canonical_ownership": {
                    "state": "owned",
                    "work_id": work_id,
                    "schema_types": [schema_type],
                    "artifacts": [
                        {"path": canonical_path, "raw_sha256": _sha(canonical_bytes)}
                    ],
                },
                "reconstruction_adapter": {"state": "referenced_only"},
            }
        )
        export_path = f"exports/huggingface/{schema_type}.jsonl"
        export_bytes = (json.dumps({"_source_id": work_id}) + "\n").encode()
        _write(root / export_path, export_bytes)
        exports.append(
            {
                "schema_type": schema_type,
                "path": export_path,
                "raw_sha256": _sha(export_bytes),
                "rows": 1,
            }
        )

    catalog = {
        "identity": "verification-catalog-accounting-report-v1",
        "catalog_snapshot": {
            "path": "docs/WORK_CATALOG.md",
            "raw_sha256": _sha(catalog_bytes),
            "work_units": len(works),
        },
        "dependencies": [],
        "phase1b_exit": {"reasons": [], "state": "READY"},
        "counts": {
            "total": len(works),
            "reconstruction_authenticated": 0,
            "reconstruction_referenced_only": len(works),
            "reconstruction_unavailable": 0,
        },
        "canonical_data": {
            "artifacts_owned": len(works),
            "work_units_owned": len(works),
        },
        "works": works,
    }
    ir = {
        "identity": "verification-ir-accounting-report-v1",
        "dependencies": [],
        "counts": {
            "artifacts_owned": 0,
            "renderings_owned": 0,
            "work_units_with_ir": 0,
        },
        "renderings": [],
        "phase1b_ir_exit": {"reasons": [], "state": "READY"},
    }
    publication = {
        "identity": "verification-publication-accounting-report-v1",
        "dependencies": [],
        "counts": {
            "export_files": len(exports),
            "rows_owned": len(exports),
            "work_units_included": len(exports),
        },
        "exports": exports,
        "phase1b_publication_exit": {"reasons": [], "state": "READY"},
    }

    inventory = generate_corpus_inventory(root, catalog, ir, publication)
    for path in (
        "cvw_phase1b/phase2_input.py",
        "schemas/v1/verification_phase2_input.schema.json",
    ):
        _write(root / path, (REPO_ROOT / path).read_bytes())
    phase2_inputs = generate_phase2_inputs(root, inventory)
    completion = generate_phase1b_completion(
        catalog, ir, publication, inventory, phase2_inputs
    )

    assert {item["schema_type"] for item in inventory["projection_artifacts"]} == set(
        schema_types
    )
    assert len(inventory["works"]) == 12
    assert completion["state"] == "READY"


def test_fixture_corpus_names_every_required_malformed_ownership_case() -> None:
    fixture = json.loads(FIXTURE.read_bytes())

    assert set(fixture["malformed_ownership_cases"]) == {
        "duplicate-ownership",
        "missing-source-hash",
        "orphaned-ir",
        "unresolved-export-row",
        "grain-mixing",
        "false-current-evidence",
    }
