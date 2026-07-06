"""Tests for build.lib.review_state."""

from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest

from build.lib import review_state, sidecar_migrations


def test_derive_sidecar_path_commentary():
    p = review_state.derive_sidecar_path("data/commentaries/adam-clarke/2-john.json")
    assert p == Path("review/state/commentaries/adam-clarke/2-john.json")


def test_derive_sidecar_path_encyclopedia():
    p = review_state.derive_sidecar_path("data/reference/schaff-herzog-encyclopedia.json")
    assert p == Path("review/state/reference/schaff-herzog-encyclopedia.json")


def test_derive_sidecar_path_rejects_non_data_path():
    with pytest.raises(ValueError):
        review_state.derive_sidecar_path("schemas/v1/commentary.schema.json")


def test_derive_sidecar_path_with_repo_root(tmp_path: Path):
    repo = tmp_path / "ocd"
    (repo / "data" / "reference").mkdir(parents=True)
    (repo / "data" / "reference" / "x.json").write_text("{}", encoding="utf-8")
    p = review_state.derive_sidecar_path(
        repo / "data" / "reference" / "x.json", repo_root=repo
    )
    assert p == (repo / "review" / "state" / "reference" / "x.json").resolve()


def test_empty_sidecar_has_required_fields():
    sc = review_state.empty_sidecar(
        record_path="data/foo.json",
        record_resource_id="foo",
        record_checksum_sha256="0" * 64,
        parser_version_seen="build/parsers/foo.py@v1.0.0",
    )
    schema = review_state.load_schema()
    jsonschema.validate(instance=sc, schema=schema)
    assert sc["schema_version"] == sidecar_migrations.CURRENT_VERSION
    assert sc["entries"] == {}
    assert sc["dead_letter"] == []
    assert sc["confidence"]["text_fidelity"] == "unverified"


def test_save_and_load_sidecar_round_trip(tmp_path: Path):
    sc = review_state.empty_sidecar(
        record_path="data/foo.json",
        record_resource_id="foo",
        record_checksum_sha256="a" * 64,
        parser_version_seen="build/parsers/foo.py@v1.0.0",
    )
    p = tmp_path / "sc.json"
    review_state.save_sidecar(p, sc)
    loaded = review_state.load_sidecar(p)
    assert loaded == sc


def test_save_sidecar_rejects_invalid_payload(tmp_path: Path):
    bad = {
        "schema_type": "review_state",
        "schema_version": "1.0.0",
        "record_path": "data/foo.json",
        "record_resource_id": "foo",
        "record_checksum_sha256": "z" * 64,  # not hex
        "parser_version_seen": "build/parsers/foo.py@v1.0.0",
        "confidence": {
            "structural_fidelity": "unverified",
            "text_fidelity": "unverified",
            "edition_provenance": "unverified",
        },
        "entries": {},
        "dead_letter": [],
    }
    from build.lib.atomic_io import SchemaValidationError

    with pytest.raises(SchemaValidationError):
        review_state.save_sidecar(tmp_path / "sc.json", bad)
    assert not (tmp_path / "sc.json").exists()


def test_render_dump_is_plain_english(tmp_path: Path):
    sc = review_state.empty_sidecar(
        record_path="data/reference/schaff-herzog-encyclopedia.json",
        record_resource_id="schaff-herzog-encyclopedia",
        record_checksum_sha256="b" * 64,
        parser_version_seen="build/parsers/ia_schaff_herzog.py@v1.0.0",
    )
    sc["entries"]["schaff-herzog.theotokos"] = {
        "warnings_acknowledged": [
            {
                "producer": "historical_lexicon",
                "code": "archaic_variant",
                "signature": "field=definition_blocks.b8f3a1c2;surface=Theotokos",
                "signature_version": "v1.0.0",
                "reason": "confirmed",
            }
        ],
        "warnings_dismissed": [
            {
                "producer": "ocr_scanner",
                "code": "digit_in_letter",
                "signature": "field=definition_blocks.b8f3a1c2;offset=12;token=TH0",
                "signature_version": "v1.0.0",
                "reason": "false_positive",
                "note": "OCR engine ambiguity on capital O",
            }
        ],
        "last_reviewed_at": "2026-05-12T10:00:00+00:00",
        "last_reviewer": "test_reviewer",
    }
    out = review_state.render_dump(sc)
    # Must mention the resource, the entry, both decision categories, and the
    # reviewer's note — without dumping raw JSON.
    assert "schaff-herzog-encyclopedia" in out
    assert "schaff-herzog.theotokos" in out
    assert "acknowledged (1)" in out
    assert "dismissed (1)" in out
    assert "OCR engine ambiguity on capital O" in out
    assert "test_reviewer" in out
    # No raw JSON braces in the output (the JSON-soup failure mode for step 6).
    assert "{" not in out and "}" not in out


def test_cli_dump_runs_against_record_path(tmp_path: Path, monkeypatch, capsys):
    # Create a record-shaped path and its sidecar.
    record = tmp_path / "data" / "foo.json"
    record.parent.mkdir(parents=True)
    record.write_text("{}", encoding="utf-8")
    sidecar_path = review_state.derive_sidecar_path(record)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    review_state.save_sidecar(
        sidecar_path,
        review_state.empty_sidecar(
            record_path=str(record.relative_to(tmp_path)),
            record_resource_id="foo",
            record_checksum_sha256="c" * 64,
            parser_version_seen="build/parsers/foo.py@v1.0.0",
        ),
    )
    monkeypatch.chdir(tmp_path)
    rc = review_state._cli(["dump", "data/foo.json"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Sidecar for foo" in captured.out
    assert "No entry-level review activity yet." in captured.out
