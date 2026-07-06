"""B13 corpus fan-out tests."""

from __future__ import annotations

import json
import types
from pathlib import Path
from typing import Any

import pytest


# --- T4: --engines selection (run only the requested S1 engines) -------------
#
# The fanout always ran all five engines; --engines narrows the set so the
# geometry-only reconciliation chain does not pay for the Kraken lanes it never
# consumes. These tests stub every engine entrypoint so no real OCR runs, and
# assert exactly which engines process_volume invoked.


def _patch_engines(monkeypatch, tmp_path: Path) -> list[str]:
    """Stub each S1 engine entrypoint to record its name; return the call log.

    Each stub returns a fake summary whose manifest_path is a real minimal JSON
    file (process_volume re-reads it in the S2 loop). The S2 render is stubbed
    so the test exercises only engine selection.
    """
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    called: list[str] = []

    def _fake_summary(lineage: str) -> Any:
        manifest = tmp_path / f"{lineage}.manifest.json"
        manifest.write_text(
            json.dumps({"source_lineage_id": lineage, "pages": []}), encoding="utf-8"
        )
        return types.SimpleNamespace(manifest_path=manifest, failed_pages=0)

    def _record(name: str, lineage: str):
        def _fn(volume: int, **kwargs: Any) -> Any:
            called.append(name)
            return _fake_summary(lineage)

        return _fn

    monkeypatch.setattr(fanout, "_run_tesseract", _record("tesseract", "tesseract-py314-v1"))
    monkeypatch.setattr(fanout, "_run_surya", _record("surya", "surya-py312-v1"))
    monkeypatch.setattr(fanout, "_run_kraken", _record("kraken", "kraken-py312-v1"))
    monkeypatch.setattr(
        fanout, "_run_kraken_greek", _record("kraken-greek", "kraken-greek-py312-v1")
    )

    def _record_abbyy(volume: int, **kwargs: Any) -> list[Any]:
        called.append("abbyy")
        return [_fake_summary("ia-abbyy-v1")]

    monkeypatch.setattr(fanout, "_run_abbyy_lineages", _record_abbyy)
    # Short-circuit everything downstream of engine selection.
    monkeypatch.setattr(fanout, "_s2_render", lambda manifest_path, **kw: tmp_path / "s2.json")
    return called


def test_engines_subset_runs_only_selected(monkeypatch, tmp_path: Path) -> None:
    """T4a: engines={surya, tesseract, abbyy} runs only those, skipping Kraken."""
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    called = _patch_engines(monkeypatch, tmp_path)
    fanout.process_volume(
        1,
        s1_root=tmp_path,
        s2_root=tmp_path,
        input_root=tmp_path,
        engines={"surya", "tesseract", "abbyy"},
    )
    assert set(called) == {"surya", "tesseract", "abbyy"}
    assert "kraken" not in called
    assert "kraken-greek" not in called


def test_engines_none_runs_all_five(monkeypatch, tmp_path: Path) -> None:
    """T4b: engines=None (default) preserves backward-compatible all-engine run."""
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    called = _patch_engines(monkeypatch, tmp_path)
    fanout.process_volume(
        1,
        s1_root=tmp_path,
        s2_root=tmp_path,
        input_root=tmp_path,
        engines=None,
    )
    assert set(called) == set(fanout.ALL_ENGINES)


def test_engines_cli_rejects_unknown_engine() -> None:
    """T4c: --engines fails closed on an unknown engine name (REL-02)."""
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    with pytest.raises(SystemExit):
        fanout.main(["--volumes", "1", "--engines", "definitely-not-an-engine"])


# --- T5: per-engine timing ---------------------------------------------------


def test_process_volume_returns_engine_times_for_active_engines(
    monkeypatch, tmp_path: Path
) -> None:
    """T5: process_volume return dict includes engine_times with float seconds per active engine."""
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    called = _patch_engines(monkeypatch, tmp_path)
    result = fanout.process_volume(
        1,
        s1_root=tmp_path,
        s2_root=tmp_path,
        input_root=tmp_path,
        engines={"tesseract", "abbyy"},
    )

    assert "engine_times" in result
    times = result["engine_times"]
    assert "tesseract" in times
    assert "abbyy" in times
    # Inactive engines must not appear
    assert "surya" not in times
    assert "kraken" not in times
    assert "kraken-greek" not in times
    assert isinstance(times["tesseract"], float)
    assert isinstance(times["abbyy"], float)
    assert times["tesseract"] >= 0.0
    assert times["abbyy"] >= 0.0


def test_s2_render_prints_rendering_before_uncached_render(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An uncached S2 render emits progress before calling the slow renderer."""
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"source_lineage_id": "tesseract-py314-v1"}), encoding="utf-8"
    )
    observed_before_render: list[str] = []

    def _fake_render_manifest(*args: Any, **kwargs: Any) -> dict[str, Any]:
        observed_before_render.append(capsys.readouterr().out)
        return {}

    monkeypatch.setattr(fanout, "render_manifest", _fake_render_manifest)

    result = fanout._s2_render(
        manifest_path,
        s2_root=tmp_path / "s2",
        vol_label="vol_01",
        manifest_index=1,
        manifest_total=1,
    )

    assert result == tmp_path / "s2" / "vol_01" / "tesseract-py314-v1"
    assert observed_before_render == ["    s2 [1/1] tesseract-py314-v1: rendering...\n"]


def test_s2_render_skips_when_manifest_hash_changes_but_stable_identity_matches(
    monkeypatch, tmp_path: Path
) -> None:
    """Timestamp-only S1 manifest rewrites must not force S2 rerendering."""
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    manifest_path = tmp_path / "manifest.json"
    sidecar_path = tmp_path / "page_0001.json"
    sidecar_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    sidecar_sha = fanout._file_sha256(sidecar_path)
    sidecar_ref_path = str(sidecar_path)
    manifest_path.write_text(
        json.dumps(
            {
                "source_lineage_id": "tesseract-py314-v1",
                "rendering_id": "tesseract-py314-v1/work/edition/v1",
                "engine_family": "tesseract",
                "engine_version": "fixture-1.0",
                "volume": 1,
                "manifest_id": "sm-sha256:" + ("1" * 64),
                "pages": [
                    {
                        "page_native_id": "page_0001",
                        "status": "eligible",
                        "sidecar_page_path": sidecar_ref_path,
                        "source_payload_sha256": "sha256:" + ("2" * 64),
                    }
                ],
                "created_at": "2026-06-09T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "s2" / "vol_01" / "tesseract-py314-v1"
    index_path = output_dir / "index.json"
    output_path = output_dir / "pages" / "page_0001.rendering-v1.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "schema_version": "rendering-index-v1",
                "source_lineage_id": "tesseract-py314-v1",
                "volume": 1,
                "pages": ["page_0001"],
            }
        ),
        encoding="utf-8",
    )
    output_path.write_text(
        json.dumps(
            {
                # A real render_s2 page doc carries schema_version + a per-page
                # rendering_id; the currentness gate (mirroring Gate 1) checks both.
                "schema_version": "rendering-v1",
                "stage_version": fanout._S2_STAGE_VERSION,
                "rendering_id": "tesseract-py314-v1/work/edition/v1",
                "engine_family": "tesseract",
                "engine_version": "fixture-1.0",
                "source_lineage_id": "tesseract-py314-v1",
                "volume": 1,
                "source_sidecar_refs": [
                    {
                        "path": "manifest.json",
                        "sha256": "sha256:" + ("0" * 64),
                    },
                    {"path": sidecar_ref_path, "sha256": sidecar_sha},
                ],
                "pages": [
                    {
                        "manifest_id": "sm-sha256:" + ("1" * 64),
                        "rendering_id": "tesseract-py314-v1/work/edition/v1",
                        "page_native_id": "page_0001",
                        "source_payload_sha256": "sha256:" + ("2" * 64),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: list[Path] = []

    def _fake_render_manifest(manifest_path: Path, **kwargs: Any) -> dict[str, Any]:
        calls.append(manifest_path)
        return {}

    monkeypatch.setattr(fanout, "render_manifest", _fake_render_manifest)

    result = fanout._s2_render(
        manifest_path,
        s2_root=tmp_path / "s2",
        vol_label="vol_01",
        manifest_index=1,
        manifest_total=1,
    )

    assert result == output_dir
    assert calls == []
    assert json.loads(output_path.read_text(encoding="utf-8"))["source_sidecar_refs"][0][
        "sha256"
    ] == "sha256:" + ("0" * 64)


def test_s2_render_rerenders_when_sidecar_ref_is_stale(
    monkeypatch, tmp_path: Path
) -> None:
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    manifest_path = tmp_path / "manifest.json"
    sidecar_path = tmp_path / "page_0001.json"
    sidecar_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    sidecar_ref_path = str(sidecar_path)
    manifest_path.write_text(
        json.dumps(
            {
                "source_lineage_id": "tesseract-py314-v1",
                "rendering_id": "tesseract-py314-v1/work/edition/v1",
                "engine_family": "tesseract",
                "engine_version": "fixture-1.0",
                "volume": 1,
                "manifest_id": "sm-sha256:" + ("1" * 64),
                "pages": [
                    {
                        "page_native_id": "page_0001",
                        "status": "eligible",
                        "sidecar_page_path": sidecar_ref_path,
                        "source_payload_sha256": "sha256:" + ("2" * 64),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "s2" / "vol_01" / "tesseract-py314-v1"
    output_path = output_dir / "pages" / "page_0001.rendering-v1.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.json").write_text(
        json.dumps({"schema_version": "rendering-index-v1", "pages": ["page_0001"]}),
        encoding="utf-8",
    )
    output_path.write_text(
        json.dumps(
            {
                "stage_version": fanout._S2_STAGE_VERSION,
                "rendering_id": "tesseract-py314-v1/work/edition/v1",
                "engine_family": "tesseract",
                "engine_version": "fixture-1.0",
                "source_lineage_id": "tesseract-py314-v1",
                "volume": 1,
                "source_sidecar_refs": [
                    {"path": "manifest.json", "sha256": "sha256:" + ("0" * 64)},
                    {"path": sidecar_ref_path, "sha256": "sha256:" + ("0" * 64)},
                ],
                "pages": [
                    {
                        "manifest_id": "sm-sha256:" + ("1" * 64),
                        "page_native_id": "page_0001",
                        "source_payload_sha256": "sha256:" + ("2" * 64),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: list[Path] = []

    def _fake_render_manifest(manifest_path: Path, **kwargs: Any) -> dict[str, Any]:
        calls.append(manifest_path)
        return {}

    monkeypatch.setattr(fanout, "render_manifest", _fake_render_manifest)

    fanout._s2_render(
        manifest_path,
        s2_root=tmp_path / "s2",
        vol_label="vol_01",
        manifest_index=1,
        manifest_total=1,
    )

    assert calls == [manifest_path]


# --- T6: geometry preset -----------------------------------------------------


def test_resolve_engines_expands_geometry_preset() -> None:
    """T6a: 'geometry' token expands to GEOMETRY_PRESET {surya, tesseract, abbyy}.

    _resolve_engines returns a list (order matters for engine processing); compare
    set content against the frozenset constant, not type-equal.
    """
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    result = fanout._resolve_engines(["geometry"])
    assert set(result) == fanout.GEOMETRY_PRESET


def test_resolve_engines_geometry_combined_with_explicit_name() -> None:
    """T6b: geometry preset can be combined with an explicit engine name."""
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    result = fanout._resolve_engines(["geometry", "kraken"])
    assert set(result) == fanout.GEOMETRY_PRESET | {"kraken"}


def test_resolve_engines_none_returns_none() -> None:
    """T6c: None (omit --engines) resolves to None (run all, backward-compatible)."""
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    assert fanout._resolve_engines(None) is None
    assert fanout._resolve_engines([]) is None


def test_geometry_preset_runs_only_geometry_engines(monkeypatch, tmp_path: Path) -> None:
    """T6d: _resolve_engines(['geometry']) runs surya/tesseract/abbyy, skips Kraken lanes."""
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    called = _patch_engines(monkeypatch, tmp_path)
    fanout.process_volume(
        1,
        s1_root=tmp_path,
        s2_root=tmp_path,
        input_root=tmp_path,
        engines=fanout._resolve_engines(["geometry"]),
    )
    assert set(called) == {"surya", "tesseract", "abbyy"}
    assert "kraken" not in called
    assert "kraken-greek" not in called


# --- T7: ABBYY is imported OCR, not live OCR ---------------------------------


def test_abbyy_classified_as_imported_not_live_ocr() -> None:
    """T7: ABBYY is in IMPORTED_OCR_ENGINES and absent from LIVE_OCR_ENGINES.

    Verifies the conceptual separation: live engines run inference on page
    images; ABBYY ingests pre-computed FineReader output from Internet Archive.
    """
    from build.tools.ocr_pipeline import run_ocr_pipeline as fanout

    assert "abbyy" in fanout.IMPORTED_OCR_ENGINES
    assert "abbyy" not in fanout.LIVE_OCR_ENGINES
    # No engine belongs to both categories
    assert set(fanout.LIVE_OCR_ENGINES) & set(fanout.IMPORTED_OCR_ENGINES) == set()
    # Together they cover ALL_ENGINES exactly
    assert set(fanout.ALL_ENGINES) == set(fanout.LIVE_OCR_ENGINES) | set(fanout.IMPORTED_OCR_ENGINES)
