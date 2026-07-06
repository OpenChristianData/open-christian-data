from __future__ import annotations

import copy


EXPECTED_CODE = "ATTESTED_BY_REFERENCE_UNRESOLVED"


def _record() -> dict:
    return {
        "meta": {"id": "sample/work/edition", "schema_type": "reconciled_record"},
        "blocks": [{"block_id": "b1", "attested_by": ["source-missing"]}],
    }


def _codes(output: dict) -> set[str]:
    return {warning["code"] for warning in output["warnings"]}


def test_attested_by_reference_resolution() -> None:
    from build.lib.warning_producers import attested_by_reference_resolution

    catalog = {"renderings": [{"rendering_id": "source-a"}]}
    missing = attested_by_reference_resolution.run(_record(), {"resource_id": "sample", "catalog": catalog}, {})
    clean_record = copy.deepcopy(_record())
    clean_record["blocks"][0]["attested_by"] = ["source-a"]
    clean = attested_by_reference_resolution.run(clean_record, {"resource_id": "sample", "catalog": catalog}, {})

    assert EXPECTED_CODE in _codes(missing)
    assert EXPECTED_CODE not in _codes(clean)
