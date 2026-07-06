from __future__ import annotations

import json
from pathlib import Path

from build.tools.ocr_pipeline.reconcile_page_classes import (
    PRIMARY_LINEAGES,
    classify_page,
    classify_volume,
    classify_volume_details,
)


def _manifest(leaves: list[dict], gaps: list[dict], volume: int = 1) -> dict:
    return {
        "volume": volume,
        "page_count": max(
            [leaf["page_num"] for leaf in leaves if isinstance(leaf.get("page_num"), int)]
            + [gap["page_num"] for gap in gaps if isinstance(gap.get("page_num"), int)]
            + [0]
        ),
        "leaves": leaves,
        "gaps": gaps,
    }


def _leaf(page_num: int, leaf_num: int, sha: str | None = None) -> dict:
    leaf = {
        "kind": "body",
        "image_state": "present",
        "page_num": page_num,
        "leaf_num": leaf_num,
    }
    if sha is not None:
        leaf["sha256"] = sha
    return leaf


def _gap(page_num: int, sha: str | None = None, status: str = "stale_status") -> dict:
    gap = {"page_num": page_num, "status": status}
    if sha is not None:
        gap["sha256"] = sha
    return gap


def _write_image(repo_root: Path, volume: int, page_num: int, payload: bytes = b"img") -> None:
    path = (
        repo_root
        / "raw"
        / "internet-archive"
        / "schaff-herzog-pages"
        / f"vol_{volume:02d}"
        / f"page_{page_num:04d}.jpg"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_sidecar(
    repo_root: Path,
    lineage: str,
    volume: int,
    page_num: int,
    canonical_leaf_id: int | None,
    *,
    clid_exempt: bool = False,
) -> None:
    path = (
        repo_root
        / "reports"
        / "s1-sidecars"
        / lineage
        / f"vol_{volume:02d}"
        / "pages"
        / f"page_{page_num:04d}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "page_native_id": f"page_{page_num:04d}",
        "canonical_leaf_id": canonical_leaf_id,
        "source_payload_sha256": f"sha256:{page_num:04x}",
    }
    if clid_exempt:
        record["clid_exempt"] = True
    path.write_text(json.dumps(record), encoding="utf-8")


def test_vol01_9398_regression(tmp_path: Path) -> None:
    manifest = _manifest(
        leaves=[
            _leaf(93, 129, "sha256:0093"),
            _leaf(94, 130, "sha256:0094"),
            _leaf(95, 131, "sha256:0095"),
            _leaf(98, 132, "sha256:0098"),
        ],
        gaps=[
            _gap(94),
            _gap(95),
            _gap(96, "sha256:0096"),
            _gap(97, "sha256:0097"),
        ],
        volume=1,
    )
    for page_num in range(94, 99):
        _write_image(tmp_path, 1, page_num)
    for lineage in ("tesseract-py314-v1", "kraken-py312-v1"):
        _write_sidecar(tmp_path, lineage, 1, 94, 130)
        _write_sidecar(tmp_path, lineage, 1, 95, 131)
        _write_sidecar(tmp_path, lineage, 1, 96, None, clid_exempt=True)
        _write_sidecar(tmp_path, lineage, 1, 97, None)

    assert classify_volume(manifest, repo_root=tmp_path) == {
        "keyless_ocrd": [96, 97],
        "stale_gap_record": [94, 95],
        "image_not_ocrd": [],
        "true_hole": [],
    }


def test_four_classes_one_each(tmp_path: Path) -> None:
    manifest = _manifest(
        leaves=[_leaf(10, 110), _leaf(20, 120), _leaf(30, 130), _leaf(40, 140)],
        gaps=[_gap(10), _gap(20), _gap(30), _gap(40)],
        volume=2,
    )
    _write_image(tmp_path, 2, 10)
    _write_image(tmp_path, 2, 20)
    _write_image(tmp_path, 2, 30)
    _write_sidecar(tmp_path, PRIMARY_LINEAGES[0], 2, 10, None)
    _write_sidecar(tmp_path, PRIMARY_LINEAGES[0], 2, 20, 120)

    assert classify_volume(manifest, repo_root=tmp_path) == {
        "keyless_ocrd": [10],
        "stale_gap_record": [20],
        "image_not_ocrd": [30],
        "true_hole": [40],
    }


def test_true_hole_out_of_range_flag(tmp_path: Path) -> None:
    manifest = _manifest(
        leaves=[_leaf(10, 110), _leaf(20, 120)],
        gaps=[_gap(15), _gap(21)],
        volume=3,
    )

    details = {detail["page_num"]: detail for detail in classify_volume_details(manifest, tmp_path)}

    assert details[15]["class"] == "true_hole"
    assert details[15]["out_of_range"] is False
    assert details[21]["class"] == "true_hole"
    assert details[21]["out_of_range"] is True


def test_classify_page_pure() -> None:
    assert classify_page(
        sidecar_present=True,
        sidecar_clid=None,
        img_present=True,
        gap_present=True,
    ) == "keyless_ocrd"
    assert classify_page(
        sidecar_present=False,
        sidecar_clid=None,
        img_present=True,
        gap_present=True,
    ) != "keyless_ocrd"

    assert classify_page(
        sidecar_present=True,
        sidecar_clid=130,
        img_present=True,
        gap_present=True,
    ) == "stale_gap_record"
    assert classify_page(
        sidecar_present=True,
        sidecar_clid=130,
        img_present=True,
        gap_present=False,
    ) == "ok"

    assert classify_page(
        sidecar_present=False,
        sidecar_clid=None,
        img_present=True,
        gap_present=True,
    ) == "image_not_ocrd"
    assert classify_page(
        sidecar_present=True,
        sidecar_clid=None,
        img_present=True,
        gap_present=True,
    ) != "image_not_ocrd"

    assert classify_page(
        sidecar_present=False,
        sidecar_clid=None,
        img_present=False,
        gap_present=True,
    ) == "true_hole"
    assert classify_page(
        sidecar_present=False,
        sidecar_clid=None,
        img_present=False,
        gap_present=False,
    ) == "ok"


def test_classes_mutually_exclusive(tmp_path: Path) -> None:
    manifest = _manifest(
        leaves=[_leaf(1, 101), _leaf(2, 102), _leaf(3, 103), _leaf(4, 104)],
        gaps=[_gap(1), _gap(2), _gap(3), _gap(4)],
        volume=4,
    )
    _write_image(tmp_path, 4, 1)
    _write_image(tmp_path, 4, 2)
    _write_image(tmp_path, 4, 3)
    _write_sidecar(tmp_path, PRIMARY_LINEAGES[0], 4, 1, None)
    _write_sidecar(tmp_path, PRIMARY_LINEAGES[0], 4, 2, 102)

    classified = classify_volume(manifest, repo_root=tmp_path)
    seen = [page for pages in classified.values() for page in pages]

    assert sorted(seen) == [1, 2, 3, 4]
    assert len(seen) == len(set(seen))
