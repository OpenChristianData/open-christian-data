"""R-final.1 — tests for the abbyy/azure S2 clid re-key path.

The re-key reuses render_s2's own derivation (which now stamps canonical_leaf_id
because S1 carries it) and skips the redundant rendering-v1 jsonschema
re-validation -- the expensive part (~716 ms/page) and a pure read-only gate, so
skipping it cannot change output bytes. Two foundations are proven here:

1. render_manifest(validate_schema=False) is byte-identical to the validated
   render for valid input, and actually gates the jsonschema check (TEST-09
   true-positive / true-negative).
2. The rekey_s2_renderings tool stamps canonical_leaf_id onto body pages equal
   to the S1 manifest's leaf, and its completeness check fails closed when a
   rendered page is missing clid.

Run failing-first:
    py -3 -m pytest -p no:cacheprovider -q tests/test_rekey_s2_renderings.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.edition_page_key import body_edition_key  # noqa: E402
from tests.test_render_s2_per_page import _write_bundle  # noqa: E402


def _read_pages(pages_dir: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(pages_dir.glob("*.rendering-v1.json"))}


def _stamp_edition_keys(manifest_path: Path, manifest: dict[str, Any]) -> None:
    """Backfill the now-required edition_page_key onto the shared bundle's manifest
    page_refs and their sidecar page files so a validated render passes."""
    for page_ref in manifest["pages"]:
        key = body_edition_key(page_ref["page_sequence"])
        page_ref["edition_page_key"] = dict(key)
        sidecar_path = manifest_path.parent.parent.parent / page_ref["sidecar_page_path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["edition_page_key"] = dict(key)
        sidecar_path.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Foundation 1 — render_s2.render_manifest(validate_schema=...)
# ---------------------------------------------------------------------------


def test_validate_schema_false_is_byte_identical_to_validated_render(tmp_path: Path) -> None:
    """Skipping jsonschema validation must not change a single output byte."""
    from build.tools.ocr_pipeline.render_s2 import render_manifest

    manifest_path, manifest = _write_bundle(tmp_path, page_count=3)
    _stamp_edition_keys(manifest_path, manifest)

    out_validated = tmp_path / "validated"
    out_skipped = tmp_path / "skipped"
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out_validated, validate_schema=True)
    render_manifest(manifest_path, repo_root=tmp_path, output_dir=out_skipped, validate_schema=False)

    validated = _read_pages(out_validated / "pages")
    skipped = _read_pages(out_skipped / "pages")
    assert validated.keys() == skipped.keys()
    for name in validated:
        assert validated[name] == skipped[name], f"{name} differs between validated and skipped render"


def test_validate_schema_true_rejects_a_schema_violating_doc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With validation ON, an impossible schema must make the write fail closed."""
    from build.lib.atomic_io import SchemaValidationError
    from build.tools.ocr_pipeline import render_s2

    impossible = tmp_path / "impossible.schema.json"
    impossible.write_text(
        json.dumps({"type": "object", "required": ["__field_that_never_exists__"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(render_s2, "SCHEMA_PATH", impossible)

    manifest_path, _ = _write_bundle(tmp_path)
    with pytest.raises(SchemaValidationError):
        render_s2.render_manifest(
            manifest_path, repo_root=tmp_path, output_dir=tmp_path / "out", validate_schema=True
        )


def test_validate_schema_false_skips_the_jsonschema_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With validation OFF, the same impossible schema must be ignored (write succeeds)."""
    from build.tools.ocr_pipeline import render_s2

    impossible = tmp_path / "impossible.schema.json"
    impossible.write_text(
        json.dumps({"type": "object", "required": ["__field_that_never_exists__"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(render_s2, "SCHEMA_PATH", impossible)

    manifest_path, _ = _write_bundle(tmp_path)
    out = tmp_path / "out"
    result = render_s2.render_manifest(
        manifest_path, repo_root=tmp_path, output_dir=out, validate_schema=False
    )
    assert result["written"] == 1
    assert (out / "pages" / "page_0001.rendering-v1.json").exists()


# ---------------------------------------------------------------------------
# Foundation 2 — the rekey_s2_renderings tool
# ---------------------------------------------------------------------------


def _bundle_with_leaf(tmp_path: Path, leaf: int = 41) -> Path:
    """A one-page abbyy bundle whose S1 page_ref carries canonical_leaf_id=leaf."""
    manifest_path, manifest = _write_bundle(
        tmp_path, engine_family="abbyy", rendering_id="ia-abbyy-v1/r",
        source_lineage_id="ia-abbyy-v1",
    )
    manifest["pages"][0]["canonical_leaf_id"] = leaf
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def test_rekey_cell_stamps_leaf_onto_body_pages(tmp_path: Path) -> None:
    """rekey_cell renders the cell with clid stamped from the S1 manifest leaf."""
    from build.tools.ocr_pipeline.rekey_s2_renderings import rekey_cell

    manifest_path = _bundle_with_leaf(tmp_path, leaf=41)
    out = tmp_path / "s2cell"
    report = rekey_cell(manifest_path, repo_root=tmp_path, output_dir=out)

    doc = json.loads((out / "pages" / "page_0001.rendering-v1.json").read_text(encoding="utf-8"))
    assert doc["pages"][0]["canonical_leaf_id"] == 41
    assert report["body_pages_with_clid"] == 1
    assert report["body_pages_missing_clid"] == 0
    assert report["ok"] is True


def test_verify_cell_clid_fails_closed_when_body_leaf_render_missing_clid(tmp_path: Path) -> None:
    """A page_ref carrying clid (body leaf) whose rendered page lacks clid is a failure.

    Mirrors verify_leaf_keying._verify_s2_cell: every S1 body leaf (page_ref with
    canonical_leaf_id) must have a rendered page carrying that exact leaf; a render
    missing it is a stamping break, not an exempt non-body page.
    """
    from build.tools.ocr_pipeline.rekey_s2_renderings import verify_cell_clid

    manifest = {"pages": [{"page_native_id": "page_0001", "status": "eligible",
                           "source_payload_sha256": "sha256:" + "1" * 64,
                           "canonical_leaf_id": 41}]}
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    # Rendered page exists but carries NO canonical_leaf_id.
    (pages_dir / "page_0001.rendering-v1.json").write_text(
        json.dumps({"schema_version": "rendering-v1",
                    "pages": [{"page_native_id": "page_0001",
                               "source_payload_sha256": "sha256:" + "1" * 64}]}),
        encoding="utf-8",
    )
    report = verify_cell_clid(pages_dir, manifest)
    assert report["body_pages_missing_clid"] == 1
    assert report["ok"] is False


def test_rekey_cell_allow_stale_manifest_renders_without_raising(tmp_path: Path) -> None:
    """A cell whose S1 manifest lags its on-disk sidecars must re-key under the
    non-mutating allow_stale_manifest path (render per the manifest; never reindex S1)."""
    from build.tools.ocr_pipeline.rekey_s2_renderings import rekey_cell

    manifest_path = _bundle_with_leaf(tmp_path, leaf=41)
    # One extra sidecar on disk the manifest does not list -> stale-manifest guard.
    extra = manifest_path.parent / "pages" / "page_0002.json"
    extra.write_text("{}", encoding="utf-8")

    report = rekey_cell(
        manifest_path, repo_root=tmp_path, output_dir=tmp_path / "cell", allow_stale_manifest=True
    )
    assert report["ok"] is True
    assert report["body_pages_with_clid"] == 1


def test_verify_cell_clid_exempts_nonbody_refs_without_clid(tmp_path: Path) -> None:
    """A page_ref with no clid (non-body/exempt) whose render also lacks clid is NOT a failure."""
    from build.tools.ocr_pipeline.rekey_s2_renderings import verify_cell_clid

    manifest = {"pages": [{"page_native_id": "page_0001", "status": "eligible",
                           "source_payload_sha256": "sha256:" + "2" * 64}]}
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "page_0001.rendering-v1.json").write_text(
        json.dumps({"schema_version": "rendering-v1",
                    "pages": [{"page_native_id": "page_0001",
                               "source_payload_sha256": "sha256:" + "2" * 64}]}),
        encoding="utf-8",
    )
    report = verify_cell_clid(pages_dir, manifest)
    assert report["body_pages_missing_clid"] == 0
    assert report["ok"] is True
