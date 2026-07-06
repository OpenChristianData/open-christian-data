from __future__ import annotations

import json
from pathlib import Path

import pytest


def _source_dir(tmp_path: Path) -> Path:
    source_dir = tmp_path / "source"
    source_dir.mkdir(parents=True)
    (source_dir / "volume-1.json").write_text(
        json.dumps(
            {
                "meta": {"id": "schaff-herzog-volume-1", "schema_version": "2.0.0"},
                "entries": [{"entry_id": "aaron", "headword": "Aaron", "body": "Text."}],
            }
        ),
        encoding="utf-8",
    )
    return source_dir


def _paths(tmp_path: Path) -> dict[str, Path]:
    output_root = tmp_path / "data" / "reference" / "schaff" / "encyclopedia" / "1908-1914"
    return {
        "output_root": output_root,
        "workbench_root": tmp_path / "review" / "state",
        "catalog_path": output_root / "catalog.json",
        "audit_path": tmp_path / "review" / "audit.jsonl",
    }


def test_r70_migration_writes_operator_chosen_anchor(tmp_path, monkeypatch):
    from build.tools.migrate_schaff_herzog import MigrationAborted, migrate_records

    paths = _paths(tmp_path)
    prompt_returned = {"value": False}

    def choose_second(_prompt):
        prompt_returned["value"] = True
        assert not paths["catalog_path"].exists()
        return "second"

    monkeypatch.setattr("builtins.input", choose_second)
    migrate_records(source_dir=_source_dir(tmp_path), **paths)

    catalog = json.loads(paths["catalog_path"].read_text(encoding="utf-8"))
    audit_log = paths["audit_path"].read_text(encoding="utf-8")
    assert prompt_returned["value"]
    assert catalog["pd_anchor_decision"]["chosen_rendering"] == "ia-ocr"
    assert [rendering["role"] for rendering in catalog["renderings"] if rendering["rendering_id"] == "ia-ocr"] == [
        "pd_anchor"
    ]
    assert "pre-decision" not in audit_log

    abort_root = tmp_path / "abort"
    abort_paths = _paths(abort_root)
    abort_source = _source_dir(abort_root)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    with pytest.raises(MigrationAborted):
        migrate_records(source_dir=abort_source, **abort_paths)

    assert not abort_paths["catalog_path"].exists()
