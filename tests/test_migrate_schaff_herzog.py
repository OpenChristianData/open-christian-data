from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from ocd_kernel.lib.schema_enums import resolve_schema_path


def _source_record() -> dict:
    return {
        "meta": {
            "id": "schaff-herzog-volume-1",
            "title": "Schaff-Herzog Encyclopedia of Religious Knowledge, Volume 1",
            "schema_version": "2.0.0",
            "schema_type": "reference_entry",
        },
        "entries": [
            {
                "entry_id": "aaron",
                "headword": "Aaron",
                "body": "Aaron was the elder brother of Moses.",
                "annotations": {"entry_key": "AARON", "volume": 1},
                "summary": "Generated summary to be removed.",
                "key_quote": "Generated quote to be removed.",
            },
            {
                "entry_id": "abaddon",
                "headword": "Abaddon",
                "body": "A name occurring in Hebrew scripture.",
                "annotations": {"entry_key": "ABADDON", "volume": 1},
            },
        ],
    }


def _write_source_fixture(tmp_path: Path, record: dict | None = None) -> Path:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_path = source_dir / "volume-1.json"
    source_path.write_text(json.dumps(record or _source_record(), indent=2), encoding="utf-8")
    return source_dir


def _work_paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "output_root": tmp_path / "data" / "reference" / "schaff" / "encyclopedia" / "1908-1914",
        "workbench_root": tmp_path / "review" / "state",
        "catalog_path": tmp_path / "data" / "reference" / "schaff" / "encyclopedia" / "1908-1914" / "catalog.json",
        "audit_path": tmp_path / "review" / "audit.jsonl",
    }


def _run_fixture_migration(tmp_path: Path) -> dict[str, Path]:
    from build.tools.migrate_schaff_herzog import migrate_records

    source_dir = _write_source_fixture(tmp_path)
    paths = _work_paths(tmp_path)
    migrate_records(source_dir=source_dir, **paths)
    return paths


def _load_first_migrated_record(paths: dict[str, Path]) -> dict:
    migrated_path = paths["output_root"] / "original" / "volume-1.json"
    return json.loads(migrated_path.read_text(encoding="utf-8"))


def _record_text(record: dict) -> str:
    return "".join(block["original_text"] for block in record["blocks"])


def test_block_count_preservation_where_applicable(tmp_path):
    paths = _run_fixture_migration(tmp_path)
    migrated = _load_first_migrated_record(paths)
    kept_input_entries = [entry for entry in _source_record()["entries"] if entry.get("body")]

    assert len(migrated["blocks"]) == len(kept_input_entries)
    assert [block["block_type"] for block in migrated["blocks"]] == ["headword", "headword"]


def test_text_concatenation_equality(tmp_path):
    paths = _run_fixture_migration(tmp_path)
    migrated = _load_first_migrated_record(paths)
    expected = "".join(entry["headword"] + "\n" + entry["body"] for entry in _source_record()["entries"])
    actual = _record_text(migrated)

    assert actual == expected, f"text concatenation changed: {actual!r} != {expected!r}"


def test_annotation_presence(tmp_path):
    paths = _run_fixture_migration(tmp_path)
    migrated = _load_first_migrated_record(paths)
    expected_annotations = [entry["annotations"] for entry in _source_record()["entries"]]

    assert [block["annotations"] for block in migrated["blocks"]] == expected_annotations


def test_old_to_new_review_state_mapping_count(tmp_path):
    from build.tools.migrate_schaff_herzog import migrate_records

    source_dir = _write_source_fixture(tmp_path)
    paths = _work_paths(tmp_path)
    paths["workbench_root"].mkdir(parents=True)
    old_workbench = paths["workbench_root"] / "volume-1.workbench.json"
    old_workbench.write_text(
        json.dumps(
            {
                "entries": {
                    "aaron": {"decision": {"status": "accepted", "note": "Keep entry."}},
                    "abaddon": {"decision": {"status": "accepted", "note": "Keep entry."}},
                }
            }
        ),
        encoding="utf-8",
    )

    migrate_records(source_dir=source_dir, **paths)
    new_workbench = json.loads((paths["workbench_root"] / "original" / "volume-1.workbench.json").read_text(encoding="utf-8"))

    assert len(new_workbench["entries"]) == 2
    assert [entry["decision"] for entry in new_workbench["entries"].values()] == [
        {"status": "accepted", "note": "Keep entry."},
        {"status": "accepted", "note": "Keep entry."},
    ]


def test_schema_validation_post_migration(tmp_path):
    paths = _run_fixture_migration(tmp_path)
    record = _load_first_migrated_record(paths)
    record_schema = json.loads(resolve_schema_path("reconciled_record").read_text(encoding="utf-8"))

    jsonschema.validate(instance=record, schema=record_schema)
    assert not list((paths["output_root"] / "modernised").glob("*.json"))


def test_audit_append_validation(tmp_path):
    paths = _run_fixture_migration(tmp_path)
    audit_schema = json.loads(resolve_schema_path("audit_event").read_text(encoding="utf-8"))
    audit_lines = paths["audit_path"].read_text(encoding="utf-8").splitlines()
    sizes = []

    for line in audit_lines:
        jsonschema.validate(instance=json.loads(line), schema=audit_schema)
        sizes.append(len(line))

    assert len(audit_lines) == len(_source_record()["entries"])
    assert sizes == sorted(sizes)


def test_r70_migration_resumes_after_post_anchor_abort(tmp_path, monkeypatch):
    from ocd_kernel.lib import atomic_io
    from build.tools.migrate_schaff_herzog import MigrationAborted, migrate_records

    source_dir = _write_source_fixture(tmp_path)
    paths = _work_paths(tmp_path)
    real_write_json_atomic = atomic_io.write_json_atomic
    write_calls = {"record": 0}

    def abort_on_second_record(target_path, payload, schema):
        if str(target_path).endswith(".json") and "blocks" in payload:
            write_calls["record"] += 1
            if write_calls["record"] == 2:
                raise MigrationAborted("simulated post-anchor abort")
        return real_write_json_atomic(target_path, payload, schema)

    monkeypatch.setattr(atomic_io, "write_json_atomic", abort_on_second_record)
    try:
        migrate_records(source_dir=source_dir, **paths)
    except MigrationAborted:
        pass

    monkeypatch.setattr(atomic_io, "write_json_atomic", real_write_json_atomic)
    migrate_records(source_dir=source_dir, **paths)
    audit_lines = paths["audit_path"].read_text(encoding="utf-8").splitlines()

    assert len(audit_lines) == len(_source_record()["entries"])


def test_r68_migration_drops_summary_and_key_quote_fields(tmp_path):
    paths = _run_fixture_migration(tmp_path)
    migrated = _load_first_migrated_record(paths)

    assert "summary" not in migrated
    assert "key_quote" not in migrated
    assert all(not block["block_type"].startswith(("summary", "key_quote")) for block in migrated["blocks"])
