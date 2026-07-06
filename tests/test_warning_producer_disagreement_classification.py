from __future__ import annotations

import copy


EXPECTED_CODE = "DISAGREEMENT_UNCLASSIFIED"


def _record() -> dict:
    return {
        "meta": {"id": "sample/work/edition", "schema_type": "reconciled_record"},
        "blocks": [
            {
                "block_id": "b1",
                "disagreements": [
                    {
                        "span": {"start_token": 0, "end_token": 1},
                        "kind": "unclassified",
                        "chosen_reading": "word",
                        "chosen_reading_attested_by": ["source-a"],
                    }
                ],
            }
        ],
    }


def _codes(output: dict) -> set[str]:
    return {warning["code"] for warning in output["warnings"]}


def test_disagreement_unclassified_fires() -> None:
    from build.lib.warning_producers import disagreement_classification

    output = disagreement_classification.run(_record(), {"resource_id": "sample"}, {})

    assert EXPECTED_CODE in _codes(output)


def test_classified_disagreement_is_clean() -> None:
    from build.lib.warning_producers import disagreement_classification

    record = copy.deepcopy(_record())
    record["blocks"][0]["disagreements"][0]["kind"] = "ocr_noise"

    output = disagreement_classification.run(record, {"resource_id": "sample"}, {})

    assert EXPECTED_CODE not in _codes(output)
