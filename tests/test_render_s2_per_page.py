"""TDD tests for R4: per-page rendering output from render_s2.render_manifest.

These tests define the target API for R4.  They MUST fail on the current code
and pass after the R4 implementation lands.

Run failing-first:
    py -3 -m pytest -p no:cacheprovider -q tests/test_render_s2_per_page.py

All tests should be red before any R4 implementation code is written.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
ZERO_SHA = "sha256:" + ("0" * 64)
ONE_SHA = "sha256:" + ("1" * 64)


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _ot(label: str) -> str:
    return "ot-sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _line(label: str, text: str, y: int) -> dict[str, Any]:
    tokens = text.split() or [text]
    return {
        "observation_token_id": _ot(f"{label}-line"),
        "line_native_id": f"{label}-line",
        "source_raw": text,
        "confidence": 90.0,
        "bbox_native": {"x": 60, "y": y, "w": 520, "h": 22},
        "words": [
            {
                "observation_token_id": _ot(f"{label}-w{i}-{tok}"),
                "word_native_id": f"{label}-w{i}",
                "source_raw": tok,
                "confidence": 91.0,
                "bbox_native": {"x": 60 + i * 52, "y": y, "w": 48, "h": 18},
            }
            for i, tok in enumerate(tokens, 1)
        ],
    }


def _write_bundle(
    root: Path,
    *,
    engine_family: str = "tesseract",
    rendering_id: str = "tesseract-render",
    page_count: int = 1,
    source_lineage_id: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Write a minimal sidecar bundle with ``page_count`` pages."""
    manifest_id = f"{engine_family}-manifest"
    lineage = source_lineage_id or f"{engine_family}-lineage"
    page_refs: list[dict[str, Any]] = []

    for seq in range(1, page_count + 1):
        page_native_id = f"page_{seq:04d}"
        line_obj = _line(f"p{seq}-b1-l1", "Church history begins", 120)
        page: dict[str, Any] = {
            "schema_version": "sidecar-page-v1",
            "manifest_id": manifest_id,
            "rendering_id": rendering_id,
            "page_native_id": page_native_id,
            "page_sequence": seq,
            "page_dimensions_native": {"width": 1000, "height": 1000, "unit": "pixel"},
            "blocks": [
                {
                    "block_id": f"p{seq}-b1",
                    "block_type": "text",
                    "bbox_native": {"x": 50, "y": 100, "w": 560, "h": 120},
                    "lines": [line_obj],
                }
            ],
            "parsed_keys_index": [],
            "page_extras_carried": {},
            "page_extras_carried_keys": [],
            "page_extras_jcs_sha256": ZERO_SHA,
            "source_payload_sha256": ONE_SHA,
        }
        page_path = root / "s1" / engine_family / "pages" / f"{page_native_id}.json"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(json.dumps(page, indent=2, ensure_ascii=False), encoding="utf-8")
        rel_page = page_path.relative_to(root).as_posix()
        page_refs.append(
            {
                "page_native_id": page_native_id,
                "page_sequence": seq,
                "status": "eligible",
                "sidecar_page_path": rel_page,
                "source_payload_sha256": ONE_SHA,
                "edition_page_key": {"section": "body", "anchor": seq, "ordinal": 0},
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": "sidecar-manifest-v1",
        "manifest_id": manifest_id,
        "work_id": "schaff-herzog",
        "edition_id": "nsh-1908-1914",
        "volume": 1,
        "rendering_id": rendering_id,
        "engine_family": engine_family,
        "engine_version": "fixture-1.0",
        "source_lineage_id": lineage,
        "source_files": [{"path": "raw/source-fixture.json", "sha256": ONE_SHA}],
        "pages": page_refs,
        "manifest_cross_check": {
            "samples_checked": 1,
            "samples_matched": 1,
            "samples_inconclusive": 0,
            "failed_samples": [],
        },
        "bundle_extras_carried": {},
        "bundle_extras_carried_keys": [],
        "bundle_extras_jcs_sha256": ZERO_SHA,
        "created_at": "2026-05-29T00:00:00Z",
    }
    manifest_path = root / "s1" / engine_family / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path, manifest


# ---------------------------------------------------------------------------
# Deliverable A — render_s2.py per-page output
# ---------------------------------------------------------------------------


def test_render_manifest_writes_per_page_files(tmp_path: Path) -> None:
    """render_manifest writes one rendering-v1 file per page under output_dir/pages/."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_bundle(tmp_path)
    output_dir = tmp_path / "s2_out"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)

    page_file = output_dir / "pages" / "page_0001.rendering-v1.json"
    assert page_file.exists(), f"Expected per-page file at {page_file}"


def test_render_manifest_fails_when_manifest_has_fewer_pages_than_sidecars(tmp_path: Path) -> None:
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_bundle(tmp_path, page_count=1)
    extra_page = manifest_path.parent / "pages" / "page_0002.json"
    extra_page.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="manifest has 1 pages but 2 sidecars"):
        render_manifest(manifest_path, repo_root=tmp_path, output_dir=tmp_path / "out")


def test_render_manifest_allows_stale_manifest_when_explicit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_bundle(tmp_path, page_count=1)
    extra_page = manifest_path.parent / "pages" / "page_0002.json"
    extra_page.write_text("{}", encoding="utf-8")

    render_manifest(
        manifest_path,
        repo_root=tmp_path,
        output_dir=tmp_path / "out",
        allow_stale_manifest=True,
    )

    captured = capsys.readouterr()
    assert "manifest has 1 pages but 2 sidecars" in captured.err


def test_render_manifest_per_page_file_is_valid_rendering_v1_doc(tmp_path: Path) -> None:
    """Each per-page file is a schema-valid rendering-v1 document with exactly one page."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_bundle(tmp_path)
    output_dir = tmp_path / "s2_out"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)

    page_file = output_dir / "pages" / "page_0001.rendering-v1.json"
    doc = json.loads(page_file.read_text(encoding="utf-8"))

    jsonschema.validate(instance=doc, schema=_schema("rendering-v1"))
    assert doc["schema_version"] == "rendering-v1"
    assert len(doc["pages"]) == 1
    assert doc["pages"][0]["page_native_id"] == "page_0001"


def test_render_manifest_carries_edition_page_key_from_page_ref(tmp_path: Path) -> None:
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, manifest = _write_bundle(tmp_path)
    key = {"section": "body", "anchor": 7, "ordinal": 0}
    manifest["pages"][0]["edition_page_key"] = key
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    output_dir = tmp_path / "s2_out"

    render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)

    page_file = output_dir / "pages" / "page_0001.rendering-v1.json"
    doc = json.loads(page_file.read_text(encoding="utf-8"))
    assert doc["pages"][0]["edition_page_key"] == key


def test_render_manifest_writes_index_json(tmp_path: Path) -> None:
    """render_manifest writes a thin index.json at the output_dir root."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_bundle(tmp_path)
    output_dir = tmp_path / "s2_out"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)

    index_path = output_dir / "index.json"
    assert index_path.exists(), f"Expected index.json at {index_path}"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["schema_version"] == "rendering-index-v1"
    assert index["pages"] == ["page_0001"]
    assert index["source_lineage_id"] == "tesseract-lineage"
    assert index["volume"] == 1


def test_render_manifest_multi_page_index_lists_all_pages(tmp_path: Path) -> None:
    """index.json pages list contains all rendered page native IDs in sequence order."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_bundle(tmp_path, page_count=3)
    output_dir = tmp_path / "s2_out"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)

    index = json.loads((output_dir / "index.json").read_text(encoding="utf-8"))
    assert index["pages"] == ["page_0001", "page_0002", "page_0003"]

    for page_id in index["pages"]:
        assert (output_dir / "pages" / f"{page_id}.rendering-v1.json").exists()


def test_render_manifest_does_not_write_old_bundle_file(tmp_path: Path) -> None:
    """The old single-file rendering-v1.json volume bundle must NOT be written."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_bundle(tmp_path)
    output_dir = tmp_path / "s2_out"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)

    old_bundle = output_dir / "rendering-v1.json"
    assert not old_bundle.exists(), "Old volume-bundle rendering-v1.json must not be written in R4"


def test_render_manifest_default_output_dir_is_manifest_parent(tmp_path: Path) -> None:
    """When output_dir is omitted, per-page files land in manifest_path.parent/pages/."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_bundle(tmp_path)
    render_manifest(manifest_path, repo_root=tmp_path)

    default_pages_dir = manifest_path.parent / "pages"
    assert (default_pages_dir / "page_0001.rendering-v1.json").exists(), (
        f"Expected default per-page output at {default_pages_dir}"
    )


def test_render_manifest_returns_summary_dict_with_counts(tmp_path: Path) -> None:
    """render_manifest returns a summary dict with 'written' and 'skipped' integer counts."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_bundle(tmp_path, page_count=2)
    output_dir = tmp_path / "s2_out"
    result = render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert result.get("written") == 2
    assert result.get("skipped") == 0


def test_render_manifest_skip_if_exists_skips_up_to_date_pages(tmp_path: Path) -> None:
    """Second render call (force=False) skips pages whose per-page file already exists."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_bundle(tmp_path, page_count=2)
    output_dir = tmp_path / "s2_out"

    first = render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)
    assert first["written"] == 2

    second = render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)
    assert second["written"] == 0
    assert second["skipped"] == 2


def test_render_manifest_force_flag_rewrites_existing_pages(tmp_path: Path) -> None:
    """force=True re-renders all pages even when per-page files already exist."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_bundle(tmp_path)
    output_dir = tmp_path / "s2_out"

    render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)
    second = render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir, force=True)

    assert second["written"] == 1
    assert second["skipped"] == 0


def test_render_manifest_skips_when_only_manifest_timestamp_changes(tmp_path: Path) -> None:
    """Volatile manifest rewrites must not invalidate otherwise-current S2 pages."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, manifest = _write_bundle(tmp_path)
    output_dir = tmp_path / "s2_out"

    render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)

    manifest["created_at"] = "2026-06-09T00:00:00Z"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    result = render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)
    assert result["written"] == 0
    assert result["skipped"] == 1


def test_render_manifest_rerenders_when_manifest_metadata_changes(tmp_path: Path) -> None:
    """Stable output metadata changes must invalidate the skip."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, manifest = _write_bundle(tmp_path)
    output_dir = tmp_path / "s2_out"

    render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)

    manifest["engine_version"] = "fixture-2.0"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    result = render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)
    assert result["written"] == 1
    assert result["skipped"] == 0


def test_render_manifest_rerenders_when_source_sidecar_changes(tmp_path: Path) -> None:
    """Currentness is invalidated when the referenced S1 sidecar file changes."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, manifest = _write_bundle(tmp_path)
    output_dir = tmp_path / "s2_out"

    render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)

    sidecar_path = tmp_path / manifest["pages"][0]["sidecar_page_path"]
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["page_extras_carried"]["runner_cache_version"] = "new-cache-version"
    sidecar["page_extras_carried_keys"] = sorted(sidecar["page_extras_carried"])
    sidecar_path.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8")

    result = render_manifest(manifest_path, repo_root=tmp_path, output_dir=output_dir)
    assert result["written"] == 1
    assert result["skipped"] == 0


# ---------------------------------------------------------------------------
# Deliverable B — drive_reconciliation_chain.py cleanup
# ---------------------------------------------------------------------------


def test_filter_rendering_to_page_is_removed() -> None:
    """filter_rendering_to_page must not exist in drive_reconciliation_chain after R4."""
    from build.tools.ocr_pipeline import drive_reconciliation_chain as chain

    assert not hasattr(chain, "filter_rendering_to_page"), (
        "filter_rendering_to_page must be removed from drive_reconciliation_chain in R4"
    )


def test_single_rendering_paths_reads_per_page_file_directly(tmp_path: Path) -> None:
    """_single_rendering_paths returns the per-page file path without a separate single_root write."""
    from build.tools.ocr_pipeline import drive_reconciliation_chain as chain

    engines = ("tesseract-py314-v1", "ia-abbyy-v1")
    s2_root = tmp_path / "s2"
    page_files = []
    for engine in engines:
        page_file = s2_root / "vol_01" / engine / "pages" / "page_0010.rendering-v1.json"
        page_file.parent.mkdir(parents=True, exist_ok=True)
        page_file.write_text(
            json.dumps({"schema_version": "rendering-v1", "pages": [{"page_native_id": "page_0010"}]}),
            encoding="utf-8",
        )
        page_files.append(page_file)

    paths = chain._single_rendering_paths(
        volume=1,
        page=10,
        engines=engines,
        s2_root=s2_root,
        single_root=tmp_path / "single",
    )

    assert paths == page_files
    # single_root must not be written — the per-page file IS the rendering
    assert not (tmp_path / "single").exists(), "single_root should not be written in R4"


def test_single_rendering_paths_raises_when_page_file_missing(tmp_path: Path) -> None:
    """_single_rendering_paths raises FileNotFoundError when per-page file is absent."""
    from build.tools.ocr_pipeline import drive_reconciliation_chain as chain

    engine = "tesseract-py314-v1"
    s2_root = tmp_path / "s2"
    # No page file written — should raise

    with pytest.raises(FileNotFoundError):
        chain._single_rendering_paths(
            volume=1,
            page=10,
            engines=[engine],
            s2_root=s2_root,
            single_root=tmp_path / "single",
        )


def test_drive_pages_reads_per_page_s2_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """drive_pages passes per-page rendering files to build_wct_for_page."""
    from build.tools.ocr_pipeline import drive_reconciliation_chain as chain

    engines = ("tesseract-py314-v1", "ia-abbyy-v1")
    s2_root = tmp_path / "s2"
    page_files = []
    for engine in engines:
        page_file = s2_root / "vol_01" / engine / "pages" / "page_0010.rendering-v1.json"
        page_file.parent.mkdir(parents=True, exist_ok=True)
        page_file.write_text(
            json.dumps({"schema_version": "rendering-v1", "pages": [{"page_native_id": "page_0010"}]}),
            encoding="utf-8",
        )
        page_files.append(page_file)

    (tmp_path / "work_meta.json").write_text("{}", encoding="utf-8")
    wct_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        chain, "build_wct_for_page",
        lambda **kw: wct_calls.append(kw) or {"positions": [], "available_engines": []},
    )
    monkeypatch.setattr(chain, "reconcile_page_inline", lambda **kw: None)
    monkeypatch.setattr(
        chain, "source_image_metadata",
        lambda *a, **kw: {"path": "raw/fake.jpg", "sha256": "abc"},
    )

    chain.drive_pages(
        volume=1,
        pages=[10],
        engines=engines,
        run_s1_s2=False,
        s2_root=s2_root,
        single_root=tmp_path / "single",
        wct_root=tmp_path / "wct",
        reconciled_root=tmp_path / "reconciled",
        work_meta=tmp_path / "work_meta.json",
        max_workers=1,  # sequential path; monkeypatch on reconcile_page_inline requires it
    )

    assert wct_calls, "build_wct_for_page must have been called"
    renderings = wct_calls[0]["renderings"]
    assert renderings == page_files, (
        f"Expected renderings=[page_file], got {renderings}"
    )
