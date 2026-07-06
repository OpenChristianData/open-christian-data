from __future__ import annotations

import copy


EXPECTED_CODE = "PAIRED_RECORD_INVARIANT"


def _original() -> dict:
    return {
        "meta": {"id": "sample/original/vol-01", "schema_type": "reconciled_record"},
        "blocks": [
            {
                "block_id": "b1",
                "language_segments": [
                    {
                        "span": {"start_token": 0, "end_token": 1},
                        "language": "grc",
                        "original_script": "αγαπη",
                        "transliteration": "agape",
                        "transliterated_from": "grc",
                    }
                ],
            }
        ],
    }


def _modernised() -> dict:
    record = copy.deepcopy(_original())
    record["meta"] = {
        "id": "sample/modernised/vol-01",
        "schema_type": "modernised_record",
        "paired_with": "sample/original/vol-01",
    }
    return record


def _codes(output: dict) -> set[str]:
    return {warning["code"] for warning in output["warnings"]}


def test_paired_record_invariant() -> None:
    from build.lib.warning_producers import paired_record_invariant

    original = _original()
    clean = _modernised()
    block_count_mismatch = _modernised()
    block_count_mismatch["blocks"].append({"block_id": "b2", "language_segments": []})
    block_id_mismatch = _modernised()
    block_id_mismatch["blocks"][0]["block_id"] = "b9"
    missing_meta = _modernised()
    del missing_meta["meta"]["paired_with"]
    segment_mismatch = _modernised()
    segment_mismatch["blocks"][0]["language_segments"][0]["language"] = "hbo"

    meta = {"resource_id": "sample", "paired_record": original}

    assert EXPECTED_CODE in _codes(paired_record_invariant.run(block_count_mismatch, meta, {}))
    assert EXPECTED_CODE in _codes(paired_record_invariant.run(block_id_mismatch, meta, {}))
    assert EXPECTED_CODE in _codes(paired_record_invariant.run(missing_meta, meta, {}))
    assert EXPECTED_CODE in _codes(paired_record_invariant.run(segment_mismatch, meta, {}))
    assert EXPECTED_CODE not in _codes(paired_record_invariant.run(clean, meta, {}))
