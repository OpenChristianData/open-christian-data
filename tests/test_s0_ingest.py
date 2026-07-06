"""Tests for Schaff-Herzog S0 ingest bijection and integrity gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.s0_ingest import (  # noqa: E402
    _expected_image_names,
    available_engines_for_volume,
    build_page_leaf_bijection,
    corpus_page_count,
    load_volume_manifest,
    s0_integrity_check,
)


def _v4_manifest_with_recovered_gap() -> dict:
    """A v4 manifest where printed page 3 was recovered from an alternate scan
    (Scenario A): it has an on-disk image + a gaps[] entry with local_path, but
    NO spine leaf. It must NOT read as missing, and its page_0003.jpg must NOT
    read as an orphan."""
    def _leaf(leaf_num: int, page_num: int) -> dict:
        return {"leaf_num": leaf_num, "page_num": page_num, "kind": "body",
                "image_state": "present",
                "local_path": f"raw/x/vol_99/page_{page_num:04d}.jpg",
                "ia_leaf_id": f"{leaf_num:04d}", "ia_filename": "x.jp2",
                "ia_item_id": "prim", "sha256": "sha256:" + "0" * 64,
                "fetched_at": "2026-06-06T00:00:00+00:00",
                "image_mode": "L", "image_size": [10, 10]}
    return {
        "volume": 99, "page_count": 5,
        "leaves": [_leaf(10, 1), _leaf(11, 2), _leaf(13, 4), _leaf(14, 5)],
        "gaps": [{
            "page_num": 3, "status": "resolved",
            "investigation_note": "recovered from alternate item hg",
            "resolved_from": "hg",
            "local_path": "raw/x/vol_99/page_0003.jpg",
            "ia_leaf_id": "0128", "ia_filename": "hg.jp2", "ia_item_id": "hg",
            "sha256": "sha256:" + "1" * 64,
            "fetched_at": "2026-06-06T00:00:00+00:00",
            "image_mode": "L", "image_size": [10, 10],
        }],
    }


def test_recovered_gap_not_listed_missing():
    """A recovered no-leaf body page (gaps[] with local_path) is present, not a
    body gap -- neither the gap-set nor the range-fill may mark it missing."""
    mf = _v4_manifest_with_recovered_gap()
    bijection = build_page_leaf_bijection(mf)
    assert 3 not in bijection["missing_pages"]


def test_recovered_gap_image_is_expected_not_orphan():
    """The recovered page's page_0003.jpg is an expected image, so the on-disk
    orphan check (actual - expected) does not false-flag it."""
    mf = _v4_manifest_with_recovered_gap()
    assert "page_0003.jpg" in _expected_image_names(mf)


def _manifest(
    volume: int,
    numbered_count: int,
    unnumbered_count: int = 0,
    gaps: list[dict] | None = None,
    duplicate_leaf: bool = False,
) -> dict:
    pages = []
    for index in range(numbered_count):
        leaf_id = f"{index + 100:04d}"
        if duplicate_leaf and index == numbered_count - 1:
            leaf_id = "0064"
        pages.append(
            {
                "page_num": index + 1,
                "ia_leaf_id": leaf_id,
                "ia_filename": f"synthetic_{leaf_id}.jp2",
            }
        )
    if duplicate_leaf and pages:
        pages[0]["ia_leaf_id"] = "0064"

    unnumbered_leaves = [
        {
            "leaf_num": index,
            "page_num": None,
            "page_type": "Normal",
            "section": "front_matter",
            "ia_leaf_id": f"{index:04d}",
            "ia_filename": f"synthetic_front_{index:04d}.jp2",
            "local_path": (
                "raw/internet-archive/schaff-herzog-pages/"
                f"vol_{volume:02d}/leaf_{index:04d}.jpg"
            ),
        }
        for index in range(unnumbered_count)
    ]

    return {
        "volume": volume,
        "ia_item_id": f"synthetic-vol-{volume}",
        "ia_derivative_type": "jp2",
        "created_at": "2026-05-29T00:00:00+00:00",
        "page_count": None,
        "pages": pages,
        "unnumbered_leaves": unnumbered_leaves,
        "gaps": gaps or [],
        "manifest_warnings": (
            ["duplicate ia_leaf_id 0064: mapped to page_num values [1, 4]"]
            if duplicate_leaf
            else []
        ),
    }


def _write_manifest_tree(
    repo_root: Path,
    manifest: dict,
    *,
    missing_images: set[str] | None = None,
) -> Path:
    volume = manifest["volume"]
    raw_dir = repo_root / "raw" / "internet-archive" / "schaff-herzog-pages"
    volume_dir = raw_dir / f"vol_{volume:02d}"
    volume_dir.mkdir(parents=True)
    manifest_path = raw_dir / f"vol_{volume:02d}.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    missing = missing_images or set()
    for page in manifest["pages"]:
        image_name = f"page_{page['page_num']:04d}.jpg"
        if image_name not in missing:
            (volume_dir / image_name).write_text("image", encoding="utf-8")
    for leaf in manifest["unnumbered_leaves"]:
        image_name = f"leaf_{leaf['leaf_num']:04d}.jpg"
        if image_name not in missing:
            (volume_dir / image_name).write_text("image", encoding="utf-8")
    return manifest_path


def test_bijection_holds_on_synthetic_volume(tmp_path: Path) -> None:
    manifest = _manifest(volume=1, numbered_count=4, unnumbered_count=2)
    manifest_path = _write_manifest_tree(tmp_path, manifest)

    loaded = load_volume_manifest(manifest_path)
    bijection = build_page_leaf_bijection(loaded)
    flags = s0_integrity_check(1, tmp_path)

    assert bijection["numbered_page_count"] == 4
    assert bijection["unnumbered_leaf_count"] == 2
    assert bijection["total_leaf_count"] == 6
    assert bijection["duplicate_leaf_ids"] == []
    assert bijection["missing_pages"] == []
    assert flags == []


def test_missing_leaf_hard_flags(tmp_path: Path) -> None:
    manifest = _manifest(
        volume=1,
        numbered_count=3,
        gaps=[
            {
                "page_num": 2,
                "status": "unresolved",
                "investigation_note": "synthetic missing page",
            }
        ],
    )
    _write_manifest_tree(tmp_path, manifest, missing_images={"page_0002.jpg"})

    bijection = build_page_leaf_bijection(manifest)
    flags = s0_integrity_check(1, tmp_path)

    assert bijection["missing_pages"] == [2]
    assert flags
    assert {flag.kind for flag in flags} >= {"page_gap", "manifest_entry_without_image"}


def test_duplicate_leaf_hard_flags(tmp_path: Path) -> None:
    manifest = _manifest(volume=1, numbered_count=4, duplicate_leaf=True)
    _write_manifest_tree(tmp_path, manifest)

    bijection = build_page_leaf_bijection(manifest)
    flags = s0_integrity_check(1, tmp_path)

    assert bijection["duplicate_leaf_ids"] == ["0064"]
    assert any(flag.kind == "duplicate_leaf" for flag in flags)


def test_page_count_emitted_from_bijection_not_constant(tmp_path: Path) -> None:
    first = _manifest(volume=1, numbered_count=2)
    second = _manifest(volume=2, numbered_count=5)
    _write_manifest_tree(tmp_path, first)
    _write_manifest_tree(tmp_path, second)

    counts = corpus_page_count(tmp_path)

    assert counts["per_volume"] == {"1": 2, "2": 5}
    assert counts["corpus_numbered_page_count"] == 7


def test_available_engines_reflects_present_sources_only(tmp_path: Path) -> None:
    manifest = _manifest(volume=1, numbered_count=1)
    _write_manifest_tree(tmp_path, manifest)
    volume_dir = (
        tmp_path
        / "raw"
        / "internet-archive"
        / "schaff-herzog-pages"
        / "vol_01"
    )
    (volume_dir / "page_0001.ia-abbyy-dli.json").write_text(
        json.dumps({"text": "alpha"}),
        encoding="utf-8",
    )

    available = available_engines_for_volume(1, tmp_path)

    assert available == {"page_0001": ["ia-abbyy-dli"]}


def test_available_engines_accepts_assembled_pages_with_data_count(
    tmp_path: Path,
) -> None:
    manifest = _manifest(volume=1, numbered_count=1)
    _write_manifest_tree(tmp_path, manifest)
    lineage_dir = (
        tmp_path
        / "data"
        / "reference"
        / "schaff"
        / "encyclopedia"
        / "1908-1914"
        / "azure-v1"
    )
    lineage_dir.mkdir(parents=True)
    (lineage_dir / "vol_01.json").write_text(
        json.dumps(
            {
                "page_count": 2,
                "pages_with_data": 1,
                "pages": [
                    {"page": 3, "text": "alpha"},
                    {"page": 4, "text": ""},
                ],
            }
        ),
        encoding="utf-8",
    )

    available = available_engines_for_volume(1, tmp_path)

    assert available == {"page_0003": ["azure-v1"]}


@pytest.mark.skipif(
    not (
        REPO_ROOT
        / "raw"
        / "internet-archive"
        / "schaff-herzog-pages"
        / "vol_01.manifest.json"
    ).exists(),
    reason="raw/ not downloaded",
)
def test_vol_01_bijection_real_data() -> None:
    manifest_path = (
        REPO_ROOT
        / "raw"
        / "internet-archive"
        / "schaff-herzog-pages"
        / "vol_01.manifest.json"
    )
    manifest = load_volume_manifest(manifest_path)
    bijection = build_page_leaf_bijection(manifest)

    assert bijection["numbered_page_count"] > 0
    # After the Model-B rebuild, leaf 0037 is used exactly once (page 1, primary).
    # The old hand-edited false-leaf-id manifest had it duplicated; the corrected
    # manifest has no duplicate leaf ids.
    assert bijection["duplicate_leaf_ids"] == []
