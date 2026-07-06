from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from build.lib.warning_producers import METRIC_FIELDS, run_all_producers
from build.lib.warning_producers import ocr_scanner


def _record(pattern_set: str = "schaff-herzog") -> dict:
    return {
        "meta": {
            "id": "ocr-test",
            "schema_type": "reference_entry",
            "schema_version": "2.1.0",
            "scan_source": {"pattern_set": pattern_set},
        },
        "data": [
            {
                "entry_id": "ocr-test.theotokos",
                "term": "THE0T0K0S",
                "alt_terms": [],
                "definition_blocks": ["A theological term."],
            }
        ],
    }


def test_pattern_set_resolves_from_meta_scan_source() -> None:
    output = ocr_scanner.run(
        _record(),
        {"resource_id": "ocr-test", "resource_type": "encyclopedia"},
        {},
    )

    assert output["pattern_set"] == "ia_djvu"
    assert output["candidates"]
    assert output["warnings"][0]["code"] == "digit_in_letter"


def test_scanner_producer_uses_utc_timestamp_and_no_truncation() -> None:
    output = ocr_scanner.run(
        _record(),
        {"resource_id": "ocr-test", "resource_type": "encyclopedia"},
        {},
    )

    scanned_at = datetime.fromisoformat(output["scanned_at"])
    assert scanned_at.utcoffset().total_seconds() == 0
    assert output["truncated"] is False
    assert output["truncated_reason"] is None


def test_integration_against_schaff_herzog_config_shape() -> None:
    output = ocr_scanner.run(
        _record(),
        {"resource_id": "ocr-test", "resource_type": "encyclopedia"},
        {},
    )

    warning = output["warnings"][0]
    assert warning["entry_id"] == "ocr-test.theotokos"
    assert warning["field_path"] == "term"
    assert len(warning["evidence"]["snippet"]) <= 120
    assert warning["signature"]


def test_run_all_producers_writes_numeric_metrics() -> None:
    meta = {"resource_id": "ocr-test", "resource_type": "encyclopedia"}

    run_all_producers(_record(), meta, producers=[ocr_scanner])

    metrics_path = Path("review/producer-metrics/ocr_scanner/ocr-test.json")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert set(METRIC_FIELDS) <= set(metrics)
    assert all(isinstance(metrics[field], (int, float)) for field in METRIC_FIELDS)
