import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ocd_kernel.lib.schema_enums import resolve_schema_path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _schema(name: str) -> dict:
    return json.loads(resolve_schema_path(name).read_text(encoding="utf-8"))


RECONCILED_SCHEMA = _schema("reconciled_record")
CATALOG_SCHEMA = _schema("rendering_catalog")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _catalog(work_id: str) -> dict:
    return {
        "work_id": work_id,
        "edition": "2000",
        "modernisation_intent": "intended",
        "pd_anchor_decision": {
            "chosen_rendering": "fixture-anchor",
            "rationale": "Fixture anchor selected for deterministic publisher tests.",
            "decided_at": "2026-05-17T00:00:00Z",
            "alternates_considered": [
                {
                    "rendering_id": "fixture-attestor",
                    "rejected_because": "Fixture alternate for catalog coverage.",
                }
            ],
        },
        "renderings": [
            {
                "rendering_id": "fixture-anchor",
                "role": "pd_anchor",
                "source": "fixture",
                "format": "plain",
                "license": "public-domain",
            },
            {
                "rendering_id": "fixture-attestor",
                "role": "pd_attestor",
                "source": "fixture",
                "format": "plain",
                "license": "public-domain",
            },
        ],
    }


def _record(work_id: str, title: str) -> dict:
    return {
        "meta": {
            "id": f"{work_id}/0001",
            "title": title,
            "author_slug": "fixture-author",
            "author_display_name": "Fixture Author",
            "author_birth_year": None,
            "author_death_year": None,
            "original_publication_year": 2000,
            "language": "en",
            "tradition": ["reformed"],
            "license": "public-domain",
            "schema_type": "reconciled_record",
            "schema_version": "3.0.0",
            "edition": "2000",
            "pd_anchor": "fixture-anchor",
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
                "block_id": "0001-p1",
                "block_id_history": [],
                "block_type": "paragraph",
                "language": "en",
                "language_confidence": 1.0,
                "language_alternates": [],
                "language_segments": [],
                "original_text": f"{title} original text.",
                "modern_text": f"{title} modern text.",
                "annotations": {},
                "source_pages": [{"rendering_id": "fixture-anchor", "page_number": 1}],
                "attested_by": ["fixture-anchor"],
                "disagreements": [],
                "structural_disagreements": [],
                "modernisations": [],
            }
        ],
        "match_explanations": [],
    }


def _validate_and_write(path: Path, payload: dict, schema: dict) -> None:
    Draft202012Validator(schema).validate(payload)
    _write_json(path, payload)


def _stage_work(tmp_path: Path, work_slug: str, title: str) -> Path:
    work_id = f"reference/{work_slug}"
    work_dir = tmp_path / "data" / "reference" / work_slug / "2000"
    _validate_and_write(work_dir / "catalog.json", _catalog(work_id), CATALOG_SCHEMA)
    _validate_and_write(work_dir / "original" / "0001.json", _record(work_id, title), RECONCILED_SCHEMA)
    return work_dir


def test_publisher_glob_finds_all_records(tmp_path: Path) -> None:
    work_d = _stage_work(tmp_path, "work-d", "Work D")
    work_e = _stage_work(tmp_path, "work-e", "Work E")

    from build.tools.export_hf_dataset import MisplacedRecord
    from build.tools.export_hf_dataset import main

    export_root = tmp_path / "exports"
    assert main(["--data-root", str(tmp_path / "data"), "--output", str(export_root)]) == 0

    records_path = export_root / "original" / "records.jsonl"
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    assert {record["meta"]["id"] for record in records} == {
        "reference/work-d/0001",
        "reference/work-e/0001",
    }

    nested_path = work_d / "original" / "nested" / "extra.json"
    _validate_and_write(nested_path, _record("reference/work-d", "Nested Work D"), RECONCILED_SCHEMA)

    with pytest.raises(MisplacedRecord) as excinfo:
        main(["--data-root", str(tmp_path / "data"), "--output", str(tmp_path / "exports-with-nested")])
    assert "nested/extra.json" in str(excinfo.value).replace("\\", "/")
