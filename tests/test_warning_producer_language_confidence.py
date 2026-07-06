from __future__ import annotations

import copy


BLOCK_CODE = "LANG_BLOCK_NEEDS_REVIEW"
RECORD_CODE = "LANG_RECORD_NEEDS_REVIEW"


def _record() -> dict:
    return {
        "meta": {"id": "sample/work/edition", "schema_type": "reconciled_record"},
        "blocks": [
            {
                "block_id": "b1",
                "language": "en",
                "language_confidence": 0.59,
            }
        ],
    }


def _codes(output: dict) -> set[str]:
    return {warning["code"] for warning in output["warnings"]}


def test_lang_block_needs_review_fires_for_low_confidence() -> None:
    from build.lib.warning_producers import language_confidence

    output = language_confidence.run(_record(), {"resource_id": "sample"}, {})

    assert BLOCK_CODE in _codes(output)


def test_lang_block_needs_review_is_clean_at_threshold() -> None:
    from build.lib.warning_producers import language_confidence

    record = copy.deepcopy(_record())
    record["blocks"][0]["language_confidence"] = 0.60

    output = language_confidence.run(record, {"resource_id": "sample"}, {})

    assert BLOCK_CODE not in _codes(output)


def test_lang_record_needs_review_fires_when_any_block_flags() -> None:
    from build.lib.warning_producers import language_confidence

    record = _record()
    record["blocks"].append({"block_id": "b2", "language": "en", "language_confidence": 0.98})

    output = language_confidence.run(record, {"resource_id": "sample"}, {})

    assert RECORD_CODE in _codes(output)


def test_lang_record_needs_review_is_clean_when_all_blocks_clean() -> None:
    from build.lib.warning_producers import language_confidence

    record = _record()
    record["blocks"][0]["language_confidence"] = 0.98

    output = language_confidence.run(record, {"resource_id": "sample"}, {})

    assert RECORD_CODE not in _codes(output)
