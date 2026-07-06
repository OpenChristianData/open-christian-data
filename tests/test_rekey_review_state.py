import json
from copy import deepcopy
from pathlib import Path

import jsonschema

from build.lib import review_state
from build.tools import rekey_review_state


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sidecar() -> dict:
    payload = review_state.empty_sidecar(
        record_path="data/reference/schaff-herzog-encyclopedia.json",
        record_resource_id="schaff-herzog-encyclopedia",
        record_checksum_sha256="0" * 64,
        parser_version_seen="build/parsers/ia_schaff_herzog.py@v1.0.0",
    )
    payload["entries"]["schaff-herzog.old"] = {
        "warnings_acknowledged": [],
        "warnings_dismissed": [
            {
                "producer": "ocr_scanner",
                "code": "digit_in_letter",
                "signature": "old-sig",
                "signature_version": "v1.0.0",
                "reason": "false_positive",
            }
        ],
    }
    return payload


def _ledger_entry() -> dict:
    return {
        "schema_version": "1.0.0",
        "correction_id": "c1",
        "resource_id": "schaff-herzog-encyclopedia",
        "record_path": "data/reference/schaff-herzog-encyclopedia.json",
        "entry_id": "schaff-herzog.old",
        "field_path": "definition_blocks.oldblock",
        "correction_type": "text",
        "blocker": "none",
        "before_text": "bad",
        "after_text": "good",
        "producer_warning_signature": "old-sig",
        "status": "proposed",
        "created_at": "2026-05-12T10:00:00+00:00",
    }


def _validate_warning_signature_remap_manifest(manifest: dict) -> None:
    schema_path = Path("schemas") / "v1" / "warning_signature_remap.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=manifest, schema=schema)


def test_remap_signature_passes_through_hex_when_no_map():
    signature = "2c26b46b68ffc68f"
    field_map = {("2c", "b4"): ("entry-new", "field-new")}
    assert any(token in signature for old_pair in field_map for token in old_pair)

    assert rekey_review_state._remap_signature(signature, {}) == signature


def test_remap_signature_applies_explicit_remap():
    assert rekey_review_state._remap_signature("old-sig", {"old-sig": "new-sig"}) == "new-sig"


def test_rekey_sidecar_with_warning_signature_remap_manifest(tmp_path: Path):
    manifest = {
        "schema_version": "1.0.0",
        "producer": "ocr_scanner",
        "from_signature_version": "v1",
        "to_signature_version": "v2",
        "remap_rule": "explicit",
        "explicit_remap": {"old-sig": "new-sig"},
    }
    _validate_warning_signature_remap_manifest(manifest)
    manifest_path = tmp_path / "signature.json"
    _write_json(manifest_path, manifest)
    _, _, field_map, orphaned_fields, signature_map = rekey_review_state._load_manifests([manifest_path])
    sidecar = _sidecar()
    expected = deepcopy(sidecar)
    expected["entries"]["schaff-herzog.old"]["warnings_dismissed"][0]["signature"] = "new-sig"

    migrated, changed = rekey_review_state._rekey_sidecar(
        sidecar,
        anchor_map={},
        orphaned_anchors=set(),
        field_map=field_map,
        orphaned_fields=orphaned_fields,
        signature_map=signature_map,
    )

    assert changed == 1
    assert migrated == expected


def test_rekey_review_state_migrates_anchor_field_path_and_signature(tmp_path: Path):
    sidecar_dir = tmp_path / "review" / "state"
    sidecar_path = sidecar_dir / "reference" / "schaff-herzog-encyclopedia.json"
    review_state.save_sidecar(sidecar_path, _sidecar())
    ledger_dir = tmp_path / "review" / "corrections"
    ledger_path = ledger_dir / "schaff-herzog-encyclopedia.jsonl"
    ledger_dir.mkdir(parents=True)
    ledger_path.write_text(json.dumps(_ledger_entry()) + "\n", encoding="utf-8")

    anchor_manifest = tmp_path / "anchor.json"
    field_manifest = tmp_path / "field.json"
    signature_manifest = tmp_path / "signature.json"
    _write_json(
        anchor_manifest,
        {
            "schema_version": "1.0.0",
            "parser": "build/parsers/ia_schaff_herzog.py",
            "from_version": "v1",
            "to_version": "v2",
            "slug_algorithm_version_from": 1,
            "slug_algorithm_version_to": 2,
            "remap": {"schaff-herzog.old": "schaff-herzog.new"},
            "orphaned": [],
        },
    )
    _write_json(
        field_manifest,
        {
            "schema_version": "1.0.0",
            "parser": "build/parsers/ia_schaff_herzog.py",
            "from_version": "v1",
            "to_version": "v2",
            "remap": {
                "schaff-herzog.old|definition_blocks.oldblock": "schaff-herzog.new|definition_blocks.newblock"
            },
            "orphaned_field_paths": [],
        },
    )
    _write_json(
        signature_manifest,
        {
            "schema_version": "1.0.0",
            "producer": "ocr_scanner",
            "from_signature_version": "v1",
            "to_signature_version": "v2",
            "remap_rule": "explicit",
            "explicit_remap": {"old-sig": "new-sig"},
        },
    )

    counts = rekey_review_state.run(
        manifests=[anchor_manifest, field_manifest, signature_manifest],
        review_state_dir=sidecar_dir,
        ledger_dir=ledger_dir,
    )

    assert counts["sidecars_changed"] == 1
    migrated = review_state.load_sidecar(sidecar_path)
    assert "schaff-herzog.new" in migrated["entries"]
    decision = migrated["entries"]["schaff-herzog.new"]["warnings_dismissed"][0]
    assert decision["signature"] == "new-sig"

    ledger = json.loads(ledger_path.read_text(encoding="utf-8").strip())
    assert ledger["entry_id"] == "schaff-herzog.new"
    assert ledger["field_path"] == "definition_blocks.newblock"
    assert ledger["producer_warning_signature"] == "new-sig"


def test_rekey_review_state_surfaces_orphan_field_paths(tmp_path: Path):
    sidecar_dir = tmp_path / "review" / "state"
    sidecar_path = sidecar_dir / "reference" / "schaff-herzog-encyclopedia.json"
    review_state.save_sidecar(sidecar_path, _sidecar())
    manifest = tmp_path / "field.json"
    _write_json(
        manifest,
        {
            "schema_version": "1.0.0",
            "parser": "build/parsers/ia_schaff_herzog.py",
            "from_version": "v1",
            "to_version": "v2",
            "remap": {},
            "orphaned_field_paths": ["schaff-herzog.old|definition_blocks.dead"],
        },
    )

    counts = rekey_review_state.run(
        manifests=[manifest],
        review_state_dir=sidecar_dir,
        ledger_dir=tmp_path / "review" / "corrections",
    )

    assert counts["orphan_warnings"] == 1
    migrated = review_state.load_sidecar(sidecar_path)
    assert migrated["dead_letter"][0]["code"] == "correction_orphaned_by_parser"
    assert migrated["dead_letter"][0]["entry_id"] == "schaff-herzog.old"
