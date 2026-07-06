from __future__ import annotations

import copy


EXPECTED_CODE = "TRANSLITERATION_INCOMPLETE"


def _record() -> dict:
    return {
        "meta": {"id": "sample/work/edition", "schema_type": "reconciled_record"},
        "blocks": [
            {
                "block_id": "b1",
                "language": "en",
                "original_text": "The Greek word αγαπη appears here.",
                "language_segments": [],
            }
        ],
    }


def _codes(output: dict) -> set[str]:
    return {warning["code"] for warning in output["warnings"]}


def test_transliteration_incomplete_fires_for_unsegmented_source_script() -> None:
    from build.lib.warning_producers import transliteration_completeness

    output = transliteration_completeness.run(_record(), {"resource_id": "sample"}, {})

    assert EXPECTED_CODE in _codes(output)


def test_transliteration_complete_is_clean() -> None:
    from build.lib.warning_producers import transliteration_completeness

    record = copy.deepcopy(_record())
    record["blocks"][0]["language_segments"] = [
        {
            "span": {"start_token": 3, "end_token": 4},
            "language": "grc",
            "original_script": "αγαπη",
            "transliteration": "agape",
        }
    ]

    output = transliteration_completeness.run(record, {"resource_id": "sample"}, {})

    assert EXPECTED_CODE not in _codes(output)
