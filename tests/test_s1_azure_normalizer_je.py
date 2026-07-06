"""TDD tests for build/parsers/s1_azure_normalizer_je.py.

Covers:
- normalize_je_azure_volume: reads page_NNNN.azure.json files, emits S1 sidecars
- JE-specific constants: work_id, edition_id, rendering_id
- Schema invariants: page_sequence >= 1, page_dimensions_native unit = "pixel"
- Partial sidecar handling (skip, don't crash)
- Idempotency: second run resumes without re-emitting
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build.parsers.s1_azure_normalizer_je as mod  # noqa: E402

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_azure_sidecar(
    path: Path,
    *,
    width: int = 2048,
    height: int = 2828,
    blocks: list[dict] | None = None,
    partial: bool = False,
) -> None:
    """Write a minimal azure.json sidecar matching run_cloud_ocr.ocr_azure output."""
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
                "bbox": {"x": 100, "y": 80, "w": 400, "h": 60},
                "lines": [
                    {
                        "text": "Jewish people",
                        "bbox": {"x": 100, "y": 80, "w": 400, "h": 60},
                        "words": [
                            {
                                "text": "Jewish",
                                "confidence": 97.1,
                                "bbox": {"x": 100, "y": 80, "w": 180, "h": 60},
                            },
                            {
                                "text": "people",
                                "confidence": 95.3,
                                "bbox": {"x": 290, "y": 82, "w": 210, "h": 58},
                            },
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
        "run_timestamp": "2026-06-06T00:00:00Z",
        "image_size": [width, height],
        "page_rotation": 0.0,
        "confidence_mean": 96.2,
        "raw_text": "Jewish people",
        "blocks": blocks,
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_work_id_is_je() -> None:
    assert mod.WORK_ID == "jewish-encyclopedia.vol_02"


def test_edition_id_is_je() -> None:
    assert mod.EDITION_ID == "1901-1906"


def test_engine_family_is_azure_read() -> None:
    assert mod.ENGINE_FAMILY == "azure_read"


def test_rendering_id_contains_jewish_encyclopedia() -> None:
    assert "jewish-encyclopedia" in mod.RENDERING_ID
    assert "schaff" not in mod.RENDERING_ID


# ---------------------------------------------------------------------------
# normalize_je_azure_volume: basic emission
# ---------------------------------------------------------------------------

def test_je_azure_emits_one_page(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0038.azure.json")
    out_dir = tmp_path / "out"

    result = mod.normalize_je_azure_volume(raw_dir, out_dir)

    assert result["emitted_pages"] == 1
    assert result["skipped_pages"] == 0
    assert result["failed_pages"] == 0
    assert (out_dir / "pages" / "page_0038.json").exists()


def test_je_azure_manifest_has_je_work_id(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0038.azure.json")
    out_dir = tmp_path / "out"

    mod.normalize_je_azure_volume(raw_dir, out_dir)

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["work_id"] == "jewish-encyclopedia.vol_02"
    assert manifest["edition_id"] == "1901-1906"
    assert manifest["engine_family"] == "azure_read"
    assert "jewish-encyclopedia" in manifest["rendering_id"]
    assert "schaff" not in manifest["rendering_id"]


def test_je_azure_page_native_id_from_filename(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0038.azure.json")
    out_dir = tmp_path / "out"

    result = mod.normalize_je_azure_volume(raw_dir, out_dir)

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["pages"][0]["page_native_id"] == "page_0038"


def test_je_azure_page_sequence_is_page_number(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0038.azure.json")
    out_dir = tmp_path / "out"

    mod.normalize_je_azure_volume(raw_dir, out_dir)

    page = json.loads((out_dir / "pages" / "page_0038.json").read_text(encoding="utf-8"))
    assert page["page_sequence"] == 38


def test_je_azure_stamps_edition_page_key_and_clid_exempt_and_validates(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0038.azure.json")
    out_dir = tmp_path / "out"

    mod.normalize_je_azure_volume(raw_dir, out_dir)

    page = json.loads((out_dir / "pages" / "page_0038.json").read_text(encoding="utf-8"))
    assert page["edition_page_key"] == {"section": "body", "anchor": 38, "ordinal": 0}
    assert page["clid_exempt"] is True
    jsonschema.validate(instance=page, schema=_schema("sidecar-page-v1"))


def test_je_azure_page_sequence_at_least_one(tmp_path: Path) -> None:
    # Schema minimum: 1. Even page_0001 must have sequence >= 1.
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0001.azure.json")
    out_dir = tmp_path / "out"

    mod.normalize_je_azure_volume(raw_dir, out_dir)

    page = json.loads((out_dir / "pages" / "page_0001.json").read_text(encoding="utf-8"))
    assert page["page_sequence"] >= 1


def test_je_azure_page_dimensions_unit_is_pixel(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0038.azure.json", width=2048, height=2828)
    out_dir = tmp_path / "out"

    mod.normalize_je_azure_volume(raw_dir, out_dir)

    page = json.loads((out_dir / "pages" / "page_0038.json").read_text(encoding="utf-8"))
    dims = page["page_dimensions_native"]
    assert dims["width"] == 2048
    assert dims["height"] == 2828
    assert dims["unit"] == "pixel"


def test_je_azure_word_geometry_preserved(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0038.azure.json")
    out_dir = tmp_path / "out"

    mod.normalize_je_azure_volume(raw_dir, out_dir)

    page = json.loads((out_dir / "pages" / "page_0038.json").read_text(encoding="utf-8"))
    words = [w for b in page["blocks"] for ln in b["lines"] for w in ln["words"]]
    assert len(words) == 2
    assert all(isinstance(w["bbox_native"], dict) for w in words)
    assert words[0]["source_raw"] == "Jewish"
    assert words[0]["bbox_native"] == {"x": 100, "y": 80, "w": 180, "h": 60}
    assert words[0]["confidence"] == 97.1


def test_je_azure_observation_token_ids_unique(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0038.azure.json")
    out_dir = tmp_path / "out"

    mod.normalize_je_azure_volume(raw_dir, out_dir)

    page = json.loads((out_dir / "pages" / "page_0038.json").read_text(encoding="utf-8"))
    words = [w for b in page["blocks"] for ln in b["lines"] for w in ln["words"]]
    ids = [w["observation_token_id"] for w in words]
    assert len(ids) == len(set(ids))


def test_je_azure_multiple_pages_all_emitted(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    for page_num in (38, 39, 40):
        _write_azure_sidecar(raw_dir / f"page_{page_num:04d}.azure.json")
    out_dir = tmp_path / "out"

    result = mod.normalize_je_azure_volume(raw_dir, out_dir)

    assert result["emitted_pages"] == 3
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    native_ids = [p["page_native_id"] for p in manifest["pages"]]
    assert native_ids == ["page_0038", "page_0039", "page_0040"]


# ---------------------------------------------------------------------------
# Partial sidecar handling
# ---------------------------------------------------------------------------

def test_je_azure_skips_partial_sidecars(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0038.azure.json")
    _write_azure_sidecar(raw_dir / "page_0039.azure.json", partial=True)
    out_dir = tmp_path / "out"

    result = mod.normalize_je_azure_volume(raw_dir, out_dir)

    assert result["emitted_pages"] == 1
    assert result["skipped_partial"] == 1
    assert not (out_dir / "pages" / "page_0039.json").exists()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_je_azure_rerun_resumes(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0038.azure.json")
    out_dir = tmp_path / "out"

    first = mod.normalize_je_azure_volume(raw_dir, out_dir)
    second = mod.normalize_je_azure_volume(raw_dir, out_dir)

    assert first["emitted_pages"] == 1
    assert second["emitted_pages"] == 0
    assert second["skipped_pages"] == 1
    # Page must still appear in manifest on rerun.
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["pages"]) == 1
    assert manifest["pages"][0]["page_native_id"] == "page_0038"


def test_je_azure_force_reruns_existing(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _write_azure_sidecar(raw_dir / "page_0038.azure.json")
    out_dir = tmp_path / "out"

    mod.normalize_je_azure_volume(raw_dir, out_dir)
    second = mod.normalize_je_azure_volume(raw_dir, out_dir, force=True)

    assert second["emitted_pages"] == 1
    assert second["skipped_pages"] == 0


# ---------------------------------------------------------------------------
# Real-data smoke test (skip when quarantine not present)
# ---------------------------------------------------------------------------

_QUARANTINE_AZURE = (
    REPO_ROOT
    / ".shrink-quarantine"
    / "je-surrogate-phase1-20260606"
    / "raw"
    / "jewish-encyclopedia"
    / "ia-pages"
    / "vol_02"
    / "page_0038.azure.json"
)


@pytest.mark.skipif(
    not _QUARANTINE_AZURE.exists(),
    reason="quarantine azure sidecar not present",
)
def test_real_je_page_0038_normalizes(tmp_path: Path) -> None:
    raw_dir = _QUARANTINE_AZURE.parent
    out_dir = tmp_path / "out"

    result = mod.normalize_je_azure_volume(raw_dir, out_dir, repo_root=tmp_path)

    # pp 38 and 39 are present in the quarantine
    assert result["emitted_pages"] >= 2
    page = json.loads((out_dir / "pages" / "page_0038.json").read_text(encoding="utf-8"))
    assert page["rendering_id"] == mod.RENDERING_ID
    words = [w for b in page["blocks"] for ln in b["lines"] for w in ln["words"]]
    assert len(words) > 100
    assert all(isinstance(w["bbox_native"], dict) for w in words)
