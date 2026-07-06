from __future__ import annotations

import json


EXPECTED_CODE = "PAIRED_WITH_REFERENCE_UNRESOLVED"


def _record(paired_with: str) -> dict:
    return {
        "meta": {
            "id": "sample/modernised/vol-01",
            "schema_type": "modernised_record",
            "paired_with": paired_with,
        },
        "blocks": [],
        "match_explanations": [],
    }


def _codes(output: dict) -> set[str]:
    return {warning["code"] for warning in output["warnings"]}


def test_paired_with_reference_resolution(tmp_path) -> None:
    from build.lib.warning_producers import paired_with_reference_resolution

    missing_path = tmp_path / "original" / "missing.json"
    missing = paired_with_reference_resolution.run(
        _record(str(missing_path)),
        {"resource_id": "sample", "record_path": str(tmp_path / "modernised" / "vol-01.json")},
        {},
    )

    original_path = tmp_path / "original" / "vol-01.json"
    modernised_path = tmp_path / "modernised" / "vol-01.json"
    original_path.parent.mkdir(parents=True)
    modernised_path.parent.mkdir(parents=True)
    original_path.write_text(
        json.dumps({"meta": {"id": "sample/original/vol-01", "paired_with": str(modernised_path)}, "blocks": []}),
        encoding="utf-8",
    )
    clean = paired_with_reference_resolution.run(
        _record(str(original_path)),
        {"resource_id": "sample", "record_path": str(modernised_path)},
        {},
    )

    assert EXPECTED_CODE in _codes(missing)
    assert EXPECTED_CODE not in _codes(clean)
