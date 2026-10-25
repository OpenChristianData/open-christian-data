"""Token enrichment must find split schemas and retain its fail-closed preflight."""

from pathlib import Path
import json

import pytest

from build.scripts import add_token_counts


def test_preflight_resolves_shared_and_dataset_schemas():
    assert add_token_counts.preflight_schema_check() == []


@pytest.mark.parametrize("failure", ["missing", "undeclared"])
def test_preflight_reports_schema_identity_on_failure(tmp_path: Path, monkeypatch, failure):
    schema = tmp_path / "sample.schema.json"
    schema.write_text('{"properties": {}}', encoding="utf-8")
    monkeypatch.setattr(add_token_counts, "SCHEMA_FILES", {"commentary": schema.name})

    def resolve(_name):
        if failure == "missing":
            raise FileNotFoundError("schema unavailable")
        return schema

    monkeypatch.setattr(add_token_counts, "resolve_schema_path", resolve)
    assert add_token_counts.preflight_schema_check() == ["commentary"]


@pytest.mark.parametrize("case, expected_exit", [("missing-count", 0), ("mismatch", 1), ("invalid-json", 1)])
def test_explicit_historical_dry_run_preserves_bytes_and_reports_errors(tmp_path, monkeypatch, case, expected_exit):
    data = tmp_path / "data"
    data.mkdir()
    path = data / "sample.json"
    record = {"commentary_text": "two words"}
    if case == "mismatch":
        record["token_count"] = 99
    content = "invalid JSON" if case == "invalid-json" else json.dumps({
        "meta": {"schema_type": "commentary"}, "data": [record]
    })
    path.write_text(content, encoding="utf-8")
    before = path.read_bytes()
    output = tmp_path / "output-must-not-exist"
    monkeypatch.setattr(add_token_counts, "DATA_DIR", str(data))
    monkeypatch.setattr(add_token_counts, "OUTPUT_DIR", str(output))
    monkeypatch.setattr(add_token_counts, "setup_logging", lambda: None)
    monkeypatch.setattr(add_token_counts, "count_tokens", lambda text: len(text.split()))
    assert add_token_counts.main(["--legacy-data", "--dry-run"]) == expected_exit
    assert path.read_bytes() == before
    assert not output.exists()
