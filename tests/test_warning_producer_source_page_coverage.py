from __future__ import annotations

import copy


EXPECTED_CODE = "SOURCE_PAGE_COVERAGE_MISSING"


def _record() -> dict:
    return {
        "meta": {
            "id": "sample/work/edition",
            "schema_type": "reconciled_record",
            "pd_anchor": "source-a",
        },
        "blocks": [{"block_id": "b1", "source_pages": []}],
    }


def _codes(output: dict) -> set[str]:
    return {warning["code"] for warning in output["warnings"]}


def test_source_page_coverage_checker() -> None:
    from build.lib.warning_producers import source_page_coverage

    missing = source_page_coverage.run(_record(), {"resource_id": "sample"}, {})
    clean_record = copy.deepcopy(_record())
    clean_record["blocks"][0]["source_pages"] = [{"rendering_id": "source-a", "page_number": 1}]
    clean = source_page_coverage.run(clean_record, {"resource_id": "sample"}, {})

    assert EXPECTED_CODE in _codes(missing)
    assert EXPECTED_CODE not in _codes(clean)
