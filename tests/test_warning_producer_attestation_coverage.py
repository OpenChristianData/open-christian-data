from __future__ import annotations

import copy


EXPECTED_CODE = "ATTESTATION_BELOW_THRESHOLD"


def _record() -> dict:
    return {
        "meta": {"id": "sample/work/edition", "schema_type": "reconciled_record"},
        "blocks": [
            {
                "block_id": "b1",
                "attested_by": ["source-a"],
                "structural_disagreements": [{"kind": "block_missing_in_source"}],
            }
        ],
    }


def _codes(output: dict) -> set[str]:
    return {warning["code"] for warning in output["warnings"]}


def test_attestation_below_threshold_fires() -> None:
    from build.lib.warning_producers import attestation_coverage

    output = attestation_coverage.run(_record(), {"resource_id": "sample"}, {})

    assert EXPECTED_CODE in _codes(output)


def test_attestation_complete_is_clean() -> None:
    from build.lib.warning_producers import attestation_coverage

    record = copy.deepcopy(_record())
    record["blocks"][0]["attested_by"] = ["source-a", "source-b"]

    output = attestation_coverage.run(record, {"resource_id": "sample"}, {})

    assert EXPECTED_CODE not in _codes(output)
