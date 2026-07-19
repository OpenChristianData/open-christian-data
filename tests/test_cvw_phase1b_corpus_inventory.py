"""Contract tests for the corpus-wide Phase 1B ownership inventory."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from cvw_phase1b import generate_catalog_accounting, generate_ir_accounting
from cvw_phase1b.corpus_inventory import (
    CorpusInventoryError,
    generate_corpus_inventory,
    serialize_corpus_inventory,
)
from cvw_phase1b.publication_accounting import generate_publication_accounting


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_CATALOG_REGISTRY = REPO_ROOT / "cvw_phase1b/fixtures/catalog_accounting.json"
LIVE_IR_REGISTRY = REPO_ROOT / "cvw_phase1b/fixtures/ir_accounting.json"
LIVE_PUBLICATION_REGISTRY = REPO_ROOT / "cvw_phase1b/fixtures/publication_accounting.json"


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def corpus_inputs(tmp_path: Path) -> tuple[
    Path, dict[str, object], dict[str, object], dict[str, object]
]:
    root = tmp_path / "corpus"
    canonical_path = "data/structured-text/example.json"
    source_hash = "1" * 64
    canonical = (
        json.dumps(
            {
                "meta": {
                    "id": "example",
                    "title": "Example",
                    "schema_type": "structured_text",
                    "schema_version": "2.1.0",
                    "provenance": {
                        "source_url": "https://example.test/source",
                        "source_hash": f"sha256:{source_hash}",
                    },
                },
                "data": {"sections": []},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    catalog_path = "docs/WORK_CATALOG.md"
    catalog = b"# Synthetic catalog\n"
    ir_path = "ir/example/example.tei.xml"
    ir_data = b"<TEI/>\n"
    export_path = "exports/huggingface/structured_text.jsonl"
    export_data = b'{"_source_id":"example"}\n'
    for path, data in (
        (canonical_path, canonical),
        (catalog_path, catalog),
        (ir_path, ir_data),
        (export_path, export_data),
        ("cvw_phase1b/corpus_inventory.py", (REPO_ROOT / "cvw_phase1b/corpus_inventory.py").read_bytes()),
        ("schemas/v1/verification_inventory.schema.json", (REPO_ROOT / "schemas/v1/verification_inventory.schema.json").read_bytes()),
    ):
        _write(root / path, data)
    catalog_report: dict[str, object] = {
        "identity": "verification-catalog-accounting-report-v1",
        "catalog_snapshot": {
            "path": catalog_path,
            "raw_sha256": _sha(catalog),
            "work_units": 1,
        },
        "dependencies": [],
        "phase1b_exit": {"reasons": [], "state": "READY"},
        "works": [
            {
                "title": "Example",
                "author": "Example Author",
                "category": "Books and Long-Form Works",
                "canonical_ownership": {
                    "state": "owned",
                    "work_id": "example",
                    "schema_types": ["structured_text"],
                    "artifacts": [{"path": canonical_path, "raw_sha256": _sha(canonical)}],
                },
                "reconstruction_adapter": {"state": "referenced_only"},
            }
        ],
    }
    ir_report: dict[str, object] = {
        "identity": "verification-ir-accounting-report-v1",
        "dependencies": [],
        "renderings": [
            {
                "work_id": "example",
                "rendering_id": "example-tei",
                "artifacts": [{"path": ir_path, "raw_sha256": _sha(ir_data)}],
            }
        ],
        "phase1b_ir_exit": {"reasons": [], "state": "READY"},
    }
    publication_report: dict[str, object] = {
        "identity": "verification-publication-accounting-report-v1",
        "dependencies": [],
        "exports": [
            {
                "schema_type": "structured_text",
                "path": export_path,
                "raw_sha256": _sha(export_data),
                "rows": 1,
            }
        ],
        "phase1b_publication_exit": {"reasons": [], "state": "READY"},
    }
    return root, catalog_report, ir_report, publication_report


def test_corpus_inventory_owns_every_artifact_and_is_deterministic(
    corpus_inputs: tuple[Path, dict[str, object], dict[str, object], dict[str, object]],
) -> None:
    root, catalog, ir, publication = corpus_inputs

    inventory = generate_corpus_inventory(root, catalog, ir, publication)

    assert inventory["identity"] == "verification-inventory-v1"
    assert inventory["catalog_snapshot"] == {
        "path": "docs/WORK_CATALOG.md",
        "raw_sha256": _sha(b"# Synthetic catalog\n"),
        "work_units": 1,
        "canonical_artifacts": 1,
    }
    assert inventory["source_artifacts"] == [
        {
            "grain": "source_artifact",
            "availability": "referenced-only",
            "source_url": "https://example.test/source",
            "raw_sha256": "1" * 64,
            "rendering_id": "example:canonical-json",
        }
    ]
    assert len(inventory["ir_artifacts"]) == 1
    assert len(inventory["projection_artifacts"]) == 1
    assert serialize_corpus_inventory(inventory) == serialize_corpus_inventory(
        generate_corpus_inventory(root, catalog, ir, publication)
    )
    assert inventory["works"] == [
        {
            "grain": "work",
            "work_id": "example",
            "title": "Example",
            "author": "Example Author",
            "category": "Books and Long-Form Works",
            "schema_type": "structured_text",
            "schema_version": "2.1.0",
            "reconstruction_state": "referenced_only",
        }
    ]


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("canonical-hash", "canonical artifact hash drifted"),
        ("source-hash", "source hash must"),
        ("source-url", "source URL"),
        ("duplicate-path", "duplicate canonical artifact ownership"),
        ("unknown-ir-work", "unknown work"),
        ("projection-hash", "publication export hash drifted"),
    ],
)
def test_corpus_ownership_defects_fail_closed(
    corpus_inputs: tuple[Path, dict[str, object], dict[str, object], dict[str, object]],
    defect: str,
    message: str,
) -> None:
    root, catalog, ir, publication = corpus_inputs
    catalog = copy.deepcopy(catalog)
    ir = copy.deepcopy(ir)
    publication = copy.deepcopy(publication)
    if defect == "canonical-hash":
        catalog["works"][0]["canonical_ownership"]["artifacts"][0]["raw_sha256"] = "0" * 64
    elif defect in {"source-hash", "source-url"}:
        path = root / "data/structured-text/example.json"
        payload = json.loads(path.read_bytes())
        field = "source_hash" if defect == "source-hash" else "source_url"
        payload["meta"]["provenance"][field] = "bad" if defect == "source-hash" else ""
        data = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        path.write_bytes(data)
        catalog["works"][0]["canonical_ownership"]["artifacts"][0]["raw_sha256"] = _sha(data)
    elif defect == "duplicate-path":
        duplicate = copy.deepcopy(catalog["works"][0])
        duplicate["canonical_ownership"]["work_id"] = "other"
        catalog["works"].append(duplicate)
        catalog["catalog_snapshot"]["work_units"] = 2
    elif defect == "unknown-ir-work":
        ir["renderings"][0]["work_id"] = "unknown"
    else:
        publication["exports"][0]["raw_sha256"] = "0" * 64

    with pytest.raises(CorpusInventoryError, match=message):
        generate_corpus_inventory(root, catalog, ir, publication)


@pytest.mark.skipif(
    not (REPO_ROOT / "exports/huggingface/bible_text.jsonl").is_file(),
    reason="local publication snapshot is unavailable",
)
def test_live_corpus_inventory_owns_selected_production_snapshot() -> None:
    catalog = generate_catalog_accounting(REPO_ROOT, LIVE_CATALOG_REGISTRY)
    ir = generate_ir_accounting(REPO_ROOT, LIVE_IR_REGISTRY, catalog)
    publication = generate_publication_accounting(
        REPO_ROOT, LIVE_PUBLICATION_REGISTRY, catalog
    )

    inventory = generate_corpus_inventory(REPO_ROOT, catalog, ir, publication)

    assert len(inventory["works"]) == 402
    assert len(inventory["canonical_artifacts"]) == 1806
    assert len(inventory["ir_artifacts"]) == 75
    assert len(inventory["projection_artifacts"]) == 12
    assert sum(item["rows"] for item in inventory["projection_artifacts"]) == 805146
