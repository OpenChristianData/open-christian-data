from __future__ import annotations

import json


EXPECTED_CODES = {
    "MOD_COVERAGE_MISSING",
    "MOD_RECORD_ORPHAN_ORIGINAL",
    "MOD_RECORD_ORPHAN_MODERNISED",
    "MOD_UNEXPECTED_MODERNISED",
}


def _codes(output: dict) -> set[str]:
    return {warning["code"] for warning in output["warnings"]}


def _write_json(path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_modernisation_coverage_consistency(tmp_path) -> None:
    from build.lib.warning_producers import modernisation_coverage_consistency

    work_dir = tmp_path / "work"
    original_path = work_dir / "original" / "vol-01.json"
    modernised_path = work_dir / "modernised" / "vol-01.json"
    orphan_modernised_path = work_dir / "modernised" / "vol-02.json"
    _write_json(original_path, {"meta": {"id": "sample/original/vol-01"}, "blocks": []})
    _write_json(modernised_path, {"meta": {"id": "sample/modernised/vol-01", "paired_with": str(original_path)}, "blocks": []})
    _write_json(orphan_modernised_path, {"meta": {"id": "sample/modernised/vol-02", "paired_with": str(work_dir / "original" / "vol-02.json")}, "blocks": []})

    missing = modernisation_coverage_consistency.run(
        {},
        {"resource_id": "sample", "work_dir": str(tmp_path / "missing"), "catalog": {"modernisation_intent": "intended"}},
        {},
    )
    orphan_original = modernisation_coverage_consistency.run(
        {},
        {
            "resource_id": "sample",
            "work_dir": str(work_dir),
            "catalog": {"modernisation_intent": "intended"},
            "original_records": [str(original_path), str(work_dir / "original" / "vol-02.json")],
        },
        {},
    )
    orphan_modernised = modernisation_coverage_consistency.run(
        {},
        {"resource_id": "sample", "work_dir": str(work_dir), "catalog": {"modernisation_intent": "intended"}},
        {},
    )
    unexpected = modernisation_coverage_consistency.run(
        {},
        {"resource_id": "sample", "work_dir": str(work_dir), "catalog": {"modernisation_intent": "not_applicable"}},
        {},
    )
    clean = modernisation_coverage_consistency.run(
        {},
        {
            "resource_id": "sample",
            "work_dir": str(work_dir),
            "catalog": {"modernisation_intent": "intended"},
            "original_records": [str(original_path)],
            "modernised_records": [str(modernised_path)],
        },
        {},
    )

    observed = _codes(missing) | _codes(orphan_original) | _codes(orphan_modernised) | _codes(unexpected)
    assert EXPECTED_CODES <= observed
    assert EXPECTED_CODES.isdisjoint(_codes(clean))
