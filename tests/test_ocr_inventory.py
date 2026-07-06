import json
import sys
from pathlib import Path

import jsonschema

from build.tools.ocr_pipeline.ocr_inventory import (
    build_inventory,
    compute_coverage,
    resolve_present_leaf_nums,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_resolve_leaf_keyed_ids_to_leaf_nums() -> None:
    result = resolve_present_leaf_nums(["leaf_0007", "leaf_12"], {1: 101})

    assert result["leaf_nums"] == [7, 12]
    assert result["unresolved"] == []
    assert result["key_style"] == "leaf"


def test_resolve_page_keyed_ids_through_page_to_leaf() -> None:
    result = resolve_present_leaf_nums(["page_0001", "page_0002"], {1: 37, 2: 38})

    assert result["leaf_nums"] == [37, 38]
    assert result["unresolved"] == []
    assert result["key_style"] == "page"


def test_unmapped_page_id_is_recorded_as_unresolved() -> None:
    result = resolve_present_leaf_nums(["page_0001", "page_9999"], {1: 37})

    assert result["leaf_nums"] == [37]
    assert result["unresolved"] == ["page_9999"]
    assert result["key_style"] == "page"


def test_mixed_ids_choose_dominant_resolved_style() -> None:
    result = resolve_present_leaf_nums(
        ["leaf_0007", "page_0001", "page_0002", "page_9999"],
        {1: 37, 2: 38},
    )

    assert result["leaf_nums"] == [7, 37, 38]
    assert result["unresolved"] == ["page_9999"]
    assert result["key_style"] == "page"


def test_coverage_counts_missing_and_extra_leaf_nums() -> None:
    coverage = compute_coverage(
        expected_body={10, 11, 12},
        present_ids=["leaf_0010", "leaf_0012", "leaf_0099"],
        page_to_leaf={},
    )

    assert coverage["expected"] == 3
    assert coverage["present"] == 3
    assert coverage["covered"] == 2
    assert coverage["missing_count"] == 1
    assert coverage["extra_count"] == 1
    assert coverage["missing_leaf_nums"] == [11]
    assert coverage["extra_leaf_nums"] == [99]


def test_empty_present_means_all_expected_are_missing() -> None:
    coverage = compute_coverage(expected_body={10, 11}, present_ids=[], page_to_leaf={})

    assert coverage["present"] == 0
    assert coverage["covered"] == 0
    assert coverage["missing_count"] == 2
    assert coverage["extra_count"] == 0
    assert coverage["missing_leaf_nums"] == [10, 11]


def test_failed_s1_entries_are_counted_as_failed_not_covered() -> None:
    coverage = compute_coverage(
        expected_body={10, 11},
        present_ids=["leaf_0010", "leaf_0011"],
        page_to_leaf={},
        failed_ids=["leaf_0011"],
    )

    assert coverage["present"] == 1
    assert coverage["covered"] == 1
    assert coverage["failed"] == 1
    assert coverage["missing_count"] == 1
    assert coverage["missing_leaf_nums"] == [11]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _tiny_source_manifest(volume: int) -> dict:
    return {
        "ia_item_id": "test-nsh",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": volume,
        "created_at": "2026-06-12T00:00:00Z",
        "page_count": 2,
        "leaves": [
            {
                "leaf_num": 3,
                "page_num": None,
                "kind": "front_matter",
                "image_state": "present",
            },
            {"leaf_num": 10, "page_num": 1, "kind": "body", "image_state": "present"},
            {"leaf_num": 11, "page_num": 2, "kind": "body", "image_state": "present"},
        ],
    }


def _write_tiny_repo(repo_root: Path) -> None:
    source_manifest = _tiny_source_manifest(1)
    source_schema = json.loads(
        (REPO_ROOT / "schemas" / "v1" / "source_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(source_manifest, source_schema)
    _write_json(
        repo_root / "raw/internet-archive/schaff-herzog-pages/vol_01.manifest.json",
        source_manifest,
    )
    _write_json(
        repo_root / "reports/s1-sidecars/test-lineage/vol_01/manifest.json",
        {
            "schema_version": "sidecar-manifest-v1",
            "rendering_id": "test-rendering",
            "engine_family": "tesseract",
            "engine_version": "test",
            "source_lineage_id": "test-lineage",
            "volume": 1,
            "pages": [
                {
                    "page_native_id": "leaf_0010",
                    "page_sequence": 1,
                    "sidecar_page_path": "reports/s1-sidecars/test-lineage/vol_01/pages/leaf_0010.json",
                    "status": "eligible",
                    "source_payload_sha256": "sha256:" + "a" * 64,
                },
                {
                    "page_native_id": "leaf_0003",
                    "page_sequence": 2,
                    "sidecar_page_path": "reports/s1-sidecars/test-lineage/vol_01/pages/leaf_0003.json",
                    "status": "eligible",
                    "source_payload_sha256": "sha256:" + "b" * 64,
                },
                {
                    "page_native_id": "leaf_0011",
                    "page_sequence": 3,
                    "sidecar_page_path": "reports/s1-sidecars/test-lineage/vol_01/pages/leaf_0011.json",
                    "status": "eligible",
                    "source_payload_sha256": "sha256:" + "c" * 64,
                },
            ],
        },
    )
    _write_json(
        repo_root / "reports/s2-renderings/vol_01/test-lineage/index.json",
        {
            "schema_version": "rendering-index-v1",
            "source_lineage_id": "test-lineage",
            "volume": 1,
            "pages": ["leaf_0010"],
        },
    )
    _write_json(
        repo_root / "data/reference/schaff/encyclopedia/1908-1914/tesseract/vol_01.json",
        {"records": []},
    )
    _write_json(
        repo_root / "raw/internet-archive/schaff-herzog-pages/vol_01/page_0001.azure.json",
        {"text": "legacy"},
    )


def test_build_inventory_from_disk_counts_cells_and_witnesses(tmp_path: Path) -> None:
    _write_tiny_repo(tmp_path)

    index = build_inventory(tmp_path, volumes=[1], generated_at="2026-06-12T00:00:00Z")

    volume = index["volumes"]["vol_01"]
    assert volume["denominator"]["expected_ocr_body_leaves"] == 2
    assert volume["stage_summary"] == {
        "s1": {"lineages_present": 1},
        "s2": {"lineages_present": 1},
    }

    s1 = next(cell for cell in volume["cells"] if cell["stage"] == "s1")
    assert s1["expected"] == 2
    assert s1["present"] == 3
    assert s1["covered"] == 2
    assert s1["missing_count"] == 0
    assert s1["extra_count"] == 1
    assert s1["failed"] == 0
    assert s1["covered_leaf_nums"] == [10, 11]
    assert s1["covered_leaf_nums_truncated"] is False
    assert s1["missing_leaf_nums"] == []
    assert s1["extra_leaf_nums"] == [3]

    s2 = next(cell for cell in volume["cells"] if cell["stage"] == "s2")
    assert s2["covered"] == 1
    assert s2["s2_lag"] == 1
    assert s2["missing_leaf_nums"] == [11]

    witnesses = {(w["store"], w["volume"]) for w in index["witnesses"]}
    assert witnesses == {("legacy_gen1", 1), ("legacy_unnormalized", 1)}


def test_build_inventory_is_deterministic(tmp_path: Path) -> None:
    _write_tiny_repo(tmp_path)

    first = build_inventory(tmp_path, volumes=[1], generated_at="2026-06-12T00:00:00Z")
    second = build_inventory(tmp_path, volumes=[1], generated_at="2026-06-12T00:00:00Z")

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_inventory_schema_accepts_generated_fixture_index(tmp_path: Path) -> None:
    _write_tiny_repo(tmp_path)
    index = build_inventory(tmp_path, volumes=[1], generated_at="2026-06-12T00:00:00Z")
    schema = json.loads(
        (REPO_ROOT / "schemas" / "v1" / "ocr-inventory-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )

    jsonschema.validate(index, schema)
