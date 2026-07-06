import json
from pathlib import Path

import pytest

from build.lib.text_layers import (
    SurfaceFieldInvariantViolation,
    assert_record_surface_field_invariant,
    assert_surface_field_invariant,
    build_reference_layers,
)
from build.lib.pytest_skips import skip_if_missing_data
from build.parsers import helloao_commentary, ia_schaff_herzog


def test_single_field_invariant_rejects_out_of_sync_display():
    entry = {
        "entry_id": "adam-clarke.2John.1.1",
        "commentary_text": "surface",
        "layers": {
            "commentary_text": {
                "source_raw": "structured",
                "normalised": "structured",
                "structured": "structured",
                "display": "corrected",
                "source_raw_origin": "observed",
            }
        },
    }
    with pytest.raises(SurfaceFieldInvariantViolation):
        assert_surface_field_invariant(entry, text_layer_shape="single_field")


def test_clarke_2_john_surface_invariant_passes(tmp_path: Path):
    skip_if_missing_data(
        helloao_commentary.LOCAL_RAW_DIR / "c" / "adam-clarke" / "2JN" / "1.json"
    )
    config = helloao_commentary.load_config("adam-clarke")
    helloao_commentary.process_book(config, "2JN", tmp_path, emit_layers=True)
    payload = json.loads((tmp_path / "2-john.json").read_text(encoding="utf-8"))
    assert_record_surface_field_invariant(payload)


def test_schaff_slice_surface_invariant_passes():
    entry = ia_schaff_herzog.build_entry(
        {
            "term": "AARON",
            "definition_blocks": ["Normalised block"],
            "source_raw_definition_blocks": ["Normalised  block"],
            "vol_num": 3,
        },
        set(),
        emit_layers=True,
    )
    payload = {
        "meta": {"text_layer_shape": "multi_field"},
        "data": [entry],
    }
    assert_record_surface_field_invariant(payload)


def test_multi_field_invariant_rejects_out_of_sync_block():
    layers = build_reference_layers(
        term="Term",
        definition_blocks=["structured"],
        display_blocks=["display"],
    )
    entry = {
        "entry_id": "schaff-herzog.term",
        "term": "Term",
        "alt_terms": [],
        "definition_blocks": ["surface"],
        "layers": layers,
    }
    with pytest.raises(SurfaceFieldInvariantViolation):
        assert_surface_field_invariant(entry, text_layer_shape="multi_field")


def test_record_invariant_skips_unmigrated_records_without_shape():
    """Pre-Phase-C records have no meta.text_layer_shape and no layers; skip."""
    record = {
        "meta": {"id": "x", "schema_type": "commentary"},
        "data": [{"entry_id": "x.1", "commentary_text": "hi"}],
    }
    assert_record_surface_field_invariant(record)


def test_invariant_rejects_layer_keyed_by_wrong_block_id_even_if_display_matches():
    """A-F9: a layer keyed by the wrong content hash must NOT pass the
    invariant just because its stored display equals the current block.
    The pre-fix code had a display-equality fallback that softened the
    content-hash contract."""
    # Build layers with a deliberately wrong key — not the content hash of
    # "surface" — but whose display matches "surface" anyway.
    layers = {
        "definition_blocks": {
            "deadbeef": {  # wrong block_id
                "source_raw": "surface",
                "normalised": "surface",
                "structured": "surface",
                "display": "surface",
                "source_raw_origin": "observed",
            }
        }
    }
    entry = {
        "entry_id": "tst.term",
        "term": "Term",
        "alt_terms": [],
        "definition_blocks": ["surface"],
        "layers": layers,
    }
    with pytest.raises(SurfaceFieldInvariantViolation):
        assert_surface_field_invariant(entry, text_layer_shape="multi_field")


def test_record_invariant_raises_on_layer_bearing_record_without_shape():
    """A record that has entries with layers must declare meta.text_layer_shape."""
    record = {
        "meta": {"id": "x"},
        "data": [
            {
                "entry_id": "x.1",
                "commentary_text": "hi",
                "layers": {
                    "commentary_text": {
                        "source_raw": "hi",
                        "normalised": "hi",
                        "structured": "hi",
                        "display": "hi",
                        "source_raw_origin": "observed",
                    }
                },
            }
        ],
    }
    with pytest.raises(SurfaceFieldInvariantViolation):
        assert_record_surface_field_invariant(record)
