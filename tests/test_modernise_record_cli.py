from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from ocd_kernel.lib.schema_enums import resolve_schema_path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _record() -> dict:
    return {
        "meta": {
            "id": "fixture-record",
            "title": "Fixture Work",
            "author_slug": "fixture-author",
            "author_display_name": "Fixture Author",
            "author_birth_year": None,
            "author_death_year": None,
            "original_publication_year": 2000,
            "language": "en",
            "tradition": ["ecumenical"],
            "license": "public-domain",
            "schema_type": "reconciled_record",
            "schema_version": "3.0.0",
            "edition": "2000",
            "pd_anchor": "anchor",
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
                "block_id": "b_0001",
                "block_id_history": [],
                "block_type": "paragraph",
                "language": "en",
                "language_confidence": 1.0,
                "language_alternates": [],
                "language_segments": [],
                "original_text": "Old text.",
                "modern_text": "Old text.",
                "annotations": {},
                "source_pages": [{"rendering_id": "anchor", "page_number": 1}],
                "attested_by": ["anchor"],
                "disagreements": [],
                "structural_disagreements": [],
                "modernisations": [],
            }
        ],
        "match_explanations": [],
    }


def test_modernise_record_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record_path = tmp_path / "data/reference/test-work/2000/original/part-1.json"
    _write_json(record_path, _record())
    monkeypatch.chdir(tmp_path)

    from build.tools.modernise_record import main

    result = main([str(record_path)])
    assert result in (0, None)
    modernised_path = tmp_path / "data/reference/test-work/2000/modernised/part-1.json"
    modernised = json.loads(modernised_path.read_text(encoding="utf-8"))
    schema = json.loads(resolve_schema_path("modernised_record").read_text(encoding="utf-8"))
    jsonschema.validate(modernised, schema)

    first_bytes = modernised_path.read_bytes()
    result = main([str(record_path)])
    assert result in (0, None)
    assert modernised_path.read_bytes() == first_bytes
