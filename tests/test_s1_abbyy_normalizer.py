from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from build.parsers.s1_abbyy_normalizer import (  # noqa: E402
    normalize_abbyy_file,
    normalize_abbyy_rich_volume,
)

# Real raw ABBYY rich sidecar for vol_01 page_0010 -- gitignored; skip when absent
# (GitHub Actions runs against a clean checkout). The rich sidecars carry word
# bbox{x,y,w,h}, unlike the flattened data/reference assembled JSON.
_RAW_ABBYY_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
_REAL_ABBYY_PAGE10 = _RAW_ABBYY_ROOT / "vol_01" / "page_0010.ia-abbyy.json"

ABBYY_LINEAGES = [
    "ia-abbyy-v1",
    "ia-abbyy-dli-v1",
    "ia-abbyy-haucgoog-v1",
    "ia-abbyy-haucgoog-c1-v1",
    "ia-abbyy-haucgoog-c2-v1",
    "ia-abbyy-haucgoog-c3-v1",
    "ia-abbyy-haucgoog-c4-v1",
]


def _write_assembled(path: Path, lineage: str, *, pages: list[dict] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "rendering_id": f"{lineage}/schaff/encyclopedia/1908-1914/v1",
        "volume": 1,
        "engine_alias": lineage,
        "engine_version": "ABBYY FineReader",
        "page_count": len(pages or []),
        "pages_with_data": sum(1 for page in pages or [] if page.get("text")),
        "pages": pages or [],
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def test_abbyy_five_lineages_collapse_to_one_family(tmp_path: Path) -> None:
    output_root = tmp_path / "reports" / "s1-sidecars"
    manifests = []
    for lineage in ABBYY_LINEAGES:
        source = (
            tmp_path
            / "data"
            / "reference"
            / "schaff"
            / "encyclopedia"
            / "1908-1914"
            / lineage
            / "vol_01.json"
        )
        _write_assembled(source, lineage, pages=[{"page": 1, "text": "Grace peace"}])
        summary = normalize_abbyy_file(source, output_root=output_root, repo_root=tmp_path)
        manifests.append(summary.manifest)

    assert {manifest["engine_family"] for manifest in manifests} == {"abbyy"}
    assert {manifest["source_lineage_id"] for manifest in manifests} == set(ABBYY_LINEAGES)


def test_failure_class_recorded_not_swallowed(tmp_path: Path) -> None:
    source = tmp_path / "bad" / "vol_01.json"
    source.parent.mkdir(parents=True)
    source.write_text("[]", encoding="utf-8")

    summary = normalize_abbyy_file(
        source,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
        source_lineage_id="ia-abbyy-v1",
    )

    assert summary.failed_pages == 1
    assert summary.manifest["pages"][0]["failure_class"] == "malformed_assembled_json"
    assert summary.manifest["pages"][0]["status"] == "corrupt"


def test_rerun_resumes(tmp_path: Path) -> None:
    source = (
        tmp_path
        / "data"
        / "reference"
        / "schaff"
        / "encyclopedia"
        / "1908-1914"
        / "ia-abbyy-v1"
        / "vol_01.json"
    )
    _write_assembled(
        source,
        "ia-abbyy-v1",
        pages=[
            {"page": 1, "text": "Grace peace"},
            {"page": 2, "text": "Faith hope"},
        ],
    )
    output_root = tmp_path / "reports" / "s1-sidecars"

    first = normalize_abbyy_file(source, output_root=output_root, repo_root=tmp_path)
    second = normalize_abbyy_file(source, output_root=output_root, repo_root=tmp_path)

    assert first.emitted_pages == 2
    assert second.emitted_pages == 0
    assert second.skipped_pages == 2
    page_files = list((output_root / "ia-abbyy-v1" / "vol_01" / "pages").glob("*.json"))
    assert len(page_files) == 2


def test_duplicate_page_sequence_keeps_distinct_sidecars_and_tokens(tmp_path: Path) -> None:
    source = (
        tmp_path
        / "data"
        / "reference"
        / "schaff"
        / "encyclopedia"
        / "1908-1914"
        / "ia-abbyy-v1"
        / "vol_01.json"
    )
    _write_assembled(
        source,
        "ia-abbyy-v1",
        pages=[
            {"page": 2, "text": "Grace peace"},
            {"page": "leaf0000", "text": "Grace peace"},
        ],
    )
    output_root = tmp_path / "reports" / "s1-sidecars"

    summary = normalize_abbyy_file(source, output_root=output_root, repo_root=tmp_path)

    page_refs = summary.manifest["pages"]
    assert [ref["page_sequence"] for ref in page_refs] == [2, 2]
    assert len({ref["sidecar_page_path"] for ref in page_refs}) == 2
    pages_dir = output_root / "ia-abbyy-v1" / "vol_01" / "pages"
    assert (pages_dir / "page_0002.json").exists()
    assert (pages_dir / "page_leaf0000.json").exists()

    token_ids = []
    for page_path in sorted(pages_dir.glob("*.json")):
        page = json.loads(page_path.read_text(encoding="utf-8"))
        for block in page["blocks"]:
            for line in block["lines"]:
                token_ids.extend(word["observation_token_id"] for word in line["words"])
    assert len(token_ids) == len(set(token_ids))


def test_page_subset_filters_abbyy_normalization(tmp_path: Path) -> None:
    source = (
        tmp_path
        / "data"
        / "reference"
        / "schaff"
        / "encyclopedia"
        / "1908-1914"
        / "ia-abbyy-v1"
        / "vol_01.json"
    )
    _write_assembled(
        source,
        "ia-abbyy-v1",
        pages=[
            {"page": 1, "text": "Alpha"},
            {"page": 2, "text": "Beta"},
            {"page": 3, "text": "Gamma"},
        ],
    )
    output_root = tmp_path / "reports" / "s1-sidecars"

    summary = normalize_abbyy_file(
        source,
        output_root=output_root,
        repo_root=tmp_path,
        pages=[2],
    )

    assert [ref["page_sequence"] for ref in summary.manifest["pages"]] == [2]
    pages_dir = output_root / "ia-abbyy-v1" / "vol_01" / "pages"
    assert sorted(path.name for path in pages_dir.glob("*.json")) == ["page_0002.json"]


# --- Rich-sidecar geometry re-point (bug e): ABBYY as a word-geometry engine ----

# Mirrors the real raw/.../page_NNNN.ia-abbyy*.json shape verbatim: block{block_type,
# bbox} -> line{bbox,baseline,x_size,words} -> word{text,confidence,bbox{x,y,w,h}}.
def _write_rich_sidecar(
    path: Path,
    *,
    page_index: int,
    page_num: int,
    width: int = 5034,
    height: int = 6959,
    blocks: list[dict] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if blocks is None:
        blocks = [
            {
                "block_type": "Text",
                "bbox": {"x": 1136, "y": 684, "w": 516, "h": 120},
                "lines": [
                    {
                        "bbox": {"x": 1170, "y": 697, "w": 470, "h": 49},
                        "baseline": 744,
                        "x_size": None,
                        "words": [
                            {"text": "Grace", "confidence": 80.0,
                             "bbox": {"x": 1170, "y": 697, "w": 259, "h": 49}},
                            {"text": "peace", "confidence": 60.0,
                             "bbox": {"x": 1440, "y": 697, "w": 200, "h": 49}},
                        ],
                    }
                ],
            }
        ]
    word_count = sum(
        len(line["words"]) for block in blocks for line in block["lines"]
    )
    record = {
        "format_version": "ia-abbyy-rich-v1",
        "coordinate_unit": "pixel",
        "coordinate_frame": "source_image",
        "page_rotation": 0,
        "engine": "abbyy-finereader",
        "engine_version": "LuraDocument XML Exporter for ABBYY FineReader",
        "page_index": page_index,
        "page_num": page_num,
        "page_size": {"width": width, "height": height},
        "confidence_mean": 74.69,
        "word_count": word_count,
        "text": "Grace peace",
        "blocks": blocks,
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def test_rich_volume_emits_word_geometry(tmp_path: Path) -> None:
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_rich_sidecar(
        input_root / "vol_01" / "page_0010.ia-abbyy.json",
        page_index=46,
        page_num=10,
    )
    output_root = tmp_path / "reports" / "s1-sidecars"

    summary = normalize_abbyy_rich_volume(
        input_root,
        source_lineage_id="ia-abbyy-v1",
        volume=1,
        output_root=output_root,
        repo_root=tmp_path,
    )

    assert summary.manifest["engine_family"] == "abbyy"
    assert summary.emitted_pages == 1
    assert summary.manifest["pages"][0]["status"] == "eligible"

    page_path = output_root / "ia-abbyy-v1" / "vol_01" / "pages" / "page_0010.json"
    page = json.loads(page_path.read_text(encoding="utf-8"))
    # The whole point of the re-point: real pixel dimensions + per-word bbox.
    assert page["page_dimensions_native"] == {"width": 5034, "height": 6959, "unit": "pixel"}
    words = [w for b in page["blocks"] for line in b["lines"] for w in line["words"]]
    assert len(words) == 2
    assert all(isinstance(w["bbox_native"], dict) for w in words)
    assert words[0]["bbox_native"] == {"x": 1170, "y": 697, "w": 259, "h": 49}
    assert words[0]["source_raw"] == "Grace"
    assert words[0]["confidence"] == 80.0
    # Block geometry carried too.
    assert page["blocks"][0]["bbox_native"] == {"x": 1136, "y": 684, "w": 516, "h": 120}
    assert page["blocks"][0]["block_type"] == "text"
    # Token ids unique across the page.
    token_ids = [w["observation_token_id"] for w in words]
    assert len(token_ids) == len(set(token_ids))


def test_rich_volume_page_native_id_matches_scan_stem(tmp_path: Path) -> None:
    # ABBYY must key page identity to the scan stem (page_0010) so it aligns with
    # Tesseract/Surya, not to the printed page number ("10") the flat path used.
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_rich_sidecar(
        input_root / "vol_01" / "page_0010.ia-abbyy.json",
        page_index=46,
        page_num=10,
    )
    summary = normalize_abbyy_rich_volume(
        input_root,
        source_lineage_id="ia-abbyy-v1",
        volume=1,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
    )
    ref = summary.manifest["pages"][0]
    assert ref["page_native_id"] == "page_0010"
    assert ref["page_sequence"] == 10


def test_rich_volume_rerun_preserves_manifest_pages(tmp_path: Path) -> None:
    # Regression: a second run without force=True skips already-emitted pages but
    # must still produce a manifest with the page listed.  The bug was that page_refs
    # only accumulated new pages, so the skip branch silently emptied the manifest.
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_rich_sidecar(
        input_root / "vol_01" / "page_0010.ia-abbyy.json",
        page_index=46,
        page_num=10,
    )
    output_root = tmp_path / "reports" / "s1-sidecars"

    first = normalize_abbyy_rich_volume(
        input_root, source_lineage_id="ia-abbyy-v1", volume=1,
        output_root=output_root, repo_root=tmp_path,
    )
    assert first.emitted_pages == 1
    assert len(first.manifest["pages"]) == 1

    second = normalize_abbyy_rich_volume(
        input_root, source_lineage_id="ia-abbyy-v1", volume=1,
        output_root=output_root, repo_root=tmp_path,
    )
    assert second.skipped_pages == 1
    assert second.emitted_pages == 0
    assert len(second.manifest["pages"]) == 1, (
        "rerun zeroed manifest pages (skip branch did not preserve page_refs)"
    )
    assert second.manifest["pages"][0]["page_native_id"] == "page_0010"


def test_rich_volume_suffix_maps_lineage_variant(tmp_path: Path) -> None:
    # Lineage ia-abbyy-haucgoog-c1-v1 reads page_*.ia-abbyy-haucgoog-c1.json,
    # not the bare page_*.ia-abbyy.json.
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_rich_sidecar(
        input_root / "vol_01" / "page_0010.ia-abbyy-haucgoog-c1.json",
        page_index=46,
        page_num=10,
    )
    # A decoy bare-lineage file that must NOT be picked up for the c1 lineage.
    _write_rich_sidecar(
        input_root / "vol_01" / "page_0010.ia-abbyy.json",
        page_index=46,
        page_num=10,
    )
    summary = normalize_abbyy_rich_volume(
        input_root,
        source_lineage_id="ia-abbyy-haucgoog-c1-v1",
        volume=1,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
    )
    assert summary.emitted_pages == 1
    assert summary.manifest["source_lineage_id"] == "ia-abbyy-haucgoog-c1-v1"
    src_paths = [ref["path"] for ref in summary.manifest["source_files"]]
    assert all("ia-abbyy-haucgoog-c1.json" in p for p in src_paths)


def test_rich_volume_page_subset_filter(tmp_path: Path) -> None:
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    for stem, pnum in (("page_0009", 9), ("page_0010", 10), ("page_0011", 11)):
        _write_rich_sidecar(
            input_root / "vol_01" / f"{stem}.ia-abbyy.json",
            page_index=pnum + 36,
            page_num=pnum,
        )
    summary = normalize_abbyy_rich_volume(
        input_root,
        source_lineage_id="ia-abbyy-v1",
        volume=1,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
        pages=[10],
    )
    assert [ref["page_native_id"] for ref in summary.manifest["pages"]] == ["page_0010"]


def _write_canonical_manifest(
    path: Path, *, first_page: int = 1, last_page: int = 20, front_offset: int = 36
) -> None:
    """A minimal v4 canonical manifest: body leaf_num = page_num + front_offset."""
    leaves = []
    for leaf_num in range(1, first_page + front_offset):
        leaves.append({"leaf_num": leaf_num, "page_num": None, "kind": "front_matter"})
    for page_num in range(first_page, last_page + 1):
        leaves.append(
            {"leaf_num": page_num + front_offset, "page_num": page_num, "kind": "body"}
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"volume": 1, "leaves": leaves, "gaps": []}, indent=2), encoding="utf-8")


def test_rich_volume_stamps_canonical_leaf_id(tmp_path: Path) -> None:
    # R7: ABBYY aligns onto the primary leaf coordinate. page_0010 -> printed page
    # 10 -> body leaf 46 (page_num + front_offset 36). The stamp lands on BOTH the
    # manifest page_ref (render_s2 reads it for the WCT join) and the sidecar record.
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_rich_sidecar(input_root / "vol_01" / "page_0010.ia-abbyy.json", page_index=46, page_num=10)
    _write_canonical_manifest(input_root / "vol_01.manifest.json")

    summary = normalize_abbyy_rich_volume(
        input_root,
        source_lineage_id="ia-abbyy-v1",
        volume=1,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
    )
    assert summary.unmapped_pages == 0
    ref = summary.manifest["pages"][0]
    assert ref["canonical_leaf_id"] == 46
    page_path = (
        tmp_path / "reports" / "s1-sidecars" / "ia-abbyy-v1" / "vol_01" / "pages" / "page_0010.json"
    )
    page = json.loads(page_path.read_text(encoding="utf-8"))
    assert page["canonical_leaf_id"] == 46


def test_rich_volume_logs_unmapped_when_stem_has_no_leaf(tmp_path: Path) -> None:
    # A printed page outside the canonical body range (here page 25, manifest covers
    # 1-20) cannot resolve to a leaf -> unmapped, logged, no canonical_leaf_id
    # stamped (expected soft behavior, design SS6.4).
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_rich_sidecar(input_root / "vol_01" / "page_0025.ia-abbyy.json", page_index=61, page_num=25)
    _write_canonical_manifest(input_root / "vol_01.manifest.json")

    summary = normalize_abbyy_rich_volume(
        input_root,
        source_lineage_id="ia-abbyy-v1",
        volume=1,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
    )
    assert summary.unmapped_pages == 1
    assert "canonical_leaf_id" not in summary.manifest["pages"][0]


def test_abbyy_rendering_carries_canonical_leaf_id_after_stamp(tmp_path: Path) -> None:
    # R7 WCT-lane closure: once the ABBYY S1 manifest page_ref carries
    # canonical_leaf_id, render_s2 propagates it to the rendering-v1 page, so
    # build_wct includes ABBYY in the cross-engine leaf join (no longer exempt).
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_rich_sidecar(input_root / "vol_01" / "page_0010.ia-abbyy.json", page_index=46, page_num=10)
    _write_canonical_manifest(input_root / "vol_01.manifest.json")
    output_root = tmp_path / "reports" / "s1-sidecars"
    summary = normalize_abbyy_rich_volume(
        input_root,
        source_lineage_id="ia-abbyy-v1",
        volume=1,
        output_root=output_root,
        repo_root=tmp_path,
    )
    out = tmp_path / "s2_out"
    render_manifest(summary.manifest_path, repo_root=tmp_path, output_dir=out)
    rendering = json.loads((out / "pages" / "page_0010.rendering-v1.json").read_text(encoding="utf-8"))
    assert rendering["pages"][0]["canonical_leaf_id"] == 46


def test_rich_volume_without_canonical_manifest_skips_stamp(tmp_path: Path) -> None:
    # Degraded/test context (no canonical manifest on disk): stamping is skipped,
    # canonical_leaf_id stays absent (schema-optional through R6b), run still works.
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_rich_sidecar(input_root / "vol_01" / "page_0010.ia-abbyy.json", page_index=46, page_num=10)

    summary = normalize_abbyy_rich_volume(
        input_root,
        source_lineage_id="ia-abbyy-v1",
        volume=1,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
    )
    assert summary.emitted_pages == 1
    assert "canonical_leaf_id" not in summary.manifest["pages"][0]


@pytest.mark.skipif(
    not _REAL_ABBYY_PAGE10.exists(),
    reason="raw/internet-archive/schaff-herzog-pages not downloaded",
)
def test_real_abbyy_rich_page10_has_word_geometry(tmp_path: Path) -> None:
    # TEST-13: derived from the actual downloaded rich sidecar, not a description.
    # Copy the real bytes into a tmp raw tree so input + output share one repo_root.
    raw_dir = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_01"
    raw_dir.mkdir(parents=True)
    (raw_dir / "page_0010.ia-abbyy.json").write_bytes(_REAL_ABBYY_PAGE10.read_bytes())

    summary = normalize_abbyy_rich_volume(
        tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages",
        source_lineage_id="ia-abbyy-v1",
        volume=1,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
        pages=[10],
    )
    assert summary.emitted_pages == 1
    page_path = (
        tmp_path / "reports" / "s1-sidecars" / "ia-abbyy-v1" / "vol_01" / "pages" / "page_0010.json"
    )
    page = json.loads(page_path.read_text(encoding="utf-8"))
    assert page["page_dimensions_native"] == {"width": 5034, "height": 6959, "unit": "pixel"}
    words = [w for b in page["blocks"] for line in b["lines"] for w in line["words"]]
    # The real page carries 1106 ABBYY words, all with bbox.
    assert len(words) > 1000
    assert all(isinstance(w["bbox_native"], dict) for w in words)
    assert all({"x", "y", "w", "h"} == set(w["bbox_native"]) for w in words)
