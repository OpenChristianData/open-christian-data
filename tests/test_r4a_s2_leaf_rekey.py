"""TDD tests for R4a: S2 render rekey onto canonical_leaf_id.

These tests define the target behaviour for R4a. They MUST be red on the
pre-R4a code and green after the implementation lands.

R4a moves BOTH S2 currentness gates off the rename-volatile volume-global
``manifest_id`` + filename ``page_native_id`` and onto the per-page triple
``(canonical_leaf_id, source_payload_sha256, sidecar sha)``; reseeds
``rendering_line_id`` / ``rendering_block_id`` from ``canonical_leaf_id`` (not
the filename stem); stamps ``canonical_leaf_id`` onto the rendered page; and
makes the rendering pages dir equal the current manifest expected set exactly
(orphans quarantined, REL-05).

Run failing-first:
    py -3 -m pytest -p no:cacheprovider -q tests/test_r4a_s2_leaf_rekey.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ZERO_SHA = "sha256:" + ("0" * 64)


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


def _write_leaf_bundle(
    root: Path,
    *,
    engine_family: str = "tesseract",
    rendering_id: str = "tesseract-render",
    pages: list[tuple[str, int, str]] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Write a leaf-keyed sidecar bundle.

    ``pages`` is a list of ``(page_native_id, canonical_leaf_id, payload_sha)``
    tuples so a test can vary the filename, the leaf, and the content sha
    independently.
    """
    from build.lib.edition_page_key import body_edition_key

    if pages is None:
        pages = [("page_0001", 11, "sha256:" + ("1" * 64))]
    manifest_id = f"{engine_family}-manifest"
    lineage = f"{engine_family}-lineage"
    page_refs: list[dict[str, Any]] = []

    for page_native_id, leaf, payload_sha in pages:
        # Native block/line ids come from the OCR engine, not the filename. Keep
        # them stable across bundles so the only thing a test varies is the
        # filename vs leaf -- isolating the page_seed (R4a) in the id derivation.
        line_obj = _line(f"leaf{leaf}-b1-l1", "Church history begins", 120)
        page: dict[str, Any] = {
            "schema_version": "sidecar-page-v1",
            "manifest_id": manifest_id,
            "rendering_id": rendering_id,
            "page_native_id": page_native_id,
            "canonical_leaf_id": leaf,
            "page_sequence": leaf + 1,
            "page_dimensions_native": {"width": 1000, "height": 1000, "unit": "pixel"},
            "blocks": [
                {
                    "block_id": f"leaf{leaf}-b1",
                    "block_type": "text",
                    "bbox_native": {"x": 50, "y": 100, "w": 560, "h": 120},
                    "lines": [line_obj],
                }
            ],
            "parsed_keys_index": [],
            "page_extras_carried": {},
            "page_extras_carried_keys": [],
            "page_extras_jcs_sha256": ZERO_SHA,
            "source_payload_sha256": payload_sha,
            "edition_page_key": body_edition_key(leaf),
        }
        page_path = root / "s1" / engine_family / "pages" / f"{page_native_id}.json"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(json.dumps(page, indent=2, ensure_ascii=False), encoding="utf-8")
        page_refs.append(
            {
                "page_native_id": page_native_id,
                "canonical_leaf_id": leaf,
                "page_sequence": leaf + 1,
                "status": "eligible",
                "sidecar_page_path": page_path.relative_to(root).as_posix(),
                "source_payload_sha256": payload_sha,
                "edition_page_key": body_edition_key(leaf),
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
        "source_files": [{"path": "raw/source-fixture.json", "sha256": "sha256:" + ("1" * 64)}],
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


def _render_page_doc(output_dir: Path, page_native_id: str) -> dict[str, Any]:
    path = output_dir / "pages" / f"{page_native_id}.rendering-v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# canonical_leaf_id stamped on the rendered page
# ---------------------------------------------------------------------------


def test_rendered_page_carries_canonical_leaf_id(tmp_path: Path) -> None:
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_leaf_bundle(tmp_path, pages=[("page_0001", 11, "sha256:" + ("1" * 64))])
    out = tmp_path / "s2_out"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out)

    page = _render_page_doc(out, "page_0001")["pages"][0]
    assert page["canonical_leaf_id"] == 11


# ---------------------------------------------------------------------------
# rendering_line_id / block id seed from canonical_leaf_id, not the filename
# ---------------------------------------------------------------------------


def test_line_and_block_ids_seed_from_leaf_not_filename(tmp_path: Path) -> None:
    """Same canonical_leaf_id under a different filename -> identical ids.

    Pre-R4a the ids seed from page_native_id, so renaming the file changes
    every rendering_line_id/rendering_block_id. After R4a they seed from
    canonical_leaf_id, so the same leaf yields the same ids regardless of stem.
    """
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    sha = "sha256:" + ("a" * 64)
    a_root = tmp_path / "a"
    b_root = tmp_path / "b"
    a_manifest, _ = _write_leaf_bundle(a_root, pages=[("page_0042", 7, sha)])
    b_manifest, _ = _write_leaf_bundle(b_root, pages=[("leaf_0007", 7, sha)])

    a_out = a_root / "s2_out"
    b_out = b_root / "s2_out"
    render_manifest(a_manifest, repo_root=a_root, output_dir=a_out)
    render_manifest(b_manifest, repo_root=b_root, output_dir=b_out)

    a_block = _render_page_doc(a_out, "page_0042")["pages"][0]["blocks"][0]
    b_block = _render_page_doc(b_out, "leaf_0007")["pages"][0]["blocks"][0]
    assert a_block["rendering_block_id"] == b_block["rendering_block_id"]
    assert a_block["lines"][0]["rendering_line_id"] == b_block["lines"][0]["rendering_line_id"]


def test_line_id_changes_when_leaf_changes(tmp_path: Path) -> None:
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    sha = "sha256:" + ("b" * 64)
    a_root = tmp_path / "a"
    b_root = tmp_path / "b"
    a_manifest, _ = _write_leaf_bundle(a_root, pages=[("page_0001", 3, sha)])
    b_manifest, _ = _write_leaf_bundle(b_root, pages=[("page_0001", 9, sha)])
    a_out = a_root / "s2_out"
    b_out = b_root / "s2_out"
    render_manifest(a_manifest, repo_root=a_root, output_dir=a_out)
    render_manifest(b_manifest, repo_root=b_root, output_dir=b_out)

    a_line = _render_page_doc(a_out, "page_0001")["pages"][0]["blocks"][0]["lines"][0]
    b_line = _render_page_doc(b_out, "page_0001")["pages"][0]["blocks"][0]["lines"][0]
    assert a_line["rendering_line_id"] != b_line["rendering_line_id"]


# ---------------------------------------------------------------------------
# Gate 1 — render_s2._page_rendering_is_current
# ---------------------------------------------------------------------------


def test_gate1_tolerates_manifest_id_flip(tmp_path: Path) -> None:
    """A volume-global manifest_id change must NOT invalidate a page whose
    leaf, content sha and sidecar sha are unchanged (the rename-volatility fix)."""
    from build.tools.ocr_pipeline.render_s2 import _page_rendering_is_current, render_manifest

    manifest_path, manifest = _write_leaf_bundle(tmp_path, pages=[("page_0001", 11, "sha256:" + ("1" * 64))])
    out = tmp_path / "s2_out"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out)
    existing = _render_page_doc(out, "page_0001")
    page_ref = manifest["pages"][0]

    flipped = dict(manifest, manifest_id="some-other-manifest-id-after-rename")
    assert _page_rendering_is_current(
        existing,
        manifest=flipped,
        page_ref=page_ref,
        manifest_file=manifest_path,
        repo_root=tmp_path,
    )


def test_gate1_invalidates_on_leaf_change(tmp_path: Path) -> None:
    from build.tools.ocr_pipeline.render_s2 import _page_rendering_is_current, render_manifest

    manifest_path, manifest = _write_leaf_bundle(tmp_path, pages=[("page_0001", 11, "sha256:" + ("1" * 64))])
    out = tmp_path / "s2_out"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out)
    existing = _render_page_doc(out, "page_0001")

    moved_ref = dict(manifest["pages"][0], canonical_leaf_id=12)
    assert not _page_rendering_is_current(
        existing,
        manifest=manifest,
        page_ref=moved_ref,
        manifest_file=manifest_path,
        repo_root=tmp_path,
    )


# ---------------------------------------------------------------------------
# Gate 2 — run_ocr_pipeline._s2_output_is_current
# ---------------------------------------------------------------------------


def test_gate2_tolerates_manifest_id_flip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from build.tools.ocr_pipeline import run_ocr_pipeline
    from build.tools.ocr_pipeline.render_s2 import render_manifest
    from build.tools.ocr_pipeline.run_ocr_pipeline import _s2_output_is_current

    monkeypatch.setattr(run_ocr_pipeline, "REPO_ROOT", tmp_path)
    manifest_path, manifest = _write_leaf_bundle(tmp_path, pages=[("page_0001", 11, "sha256:" + ("1" * 64))])
    out = tmp_path / "s2_out"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out)
    index_path = out / "index.json"

    flipped = dict(manifest, manifest_id="some-other-manifest-id-after-rename")
    assert _s2_output_is_current(out, index_path, flipped)


def test_gate2_invalidates_on_leaf_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from build.tools.ocr_pipeline import run_ocr_pipeline
    from build.tools.ocr_pipeline.render_s2 import render_manifest
    from build.tools.ocr_pipeline.run_ocr_pipeline import _s2_output_is_current

    monkeypatch.setattr(run_ocr_pipeline, "REPO_ROOT", tmp_path)
    manifest_path, manifest = _write_leaf_bundle(tmp_path, pages=[("page_0001", 11, "sha256:" + ("1" * 64))])
    out = tmp_path / "s2_out"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out)
    index_path = out / "index.json"

    moved = json.loads(json.dumps(manifest))
    moved["pages"][0]["canonical_leaf_id"] = 12
    assert not _s2_output_is_current(out, index_path, moved)


def test_gate2_invalidates_on_identity_change_like_gate1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The two S2 gates must share the same identity key-set (audit 2026-06-15):
    # a work_id / edition_id change must invalidate under Gate 2, not only Gate 1.
    from build.tools.ocr_pipeline import run_ocr_pipeline
    from build.tools.ocr_pipeline.render_s2 import render_manifest
    from build.tools.ocr_pipeline.run_ocr_pipeline import _s2_output_is_current

    monkeypatch.setattr(run_ocr_pipeline, "REPO_ROOT", tmp_path)
    manifest_path, manifest = _write_leaf_bundle(tmp_path, pages=[("page_0001", 11, "sha256:" + ("1" * 64))])
    out = tmp_path / "s2_out"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out)
    index_path = out / "index.json"

    for field in ("work_id", "edition_id"):
        changed = dict(manifest)
        changed[field] = "changed-" + str(manifest.get(field))
        assert not _s2_output_is_current(out, index_path, changed), field


# ---------------------------------------------------------------------------
# Expected-set purge — rendering dir == current manifest expected set (REL-05)
# ---------------------------------------------------------------------------


def test_orphan_rendering_is_quarantined_not_left(tmp_path: Path) -> None:
    """A leftover rendering for a page no longer in the manifest must be moved
    out of pages/ (quarantined), so the pages dir equals the expected set."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, _ = _write_leaf_bundle(tmp_path, pages=[("page_0001", 11, "sha256:" + ("1" * 64))])
    out = tmp_path / "s2_out"
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    orphan = pages_dir / "page_9999.rendering-v1.json"
    orphan.write_text("{}", encoding="utf-8")

    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out)

    remaining = sorted(p.name for p in pages_dir.glob("*.rendering-v1.json"))
    assert remaining == ["page_0001.rendering-v1.json"]
    assert not orphan.exists()
