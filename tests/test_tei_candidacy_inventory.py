"""Focused coverage checks for the TEI candidacy inventory."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from build.lib.paths import REPO_ROOT
from build.tools import build_tei_candidacy_inventory as inventory_tool


def test_real_tei_candidacy_inventory_has_zero_unclassified_families() -> None:
    errors, counts = inventory_tool.check_inventory(
        REPO_ROOT,
        REPO_ROOT / "docs" / "tei-candidacy-inventory.json",
    )

    assert errors == []
    assert counts["parsers"] > 0
    assert counts["configs"] > 0
    assert counts["outputs"] > 0
    assert counts["single_owned_outputs"] == counts["outputs"]
    assert counts["ir_artifacts"] > 0


def test_checker_rejects_seeded_unclassified_parser() -> None:
    inventory_path = REPO_ROOT / "docs" / "tei-candidacy-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    excluded = {item["path"] for item in inventory["excluded_parsers"]}
    live_parsers = inventory_tool.discover_production_parsers(REPO_ROOT, excluded)
    seeded = live_parsers | {"build/parsers/new_unclassified_family.py"}

    with patch.object(inventory_tool, "discover_production_parsers", return_value=seeded):
        errors, _counts = inventory_tool.check_inventory(REPO_ROOT, inventory_path)

    assert "unclassified production parser: build/parsers/new_unclassified_family.py" in errors


def _seed_repo(root: Path) -> None:
    (root / "build" / "parsers").mkdir(parents=True)
    (root / "sources").mkdir()
    (root / "data").mkdir()
    (root / "ir" / "census").mkdir(parents=True)


def _entry(
    entry_id: str,
    *,
    parsers: list[str] | None = None,
    config_rules: list[dict[str, object]] | None = None,
    data_globs: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": entry_id,
        "classification": "json-native",
        "parsers": parsers or [],
        "config_rules": config_rules or [],
        "data_globs": data_globs or [],
        "evidence": ["seeded-test-evidence"],
        "priority": 0,
        "owning_batch": "test",
        "notes": "Seeded test entry.",
    }


def test_non_ccel_thml_config_is_unclassified(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    config_path = tmp_path / "sources" / "reference" / "unrelated-thml-family" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "source_format": "ThML XML",
                "source_url": "https://example.org/unrelated.xml",
            }
        ),
        encoding="utf-8",
    )
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "entries": [
                    _entry(
                        "ccel-thml",
                        config_rules=[
                            {
                                "path_glob": "sources/**/config.json",
                                "field_in": {"source_format": ["ThML XML", "CCEL ThML XML"]},
                                "field_contains": {"source_url": ["ccel.org"]},
                            }
                        ],
                    )
                ]
            }
        ),
        encoding="utf-8",
    )

    errors, _counts = inventory_tool.check_inventory(tmp_path, inventory_path)

    assert "unclassified source config: sources/reference/unrelated-thml-family/config.json" in errors


def test_overlapping_data_globs_fail_with_multiple_owners(tmp_path: Path) -> None:
    _seed_repo(tmp_path)
    parser_path = tmp_path / "build" / "parsers" / "example.py"
    parser_path.write_text('"""Seeded parser."""\n', encoding="utf-8")
    output_path = tmp_path / "data" / "example" / "work.json"
    output_path.parent.mkdir(parents=True)
    output_path.write_text(
        json.dumps(
            {
                "meta": {
                    "provenance": {
                        "processing_script_version": "build/parsers/example.py@v1"
                    }
                },
                "data": [],
            }
        ),
        encoding="utf-8",
    )
    parser = "build/parsers/example.py"
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "entries": [
                    _entry(
                        "owner-one",
                        parsers=[parser],
                        data_globs=["data/example/*.json"],
                    ),
                    _entry(
                        "owner-two",
                        parsers=[parser],
                        data_globs=["data/example/*.json"],
                    ),
                ]
            }
        ),
        encoding="utf-8",
    )

    errors, _counts = inventory_tool.check_inventory(tmp_path, inventory_path)

    assert "multiply owned data output: data/example/work.json -> owner-one, owner-two" in errors
