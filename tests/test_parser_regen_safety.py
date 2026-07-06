import json
from pathlib import Path

from build.lib import review_state
from build.lib.parser_regen_safety import merge_definition_block_regen, merge_single_field_regen
from build.tools import rekey_review_state


def test_no_correction_structured_change_display_follows_and_no_layer():
    entry, events = merge_single_field_regen(
        previous_entry=None,
        parsed_entry={
            "entry_id": "adam-clarke.2John.1.1",
            "commentary_text": "new structured",
        },
    )

    assert entry["commentary_text"] == "new structured"
    assert "layers" not in entry
    assert events[0]["field_path"] == "commentary_text"


def test_correction_exists_structured_change_preserves_corrected_display():
    entry, events = merge_single_field_regen(
        previous_entry={
            "entry_id": "adam-clarke.2John.1.1",
            "commentary_text": "corrected display",
        },
        parsed_entry={
            "entry_id": "adam-clarke.2John.1.1",
            "commentary_text": "new structured",
        },
        corrections={("adam-clarke.2John.1.1", "commentary_text")},
    )

    assert entry["commentary_text"] == "corrected display"
    assert entry["layers"]["commentary_text"]["structured"] == "new structured"
    assert entry["layers"]["commentary_text"]["display"] == "corrected display"
    assert events[0]["event_type"] == "parser_regenerated_field"


def test_field_path_removed_surfaces_orphan_and_preserves_sidecar_audit(tmp_path: Path):
    sidecar_dir = tmp_path / "review" / "state"
    sidecar_path = sidecar_dir / "reference" / "record.json"
    payload = review_state.empty_sidecar(
        record_path="data/reference/record.json",
        record_resource_id="fixture",
        record_checksum_sha256="0" * 64,
        parser_version_seen="parser@v1",
    )
    payload["entries"]["entry.old"] = {
        "warnings_acknowledged": [],
        "warnings_dismissed": [
            {
                "producer": "ocr_scanner",
                "code": "x",
                "signature": "sig",
                "signature_version": "v1",
                "reason": "false_positive",
            }
        ],
    }
    review_state.save_sidecar(sidecar_path, payload)
    manifest = tmp_path / "field.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "parser": "parser",
                "from_version": "v1",
                "to_version": "v2",
                "remap": {},
                "orphaned_field_paths": ["entry.old|definition_blocks.removed"],
            }
        ),
        encoding="utf-8",
    )

    counts = rekey_review_state.run(
        manifests=[manifest],
        review_state_dir=sidecar_dir,
        ledger_dir=tmp_path / "review" / "corrections",
    )
    migrated = review_state.load_sidecar(sidecar_path)

    assert counts["orphan_warnings"] == 1
    assert migrated["entries"]["entry.old"]["warnings_dismissed"][0]["signature"] == "sig"
    assert migrated["dead_letter"][0]["code"] == "correction_orphaned_by_parser"


def test_content_hash_block_id_change_migrates_correction_reference(tmp_path: Path):
    sidecar_dir = tmp_path / "review" / "state"
    sidecar_path = sidecar_dir / "reference" / "record.json"
    review_state.save_sidecar(
        sidecar_path,
        review_state.empty_sidecar(
            record_path="data/reference/record.json",
            record_resource_id="fixture",
            record_checksum_sha256="0" * 64,
            parser_version_seen="parser@v1",
        ),
    )
    ledger_dir = tmp_path / "review" / "corrections"
    ledger_dir.mkdir(parents=True)
    ledger = {
        "schema_version": "1.0.0",
        "correction_id": "c1",
        "resource_id": "fixture",
        "record_path": "data/reference/record.json",
        "entry_id": "entry.1",
        "field_path": "definition_blocks.oldhash",
        "correction_type": "text",
        "blocker": "none",
        "before_text": "a",
        "after_text": "b",
        "status": "proposed",
        "created_at": "2026-05-12T10:00:00+00:00",
    }
    (ledger_dir / "fixture.jsonl").write_text(json.dumps(ledger) + "\n", encoding="utf-8")
    manifest = tmp_path / "field.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "parser": "parser",
                "from_version": "v1",
                "to_version": "v2",
                "remap": {
                    "entry.1|definition_blocks.oldhash": "entry.1|definition_blocks.newhash"
                },
                "orphaned_field_paths": [],
            }
        ),
        encoding="utf-8",
    )

    counts = rekey_review_state.run(
        manifests=[manifest],
        review_state_dir=sidecar_dir,
        ledger_dir=ledger_dir,
    )
    migrated = json.loads((ledger_dir / "fixture.jsonl").read_text(encoding="utf-8"))

    assert counts["ledger_lines_changed"] == 1
    assert counts["orphan_warnings"] == 0
    assert migrated["field_path"] == "definition_blocks.newhash"


def test_anchor_change_migrates_sidecar_and_ledger_without_orphan(tmp_path: Path):
    sidecar_dir = tmp_path / "review" / "state"
    sidecar_path = sidecar_dir / "reference" / "record.json"
    payload = review_state.empty_sidecar(
        record_path="data/reference/record.json",
        record_resource_id="fixture",
        record_checksum_sha256="0" * 64,
        parser_version_seen="parser@v1",
    )
    payload["entries"]["entry.old"] = {"warnings_acknowledged": [], "warnings_dismissed": []}
    review_state.save_sidecar(sidecar_path, payload)
    ledger_dir = tmp_path / "review" / "corrections"
    ledger_dir.mkdir(parents=True)
    ledger = {
        "schema_version": "1.0.0",
        "correction_id": "c1",
        "resource_id": "fixture",
        "record_path": "data/reference/record.json",
        "entry_id": "entry.old",
        "field_path": "definition_blocks.hash",
        "correction_type": "text",
        "blocker": "none",
        "before_text": "a",
        "after_text": "b",
        "status": "proposed",
        "created_at": "2026-05-12T10:00:00+00:00",
    }
    (ledger_dir / "fixture.jsonl").write_text(json.dumps(ledger) + "\n", encoding="utf-8")
    manifest = tmp_path / "anchor.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "parser": "parser",
                "from_version": "v1",
                "to_version": "v2",
                "slug_algorithm_version_from": 1,
                "slug_algorithm_version_to": 2,
                "remap": {"entry.old": "entry.new"},
                "orphaned": [],
            }
        ),
        encoding="utf-8",
    )

    counts = rekey_review_state.run(
        manifests=[manifest],
        review_state_dir=sidecar_dir,
        ledger_dir=ledger_dir,
    )
    sidecar = review_state.load_sidecar(sidecar_path)
    migrated = json.loads((ledger_dir / "fixture.jsonl").read_text(encoding="utf-8"))

    assert "entry.new" in sidecar["entries"]
    assert migrated["entry_id"] == "entry.new"
    assert counts["orphan_warnings"] == 0


def test_definition_block_correction_merge_preserves_display_and_audit():
    entry, events = merge_definition_block_regen(
        previous_entry={
            "entry_id": "entry.1",
            "term": "Term",
            "definition_blocks": ["corrected"],
        },
        parsed_entry={
            "entry_id": "entry.1",
            "term": "Term",
            "alt_terms": [],
            "definition_blocks": ["structured"],
        },
        corrections={("entry.1", "definition_blocks.0")},
    )

    assert entry["definition_blocks"] == ["corrected"]
    assert entry["layers"]["definition_blocks"]
    assert events[0]["display"] == "corrected"
