"""Tests for the NSH unified leaf-sequence accessor (build/lib/nsh_leaf_model.py).

The accessor is the single API every NSH source-manifest consumer reads through.
It derives from the new ``leaves[]`` shape when present and falls back to the
legacy ``pages[]`` + ``unnumbered_leaves[]`` shape when absent, so consumers can
move to it BEFORE any manifest is migrated (design
docs/DESIGN_nsh_leaf_sequence_manifest.md, the P0.5 foundation).

R-consumer-window: a fallback that reads empty is the failure mode, so both
shapes are asserted non-empty -- a real on-disk legacy manifest AND a hand-built
v4 fixture.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.nsh_leaf_model import (  # noqa: E402
    back_matter,
    body_pages,
    canonical_leaf_id,
    derive_kind,
    discarded,
    expected_image_name,
    front_matter,
    gap_by_sha,
    leaf_by_sha,
    leaves_view,
    ocr_input,
    ocr_input_in_order,
    plates,
    resolve_leaf,
    body_leaf_sha_duplicates,
)
from build.lib.pytest_skips import skip_if_missing_data  # noqa: E402

NSH_BASE = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
# vol_03 on disk is now v4 (P2-migrated), so reading it no longer exercises the
# accessor's legacy pages[]+unnumbered_leaves[] fallback. _legacy_manifest()
# below is a synthetic legacy-shape fixture reproducing vol_03's pre-P2 structure
# (500 body pages on primary leaves 23..522, front offset 22, with the leading-run
# double-record on leaves 23..31 that the de-overlap must drop). Audit 2026-06-15.
CANONICAL_LEAF_ID_FIELD = {
    "type": "integer",
    "minimum": 0,
    "description": "Canonical primary-scan leaf coordinate (leaf_num), engine-agnostic and not the filename.",
}


def _legacy_manifest() -> dict:
    pages = [
        {"page_num": p, "ia_leaf_id": f"{p + 22:04d}",
         "local_path": f"raw/internet-archive/schaff-herzog-pages/vol_99/page_{p:04d}.jpg"}
        for p in range(1, 501)
    ]
    # Leaves 0..22 are genuine front matter; 23..31 double-record body pages 1..9
    # (inside the 23..522 body span) and MUST be de-overlapped; 523/524 are back.
    unnumbered = [
        {"leaf_num": n,
         "local_path": f"raw/internet-archive/schaff-herzog-pages/vol_99/leaf_{n:04d}.jpg"}
        for n in list(range(0, 32)) + [523, 524]
    ]
    return {"volume": 99, "pages": pages, "unnumbered_leaves": unnumbered}


def _v4_fixture() -> dict:
    """A hand-built v4 manifest exercising all five kinds.

    first_body leaf = 23 (page 1); last_body leaf = 25 (page 3). A plate sits at
    leaf 24 inside the body span between pages... no -- to keep body contiguous,
    body leaves are 23/25/26, the plate at leaf 24 follows page 1, front at 0,
    back at 99, a discarded duplicate at leaf 50.
    """
    return {
        "ia_item_id": "newschaffherzo99test",
        "ia_derivative_type": "jp2",
        "volume": 99,
        "created_at": "2026-06-11T00:00:00+00:00",
        "leaves": [
            {
                "leaf_num": 0,
                "page_num": None,
                "kind": "front_matter",
                "image_state": "present",
                "local_path": "raw/internet-archive/schaff-herzog-pages/vol_99/leaf_0000.jpg",
                "ia_leaf_id": "0000",
                "ia_filename": "x_jp2/x_0000.jp2",
                "ia_item_id": "newschaffherzo99test",
                "sha256": "sha256:" + "0" * 64,
                "fetched_at": "2026-06-11T00:00:00+00:00",
                "image_mode": "L",
                "image_size": [100, 200],
            },
            {
                "leaf_num": 23,
                "page_num": 1,
                "kind": "body",
                "image_state": "present",
                "local_path": "raw/internet-archive/schaff-herzog-pages/vol_99/page_0001.jpg",
                "ia_leaf_id": "0023",
                "ia_filename": "x_jp2/x_0023.jp2",
                "ia_item_id": "newschaffherzo99test",
                "sha256": "sha256:" + "1" * 64,
                "fetched_at": "2026-06-11T00:00:00+00:00",
                "image_mode": "L",
                "image_size": [100, 200],
            },
            {
                "leaf_num": 24,
                "page_num": None,
                "kind": "plate",
                "after_page_num": 1,
                "image_state": "present",
                "local_path": "raw/internet-archive/schaff-herzog-pages/vol_99/plate_0001_01.jpg",
                "ia_leaf_id": "0024",
                "ia_filename": "x_jp2/x_0024.jp2",
                "ia_item_id": "newschaffherzo99test",
                "sha256": "sha256:" + "2" * 64,
                "fetched_at": "2026-06-11T00:00:00+00:00",
                "image_mode": "RGB",
                "image_size": [100, 200],
            },
            {
                "leaf_num": 25,
                "page_num": 2,
                "kind": "body",
                "image_state": "present",
                "local_path": "raw/internet-archive/schaff-herzog-pages/vol_99/page_0002.jpg",
                "ia_leaf_id": "0025",
                "ia_filename": "x_jp2/x_0025.jp2",
                "ia_item_id": "newschaffherzo99test",
                "sha256": "sha256:" + "3" * 64,
                "fetched_at": "2026-06-11T00:00:00+00:00",
                "image_mode": "L",
                "image_size": [100, 200],
            },
            {
                "leaf_num": 50,
                "page_num": None,
                "kind": "discarded",
                "image_state": "not_imaged",
                "discard_reason": "exact duplicate of printed 2",
                "duplicate_of_page": 2,
            },
            {
                "leaf_num": 99,
                "page_num": None,
                "kind": "back_matter",
                "image_state": "pending",
            },
        ],
    }


def _shared_body_sha_manifest() -> dict:
    shared_sha = "sha256:" + "a" * 64
    return {
        "leaves": [
            {
                "leaf_num": 1,
                "page_num": 1,
                "kind": "body",
                "image_state": "present",
                "local_path": "raw/internet-archive/schaff-herzog-pages/vol_99/page_0001.jpg",
                "sha256": shared_sha,
            },
            {
                "leaf_num": 2,
                "page_num": 2,
                "kind": "body",
                "image_state": "present",
                "local_path": "raw/internet-archive/schaff-herzog-pages/vol_99/page_0002.jpg",
                "sha256": shared_sha,
            },
        ]
    }


# --- derive_kind (the pure function, design SS1.5) -------------------------


def test_derive_kind_body_when_page_num_present():
    leaf = {"leaf_num": 30, "page_num": 8}
    assert derive_kind(leaf, first_body=23, last_body=522) == "body"


def test_derive_kind_front_matter_below_first_body():
    leaf = {"leaf_num": 5, "page_num": None}
    assert derive_kind(leaf, first_body=23, last_body=522) == "front_matter"


def test_derive_kind_back_matter_above_last_body():
    leaf = {"leaf_num": 525, "page_num": None}
    assert derive_kind(leaf, first_body=23, last_body=522) == "back_matter"


def test_derive_kind_plate_null_page_inside_body_span():
    leaf = {"leaf_num": 100, "page_num": None}
    assert derive_kind(leaf, first_body=23, last_body=522) == "plate"


def test_derive_kind_discarded_when_discard_reason_present():
    # discard_reason wins even with a page_num present.
    leaf = {"leaf_num": 100, "page_num": 50, "discard_reason": "dup"}
    assert derive_kind(leaf, first_body=23, last_body=522) == "discarded"


# --- v4 shape --------------------------------------------------------------


def test_leaves_view_v4_returns_all_leaves_sorted():
    m = _v4_fixture()
    view = leaves_view(m)
    assert len(view) == 6
    assert [leaf["leaf_num"] for leaf in view] == [0, 23, 24, 25, 50, 99]


def test_v4_kind_selectors():
    m = _v4_fixture()
    assert [leaf["page_num"] for leaf in body_pages(m)] == [1, 2]
    assert [leaf["leaf_num"] for leaf in front_matter(m)] == [0]
    assert [leaf["leaf_num"] for leaf in back_matter(m)] == [99]
    assert [leaf["leaf_num"] for leaf in plates(m)] == [24]
    assert [leaf["leaf_num"] for leaf in discarded(m)] == [50]


def test_v4_ocr_input_is_body_only():
    m = _v4_fixture()
    ocr = ocr_input(m)
    assert [leaf["page_num"] for leaf in ocr] == [1, 2]
    # never plate/discarded/front/back
    assert all(leaf["kind"] == "body" for leaf in ocr)


def test_v4_ocr_input_opt_in_front_back():
    m = _v4_fixture()
    ocr = ocr_input(m, include_front_back=True)
    kinds = {leaf["kind"] for leaf in ocr}
    assert kinds == {"body", "front_matter", "back_matter"}
    # plates and discarded are NEVER included, even with the opt-in
    assert "plate" not in kinds
    assert "discarded" not in kinds


def test_v4_non_empty():
    # R-consumer-window: the v4 path must not read empty.
    m = _v4_fixture()
    assert body_pages(m)
    assert leaves_view(m)


def test_leaf_by_sha_indexes_all_sha_bearing_leaves():
    m = _v4_fixture()

    by_sha = leaf_by_sha(m)

    assert all(len(leaves) == 1 for leaves in by_sha.values())
    assert by_sha["sha256:" + "1" * 64][0]["leaf_num"] == 23
    assert {leaf["leaf_num"] for leaves in by_sha.values() for leaf in leaves} == {0, 23, 24, 25}
    assert 50 not in {leaf["leaf_num"] for leaves in by_sha.values() for leaf in leaves}
    assert 99 not in {leaf["leaf_num"] for leaves in by_sha.values() for leaf in leaves}


def test_gap_by_sha_indexes_resolved_gap_records():
    # The P2 recovered-gap model (schema 4.1.0) records a printed page the primary
    # scan skipped -- recovered from an alternate scan -- as a gap_record in gaps[],
    # carrying its sha256 but NO leaf_num. gap_by_sha indexes those by content sha so
    # a consumer can tell "real recovered body page with no spine leaf" apart from a
    # genuinely-unresolvable sha.
    m = {
        "schema_version": "source-manifest-v4",
        "volume": 1,
        "leaves": [
            {"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:" + "a" * 64},
        ],
        "gaps": [
            {"page_num": 96, "status": "resolved", "sha256": "sha256:" + "b" * 64},
            {"page_num": 200, "status": "missing"},  # no sha -> not indexable
        ],
    }

    by_sha = gap_by_sha(m)

    assert set(by_sha) == {"sha256:" + "b" * 64}
    assert by_sha["sha256:" + "b" * 64]["page_num"] == 96


def test_gap_by_sha_empty_when_no_gaps_key():
    assert gap_by_sha({"leaves": []}) == {}


def test_ocr_input_in_order_adds_current_stem_without_mutation():
    m = _v4_fixture()

    ordered = ocr_input_in_order(m)

    assert [leaf["page_num"] for leaf in ordered] == [1, 2]
    assert [leaf["current_stem"] for leaf in ordered] == ["page_0001", "page_0002"]
    assert [leaf["sha256"] for leaf in ordered] == ["sha256:" + "1" * 64, "sha256:" + "3" * 64]
    assert all("current_stem" not in leaf for leaf in ocr_input(m))


def test_resolve_leaf_by_unique_sha():
    m = _v4_fixture()

    assert resolve_leaf(m, "sha256:" + "1" * 64) == (23, 1, "page_0001")


def test_resolve_leaf_raises_for_unknown_sha():
    with pytest.raises(ValueError, match="0"):
        resolve_leaf(_v4_fixture(), "sha256:" + "9" * 64)


def test_resolve_leaf_raises_for_duplicate_sha():
    shared_sha = "sha256:" + "a" * 64

    with pytest.raises(ValueError, match="2"):
        resolve_leaf(_shared_body_sha_manifest(), shared_sha)


def test_body_leaf_sha_duplicates_empty_for_fixture():
    assert body_leaf_sha_duplicates(_v4_fixture()) == {}


def test_body_leaf_sha_duplicates_reports_shared_body_sha():
    shared_sha = "sha256:" + "a" * 64

    duplicates = body_leaf_sha_duplicates(_shared_body_sha_manifest())

    assert list(duplicates) == [shared_sha]
    assert [leaf["leaf_num"] for leaf in duplicates[shared_sha]] == [1, 2]


def test_canonical_leaf_id_reconciles_leaf_and_page_keys():
    m = {
        "leaves": [
            {"leaf_num": 3, "page_num": None, "kind": "front_matter"},
            {"leaf_num": 10, "page_num": 1, "kind": "body"},
        ]
    }

    assert canonical_leaf_id("leaf_0010", m) == 10
    assert canonical_leaf_id("page_0001", m) == 10


def test_canonical_leaf_id_returns_none_for_unresolved_ids():
    m = {
        "leaves": [
            {"leaf_num": 10, "page_num": 1, "kind": "body"},
        ]
    }

    assert canonical_leaf_id("leaf_9999", m) is None
    assert canonical_leaf_id("page_9999", m) is None
    assert canonical_leaf_id("not-a-page", m) is None


# --- legacy shape (synthetic pages[]+unnumbered_leaves[] fallback) ---------


def test_legacy_body_pages_non_empty():
    # R-consumer-window: the legacy fallback must not read empty.
    m = _legacy_manifest()
    body = body_pages(m)
    assert len(body) == 500
    assert all(leaf["kind"] == "body" for leaf in body)
    assert all(leaf["page_num"] is not None for leaf in body)


def test_legacy_front_matter_non_empty_and_de_overlapped():
    m = _legacy_manifest()
    front = front_matter(m)
    # vol_03 front unnumbered leaf_nums are 0..31; leaves 23..31 double-record
    # body pages 1..9 and MUST be dropped from front (design SS4.3).
    assert front, "front matter must not be empty for vol_03"
    front_leaf_nums = {leaf["leaf_num"] for leaf in front}
    assert max(front_leaf_nums) < 23, "leaves 23..31 must not appear as front matter"
    assert all(leaf["kind"] == "front_matter" for leaf in front)


def test_legacy_de_overlap_no_leaf_recorded_twice():
    m = _legacy_manifest()
    view = leaves_view(m)
    leaf_nums = [leaf["leaf_num"] for leaf in view]
    assert len(leaf_nums) == len(set(leaf_nums)), "every physical leaf appears once"
    # leaf 23 is body (page 1), not also front matter
    leaf23 = [leaf for leaf in view if leaf["leaf_num"] == 23]
    assert len(leaf23) == 1
    assert leaf23[0]["kind"] == "body"
    assert leaf23[0]["page_num"] == 1


def test_legacy_back_matter_present():
    m = _legacy_manifest()
    back = back_matter(m)
    assert back, "back matter must not be empty for vol_03"
    assert all(leaf["kind"] == "back_matter" for leaf in back)
    assert min(leaf["leaf_num"] for leaf in back) > 522


def test_legacy_plates_and_discarded_empty():
    # Legacy manifests have no plate/discarded concept.
    m = _legacy_manifest()
    assert plates(m) == []
    assert discarded(m) == []


def test_legacy_ocr_input_body_only():
    m = _legacy_manifest()
    ocr = ocr_input(m)
    assert len(ocr) == 500
    assert all(leaf["kind"] == "body" for leaf in ocr)


@pytest.mark.parametrize("volume", ["vol_02", "vol_10", "vol_11"])
def test_real_v4_body_leaf_sha_duplicates_absent(volume):
    manifest_path = NSH_BASE / f"{volume}.manifest.json"
    skip_if_missing_data(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert body_leaf_sha_duplicates(manifest) == {}


def test_legacy_leaves_view_sorted_by_leaf_num():
    m = _legacy_manifest()
    view = leaves_view(m)
    leaf_nums = [leaf["leaf_num"] for leaf in view]
    assert leaf_nums == sorted(leaf_nums)


# --- expected_image_name (consumed by s0_ingest) ---------------------------


def test_expected_image_name_body_is_page_jpg():
    leaf = {"leaf_num": 23, "page_num": 1, "kind": "body"}
    assert expected_image_name(leaf) == "page_0001.jpg"


def test_expected_image_name_front_back_is_leaf_jpg():
    leaf = {"leaf_num": 5, "page_num": None, "kind": "front_matter"}
    assert expected_image_name(leaf) == "leaf_0005.jpg"


def test_expected_image_name_plate_uses_local_path_basename():
    leaf = {
        "leaf_num": 24,
        "page_num": None,
        "kind": "plate",
        "local_path": "raw/.../vol_99/plate_0001_01.jpg",
    }
    assert expected_image_name(leaf) == "plate_0001_01.jpg"


def test_expected_image_name_discarded_is_none():
    leaf = {"leaf_num": 50, "page_num": None, "kind": "discarded"}
    assert expected_image_name(leaf) is None


@pytest.mark.parametrize(
    ("schema_path", "properties_path", "required_path"),
    [
        (
            Path("schemas/v1/sidecar-page-v1.schema.json"),
            ("properties",),
            ("required",),
        ),
        (
            Path("schemas/v1/rendering-v1.schema.json"),
            ("$defs", "rendered_page", "properties"),
            ("$defs", "rendered_page", "required"),
        ),
        (
            Path("schemas/v1/word-confusion-table-v1.schema.json"),
            ("properties",),
            ("required",),
        ),
    ],
)
def test_page_level_schemas_accept_optional_canonical_leaf_id(
    schema_path: Path,
    properties_path: tuple[str, ...],
    required_path: tuple[str, ...],
):
    schema = json.loads((REPO_ROOT / schema_path).read_text(encoding="utf-8"))
    properties = schema
    for key in properties_path:
        properties = properties[key]
    required = schema
    for key in required_path:
        required = required[key]

    assert properties["canonical_leaf_id"] == CANONICAL_LEAF_ID_FIELD
    assert "canonical_leaf_id" not in required
