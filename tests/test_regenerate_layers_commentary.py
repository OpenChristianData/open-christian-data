import json
from pathlib import Path

from build.lib.text_layers import assert_record_surface_field_invariant
from build.lib.pytest_skips import skip_if_missing_data
from build.parsers import helloao_commentary


def test_clarke_2_john_regenerated_with_observed_layers(tmp_path: Path):
    skip_if_missing_data(
        helloao_commentary.LOCAL_RAW_DIR / "c" / "adam-clarke" / "2JN" / "1.json"
    )
    config = helloao_commentary.load_config("adam-clarke")
    out_dir = tmp_path / "commentaries" / "adam-clarke"

    stats = helloao_commentary.process_book(
        config,
        "2JN",
        out_dir,
        dry_run=False,
        emit_layers=True,
    )

    assert stats["file"] == "2-john.json"
    payload = json.loads((out_dir / "2-john.json").read_text(encoding="utf-8"))
    assert payload["meta"]["text_layer_shape"] == "single_field"
    layered_entries = [entry for entry in payload["data"] if entry.get("layers")]
    assert layered_entries
    assert {
        entry["layers"]["commentary_text"]["source_raw_origin"]
        for entry in layered_entries
    } == {"observed"}
    assert_record_surface_field_invariant(payload)
