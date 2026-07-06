"""R-final (R5) -- canonical_leaf_id required-or-exempt across the 4 leaf-keyed
schemas, the explicit clid_exempt marker mechanism, producer emission, and the
one-time migration that stamps the marker onto existing exempt records.

TDD contract (TEST-16). All tests are RED before the R5 implementation:
  - the helper build.lib.nsh_leaf_model.set_leaf_or_exempt does not yet exist;
  - the 4 schemas still treat canonical_leaf_id as optional and reject the
    unknown clid_exempt property (additionalProperties:false);
  - render_s2 omits clid on a leaf-less page instead of marking it exempt;
  - the stamp_clid_exempt migration tool does not yet exist.

Run failing-first:
    py -3 -m pytest -p no:cacheprovider -q tests/test_rfinal_clid_required.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"

from tests.test_render_s2_per_page import _write_bundle  # noqa: E402


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _valid(doc: dict[str, Any], schema_name: str) -> bool:
    validator = jsonschema.Draft202012Validator(_schema(schema_name))
    return validator.is_valid(doc)


# ---------------------------------------------------------------------------
# A. set_leaf_or_exempt helper (build.lib.nsh_leaf_model)
# ---------------------------------------------------------------------------


def test_set_leaf_or_exempt_int_sets_clid_only() -> None:
    from build.lib.nsh_leaf_model import set_leaf_or_exempt

    rec: dict[str, Any] = {}
    set_leaf_or_exempt(rec, 41)
    assert rec["canonical_leaf_id"] == 41
    assert "clid_exempt" not in rec


def test_set_leaf_or_exempt_none_marks_exempt_only() -> None:
    from build.lib.nsh_leaf_model import set_leaf_or_exempt

    rec: dict[str, Any] = {}
    set_leaf_or_exempt(rec, None)
    assert rec["clid_exempt"] is True
    assert "canonical_leaf_id" not in rec


def test_set_leaf_or_exempt_switches_cleanly_both_directions() -> None:
    from build.lib.nsh_leaf_model import set_leaf_or_exempt

    rec: dict[str, Any] = {"canonical_leaf_id": 7}
    set_leaf_or_exempt(rec, None)  # body -> exempt
    assert rec == {"clid_exempt": True}
    set_leaf_or_exempt(rec, 9)  # exempt -> body
    assert rec == {"canonical_leaf_id": 9}


# ---------------------------------------------------------------------------
# B. schema oneOf constraint: exactly one of {canonical_leaf_id, clid_exempt}
# ---------------------------------------------------------------------------


def _docs(tmp_path: Path) -> dict[str, tuple[str, dict[str, Any], Callable[[dict], dict]]]:
    """Return {label: (schema_name, valid_doc, get_page_record)} for the 4 schemas.

    get_page_record(doc) returns the mutable per-page record carrying the clid.
    """
    from build.lib.edition_page_key import body_edition_key
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, manifest = _write_bundle(tmp_path, page_count=1)
    # The 4 leaf-keyed schemas now require edition_page_key; the shared bundle
    # builder emits records without it, so stamp a valid body key onto the
    # sidecar page file and the manifest page_ref before rendering (render_s2
    # propagates edition_page_key from the page_ref onto the rendered page).
    page_key = body_edition_key(1)
    sidecar_path = manifest_path.parent / "pages" / "page_0001.json"
    sidecar_doc = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar_doc["edition_page_key"] = dict(page_key)
    sidecar_path.write_text(json.dumps(sidecar_doc, ensure_ascii=False), encoding="utf-8")
    manifest["pages"][0]["edition_page_key"] = dict(page_key)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "s2"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out, validate_schema=False)
    rendering_doc = json.loads(
        (out / "pages" / "page_0001.rendering-v1.json").read_text(encoding="utf-8")
    )
    wct_doc = {
        "schema_type": "word_confusion_table",
        "schema_version": "word-confusion-table-v1",
        "work_id": "schaff-herzog",
        "volume_id": "vol_01",
        "page_id": "page_0001",
        "source_image": {"path": "p.jpg", "sha256": "a" * 64},
        "coordinate_unit": "pixel",
        "coordinate_frame": "source_image",
        "image_size": [1, 1],
        "layout_authority": {"tool": "geometric", "model_version": "x", "status": "ok"},
        "available_engines": [],
        "zones": [],
        "reading_order": [],
        "positions": [],
        "layer1_ops": [],
        "edition_page_key": dict(page_key),
    }
    return {
        "sidecar-page-v1": ("sidecar-page-v1", sidecar_doc, lambda d: d),
        "sidecar-manifest-v1": ("sidecar-manifest-v1", manifest, lambda d: d["pages"][0]),
        "rendering-v1": ("rendering-v1", rendering_doc, lambda d: d["pages"][0]),
        "word-confusion-table-v1": ("word-confusion-table-v1", wct_doc, lambda d: d),
    }


@pytest.mark.parametrize("label", [
    "sidecar-page-v1", "sidecar-manifest-v1", "rendering-v1", "word-confusion-table-v1",
])
def test_int_clid_is_valid(tmp_path: Path, label: str) -> None:
    schema_name, doc, get = _docs(tmp_path)[label]
    page = get(doc)
    page.pop("clid_exempt", None)
    page["canonical_leaf_id"] = 41
    assert _valid(doc, schema_name), f"{label}: int clid should be valid"


@pytest.mark.parametrize("label", [
    "sidecar-page-v1", "sidecar-manifest-v1", "rendering-v1", "word-confusion-table-v1",
])
def test_clid_exempt_marker_is_valid(tmp_path: Path, label: str) -> None:
    schema_name, doc, get = _docs(tmp_path)[label]
    page = get(doc)
    page.pop("canonical_leaf_id", None)
    page["clid_exempt"] = True
    assert _valid(doc, schema_name), f"{label}: clid_exempt:true should be valid"


@pytest.mark.parametrize("label", [
    "sidecar-page-v1", "sidecar-manifest-v1", "rendering-v1", "word-confusion-table-v1",
])
def test_neither_clid_nor_exempt_is_rejected(tmp_path: Path, label: str) -> None:
    schema_name, doc, get = _docs(tmp_path)[label]
    page = get(doc)
    page.pop("canonical_leaf_id", None)
    page.pop("clid_exempt", None)
    assert not _valid(doc, schema_name), (
        f"{label}: a page with neither clid nor clid_exempt must be rejected after R5"
    )


@pytest.mark.parametrize("label", [
    "sidecar-page-v1", "sidecar-manifest-v1", "rendering-v1", "word-confusion-table-v1",
])
def test_both_clid_and_exempt_is_rejected(tmp_path: Path, label: str) -> None:
    schema_name, doc, get = _docs(tmp_path)[label]
    page = get(doc)
    page["canonical_leaf_id"] = 41
    page["clid_exempt"] = True
    assert not _valid(doc, schema_name), (
        f"{label}: a page must be EITHER keyed OR exempt, never both (oneOf)"
    )


@pytest.mark.parametrize("label", [
    "sidecar-page-v1", "sidecar-manifest-v1", "rendering-v1", "word-confusion-table-v1",
])
def test_clid_exempt_false_is_rejected(tmp_path: Path, label: str) -> None:
    schema_name, doc, get = _docs(tmp_path)[label]
    page = get(doc)
    page.pop("canonical_leaf_id", None)
    page["clid_exempt"] = False
    assert not _valid(doc, schema_name), f"{label}: clid_exempt must be const true"


# ---------------------------------------------------------------------------
# C. producer emission: render_s2 marks a leaf-less eligible page exempt
# ---------------------------------------------------------------------------


def test_render_s2_marks_leafless_page_exempt(tmp_path: Path) -> None:
    """A non-body (no canonical_leaf_id) eligible page_ref renders to a rendered_page
    carrying clid_exempt:true (not a bare omission), so it satisfies the R5 schema."""
    from build.lib.edition_page_key import body_edition_key
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, manifest = _write_bundle(tmp_path, page_count=1)
    # Default fixture page_ref already has no canonical_leaf_id -> non-body/exempt.
    assert "canonical_leaf_id" not in manifest["pages"][0]
    # edition_page_key is now schema-required; stamp it so the validated render passes.
    manifest["pages"][0]["edition_page_key"] = body_edition_key(1)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "s2"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out, validate_schema=True)
    doc = json.loads((out / "pages" / "page_0001.rendering-v1.json").read_text(encoding="utf-8"))
    page = doc["pages"][0]
    assert "canonical_leaf_id" not in page
    assert page.get("clid_exempt") is True


def test_render_s2_body_page_keeps_int_clid_no_exempt(tmp_path: Path) -> None:
    from build.lib.edition_page_key import body_edition_key
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, manifest = _write_bundle(tmp_path, page_count=1)
    manifest["pages"][0]["canonical_leaf_id"] = 41
    # edition_page_key is now schema-required; stamp it so the validated render passes.
    manifest["pages"][0]["edition_page_key"] = body_edition_key(41)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "s2"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out, validate_schema=True)
    page = json.loads((out / "pages" / "page_0001.rendering-v1.json").read_text(encoding="utf-8"))["pages"][0]
    assert page["canonical_leaf_id"] == 41
    assert "clid_exempt" not in page


# ---------------------------------------------------------------------------
# D. migration: stamp clid_exempt:true onto existing null-clid records
# ---------------------------------------------------------------------------


def test_stamp_record_marks_null_clid_page_exempt() -> None:
    from build.tools.ocr_pipeline.stamp_clid_exempt import stamp_page_record

    rec = {"schema_version": "sidecar-page-v1", "page_native_id": "page_0001"}
    changed = stamp_page_record(rec)
    assert changed is True
    assert rec["clid_exempt"] is True


def test_stamp_record_leaves_body_page_untouched() -> None:
    from build.tools.ocr_pipeline.stamp_clid_exempt import stamp_page_record

    rec = {"schema_version": "sidecar-page-v1", "canonical_leaf_id": 41}
    changed = stamp_page_record(rec)
    assert changed is False
    assert "clid_exempt" not in rec


def test_stamp_record_is_idempotent() -> None:
    from build.tools.ocr_pipeline.stamp_clid_exempt import stamp_page_record

    rec = {"page_native_id": "page_0001"}
    assert stamp_page_record(rec) is True
    assert stamp_page_record(rec) is False  # second pass: already exempt
    assert rec["clid_exempt"] is True
