from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from build.parsers.s1_azure_normalizer import normalize_azure_volume  # noqa: E402
from build.parsers.s1_abbyy_normalizer import _validate  # noqa: E402

# Real Azure cloud sidecar for vol_01 page_0010 -- gitignored; skip when absent
# (GitHub Actions runs against a clean checkout).
_RAW_ROOT = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
_REAL_AZURE_PAGE10 = _RAW_ROOT / "vol_01" / "page_0010.azure.json"


def _write_azure_sidecar(
    path: Path,
    *,
    width: int = 5034,
    height: int = 6959,
    blocks: list[dict] | None = None,
    partial: bool = False,
) -> None:
    """Mirror the run_cloud_ocr.ocr_azure sidecar shape verbatim:

    image_size:[w,h] -> blocks[].lines[].words[]{text,confidence(0-100),bbox{x,y,w,h}}.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if partial:
        path.write_text(
            json.dumps({"partial": True, "engine": "azure", "error": "boom"}, indent=2),
            encoding="utf-8",
        )
        return
    if blocks is None:
        blocks = [
            {
                "bbox": {"x": 1170, "y": 688, "w": 470, "h": 61},
                "lines": [
                    {
                        "text": "Grace peace",
                        "bbox": {"x": 1173, "y": 688, "w": 467, "h": 61},
                        "words": [
                            {"text": "Grace", "confidence": 91.7,
                             "bbox": {"x": 1173, "y": 688, "w": 245, "h": 61}},
                            {"text": "peace", "confidence": 88.4,
                             "bbox": {"x": 1440, "y": 690, "w": 200, "h": 59}},
                        ],
                    }
                ],
            }
        ]
    record = {
        "format_version": 1,
        "coordinate_unit": "pixel",
        "coordinate_frame": "source_image",
        "engine": "azure-ai-vision",
        "engine_version": "2023-10-01",
        "run_timestamp": "2026-06-01T00:00:00Z",
        "image_size": [width, height],
        "page_rotation": 0.0,
        "confidence_mean": 90.1,
        "raw_text": "Grace peace",
        "blocks": blocks,
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _write_source_manifest(input_root: Path) -> None:
    manifest = {
        "ia_item_id": "test-nsh",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 1,
        "created_at": "2026-06-12T00:00:00Z",
        "page_count": 1,
        "leaves": [
            {"leaf_num": 10, "page_num": 10, "kind": "body", "image_state": "present"},
        ],
    }
    path = input_root / "vol_01.manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def test_azure_volume_emits_word_geometry(tmp_path: Path) -> None:
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_source_manifest(input_root)
    _write_azure_sidecar(input_root / "vol_01" / "page_0010.azure.json")
    output_root = tmp_path / "reports" / "s1-sidecars"

    summary = normalize_azure_volume(
        input_root,
        source_lineage_id="azure-ai-vision-v1",
        volume=1,
        output_root=output_root,
        repo_root=tmp_path,
    )

    assert summary.manifest["engine_family"] == "azure_read"
    assert summary.manifest["source_lineage_id"] == "azure-ai-vision-v1"
    assert summary.emitted_pages == 1
    assert summary.manifest["pages"][0]["status"] == "eligible"
    assert summary.manifest["pages"][0]["canonical_leaf_id"] == 10
    assert isinstance(summary.manifest["pages"][0]["canonical_leaf_id"], int)
    _validate("sidecar-manifest-v1", summary.manifest)

    page_path = output_root / "azure-ai-vision-v1" / "vol_01" / "pages" / "page_0010.json"
    page = json.loads(page_path.read_text(encoding="utf-8"))
    # image_size [w,h] -> real pixel page dimensions.
    assert page["page_dimensions_native"] == {"width": 5034, "height": 6959, "unit": "pixel"}
    words = [w for b in page["blocks"] for line in b["lines"] for w in line["words"]]
    assert len(words) == 2
    assert all(isinstance(w["bbox_native"], dict) for w in words)
    assert words[0]["bbox_native"] == {"x": 1173, "y": 688, "w": 245, "h": 61}
    assert words[0]["source_raw"] == "Grace"
    assert words[0]["confidence"] == 91.7
    # Block geometry carried.
    assert page["blocks"][0]["bbox_native"] == {"x": 1170, "y": 688, "w": 470, "h": 61}
    # Token ids unique across the page.
    token_ids = [w["observation_token_id"] for w in words]
    assert len(token_ids) == len(set(token_ids))


def test_azure_sidecar_record_carries_clid(tmp_path: Path) -> None:
    # R7 flip-readiness: the per-page sidecar JSON (not just the manifest ref) must
    # carry canonical_leaf_id, so the sidecar-page-v1 required flip is satisfiable.
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_source_manifest(input_root)
    _write_azure_sidecar(input_root / "vol_01" / "page_0010.azure.json")
    output_root = tmp_path / "reports" / "s1-sidecars"

    normalize_azure_volume(
        input_root,
        source_lineage_id="azure-ai-vision-v1",
        volume=1,
        output_root=output_root,
        repo_root=tmp_path,
    )

    page_path = output_root / "azure-ai-vision-v1" / "vol_01" / "pages" / "page_0010.json"
    page = json.loads(page_path.read_text(encoding="utf-8"))
    assert page["canonical_leaf_id"] == 10
    assert isinstance(page["canonical_leaf_id"], int)


def test_azure_page_native_id_matches_scan_stem(tmp_path: Path) -> None:
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_source_manifest(input_root)
    _write_azure_sidecar(input_root / "vol_01" / "page_0010.azure.json")
    summary = normalize_azure_volume(
        input_root,
        source_lineage_id="azure-ai-vision-v1",
        volume=1,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
    )
    ref = summary.manifest["pages"][0]
    assert ref["page_native_id"] == "page_0010"
    assert ref["page_sequence"] == 10


def test_azure_counts_and_emits_unmapped_page_refs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_source_manifest(input_root)
    _write_azure_sidecar(input_root / "vol_01" / "page_0010.azure.json")
    _write_azure_sidecar(input_root / "vol_01" / "page_0099.azure.json")

    with caplog.at_level(logging.WARNING, logger="build.parsers.s1_azure_normalizer"):
        summary = normalize_azure_volume(
            input_root,
            source_lineage_id="azure-ai-vision-v1",
            volume=1,
            output_root=tmp_path / "reports" / "s1-sidecars",
            repo_root=tmp_path,
        )

    refs = {ref["page_native_id"]: ref for ref in summary.manifest["pages"]}
    assert summary.unmapped_pages == 1
    assert refs["page_0010"]["canonical_leaf_id"] == 10
    assert isinstance(refs["page_0010"]["canonical_leaf_id"], int)
    assert "page_0099" in refs
    assert "canonical_leaf_id" not in refs["page_0099"]
    assert "1 page id(s) did not map to a leaf_num" in caplog.text
    assert "page_0099" in caplog.text
    _validate("sidecar-manifest-v1", summary.manifest)


def test_azure_skips_partial_sidecars(tmp_path: Path) -> None:
    # A partial sidecar (driver failure) carries no geometry -- it must not be
    # emitted as a panel page, and must not crash the volume.
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_source_manifest(input_root)
    _write_azure_sidecar(input_root / "vol_01" / "page_0010.azure.json")
    _write_azure_sidecar(input_root / "vol_01" / "page_0011.azure.json", partial=True)

    summary = normalize_azure_volume(
        input_root,
        source_lineage_id="azure-ai-vision-v1",
        volume=1,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
    )
    native_ids = [ref["page_native_id"] for ref in summary.manifest["pages"]]
    assert native_ids == ["page_0010"]
    assert summary.skipped_partial == 1


def test_azure_rerun_resumes(tmp_path: Path) -> None:
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_source_manifest(input_root)
    _write_azure_sidecar(input_root / "vol_01" / "page_0010.azure.json")
    output_root = tmp_path / "reports" / "s1-sidecars"

    first = normalize_azure_volume(
        input_root, source_lineage_id="azure-ai-vision-v1", volume=1,
        output_root=output_root, repo_root=tmp_path,
    )
    second = normalize_azure_volume(
        input_root, source_lineage_id="azure-ai-vision-v1", volume=1,
        output_root=output_root, repo_root=tmp_path,
    )
    assert first.emitted_pages == 1
    assert second.emitted_pages == 0
    assert second.skipped_pages == 1
    # Rerun must still list the page in the manifest (abbyy skip-branch regression).
    assert len(second.manifest["pages"]) == 1
    assert second.manifest["pages"][0]["page_native_id"] == "page_0010"
    assert second.manifest["pages"][0]["canonical_leaf_id"] == 10


def test_azure_page_subset_filter(tmp_path: Path) -> None:
    input_root = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    _write_source_manifest(input_root)
    for stem in ("page_0009", "page_0010", "page_0011"):
        _write_azure_sidecar(input_root / "vol_01" / f"{stem}.azure.json")
    summary = normalize_azure_volume(
        input_root,
        source_lineage_id="azure-ai-vision-v1",
        volume=1,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
        pages=[10],
    )
    assert [ref["page_native_id"] for ref in summary.manifest["pages"]] == ["page_0010"]


@pytest.mark.skipif(
    not _REAL_AZURE_PAGE10.exists(),
    reason="raw/internet-archive/schaff-herzog-pages not downloaded",
)
def test_real_azure_page10_has_word_geometry(tmp_path: Path) -> None:
    # Derived from the actual downloaded Azure sidecar, not a description.
    raw_dir = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages" / "vol_01"
    _write_source_manifest(raw_dir.parent)
    raw_dir.mkdir(parents=True)
    (raw_dir / "page_0010.azure.json").write_bytes(_REAL_AZURE_PAGE10.read_bytes())

    summary = normalize_azure_volume(
        tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages",
        source_lineage_id="azure-ai-vision-v1",
        volume=1,
        output_root=tmp_path / "reports" / "s1-sidecars",
        repo_root=tmp_path,
        pages=[10],
    )
    assert summary.emitted_pages == 1
    page_path = (
        tmp_path / "reports" / "s1-sidecars" / "azure-ai-vision-v1"
        / "vol_01" / "pages" / "page_0010.json"
    )
    page = json.loads(page_path.read_text(encoding="utf-8"))
    assert page["page_dimensions_native"] == {"width": 5034, "height": 6959, "unit": "pixel"}
    words = [w for b in page["blocks"] for line in b["lines"] for w in line["words"]]
    assert len(words) > 500
    assert all(isinstance(w["bbox_native"], dict) for w in words)
    assert all({"x", "y", "w", "h"} == set(w["bbox_native"]) for w in words)
