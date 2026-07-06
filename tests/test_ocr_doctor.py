from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tools.ocr_pipeline.sidecar_utils import count_sidecars
from build.tools.ocr_pipeline.ocr_doctor import KNOWN_ENGINES, check_engine_volume, run_doctor


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh)
        fh.write("\n")


def _write_sidecar(
    pages_dir: Path,
    stem: str,
    *,
    failure_class: str | None = None,
    page_native_id: str | None = None,
) -> None:
    extras: dict = {}
    if failure_class:
        extras["failure_class"] = failure_class
    _write_json(
        pages_dir / f"{stem}.json",
        {"page_native_id": page_native_id or stem, "page_extras_carried": extras},
    )


def _write_corrupt_sidecar(pages_dir: Path, stem: str) -> None:
    path = pages_dir / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not valid json {{{", encoding="utf-8")


def _write_manifest(run_dir: Path, page_count: int) -> None:
    pages = [
        {
            "page_native_id": f"p{i:03d}",
            "status": "eligible",
            "sidecar_page_path": f"p{i:03d}.json",
            "source_payload_sha256": "sha256:" + "0" * 64,
        }
        for i in range(page_count)
    ]
    _write_json(run_dir / "manifest.json", {"pages": pages})


def _write_state(run_dir: Path, emitted_count: int) -> None:
    _write_json(
        run_dir / "manifest.state.json",
        {"emitted_pages": [f"p{i:03d}" for i in range(emitted_count)]},
    )


def test_known_engines_include_all_abbyy_lineages() -> None:
    assert "ia-abbyy-v1" in KNOWN_ENGINES
    assert "ia-abbyy-haucgoog-v1" in KNOWN_ENGINES
    assert "ia-abbyy-dli-v1" in KNOWN_ENGINES
    assert "ia-abbyy-haucgoog-c1-v1" in KNOWN_ENGINES
    assert "ia-abbyy-haucgoog-c2-v1" in KNOWN_ENGINES
    assert "ia-abbyy-haucgoog-c3-v1" in KNOWN_ENGINES
    assert "ia-abbyy-haucgoog-c4-v1" in KNOWN_ENGINES


# ---------------------------------------------------------------------------
# count_sidecars
# ---------------------------------------------------------------------------


def test_count_sidecars_returns_zero_for_empty_dir(tmp_path: Path) -> None:
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    assert count_sidecars(pages_dir) == 0


def test_count_sidecars_counts_only_sidecar_json_files(tmp_path: Path) -> None:
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    (pages_dir / "a.json").write_text("{}", encoding="utf-8")
    (pages_dir / "b.json").write_text("{}", encoding="utf-8")
    (pages_dir / "a.rendering-v1.json").write_text("{}", encoding="utf-8")
    (pages_dir / "c.txt").write_text("text", encoding="utf-8")
    assert count_sidecars(pages_dir) == 2


def test_count_sidecars_returns_zero_for_missing_dir(tmp_path: Path) -> None:
    pages_dir = tmp_path / "nonexistent" / "pages"
    assert count_sidecars(pages_dir) == 0


# ---------------------------------------------------------------------------
# check_engine_volume
# ---------------------------------------------------------------------------


def test_check_engine_volume_ok_when_counts_match(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    for i in range(3):
        _write_sidecar(pages_dir, f"p{i:03d}")
    _write_manifest(run_dir, 3)
    _write_state(run_dir, 3)

    report = check_engine_volume("tesseract-py314-v1", 1, output_root=tmp_path)

    assert report["sidecar_count"] == 3
    assert report["manifest_count"] == 3
    assert report["state_count"] == 3
    assert report["drift"] is False
    assert report["failed"] == 0
    assert report["corrupt"] == 0


def test_check_engine_volume_drift_when_sidecars_exceed_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    for i in range(5):
        _write_sidecar(pages_dir, f"p{i:03d}")
    _write_manifest(run_dir, 3)
    _write_state(run_dir, 5)

    report = check_engine_volume("tesseract-py314-v1", 1, output_root=tmp_path)

    assert report["sidecar_count"] == 5
    assert report["manifest_count"] == 3
    assert report["drift"] is True


def test_check_engine_volume_drift_when_sidecars_exceed_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    for i in range(5):
        _write_sidecar(pages_dir, f"p{i:03d}")
    _write_manifest(run_dir, 5)
    _write_state(run_dir, 2)

    report = check_engine_volume("tesseract-py314-v1", 1, output_root=tmp_path)

    assert report["sidecar_count"] == 5
    assert report["state_count"] == 2
    assert report["drift"] is True


def test_check_engine_volume_drift_when_manifest_absent(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    for i in range(3):
        _write_sidecar(pages_dir, f"p{i:03d}")

    report = check_engine_volume("tesseract-py314-v1", 1, output_root=tmp_path)

    assert report["manifest_count"] is None
    assert report["state_count"] is None
    assert report["drift"] is True


def test_check_engine_volume_no_drift_when_no_sidecars_and_no_manifest(tmp_path: Path) -> None:
    report = check_engine_volume("tesseract-py314-v1", 1, output_root=tmp_path)

    assert report["sidecar_count"] == 0
    assert report["manifest_count"] is None
    assert report["drift"] is False


def test_check_engine_volume_counts_failed_sidecars(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    _write_sidecar(pages_dir, "p000")
    _write_sidecar(pages_dir, "p001", failure_class="ocr_subprocess_error")
    _write_sidecar(pages_dir, "p002", failure_class="image_missing")

    report = check_engine_volume("tesseract-py314-v1", 1, output_root=tmp_path)

    assert report["sidecar_count"] == 3
    assert report["failed"] == 2


def test_check_engine_volume_counts_corrupt_sidecars(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    _write_sidecar(pages_dir, "p000")
    _write_corrupt_sidecar(pages_dir, "p001")

    report = check_engine_volume("tesseract-py314-v1", 1, output_root=tmp_path)

    assert report["sidecar_count"] == 2
    assert report["corrupt"] == 1
    assert report["failed"] == 0


def test_check_engine_volume_corrupt_sidecar_not_double_counted_as_failed(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    _write_corrupt_sidecar(pages_dir, "p000")

    report = check_engine_volume("tesseract-py314-v1", 1, output_root=tmp_path)

    assert report["corrupt"] == 1
    assert report["failed"] == 0


def test_check_engine_volume_reports_missing_manifest_and_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    _write_sidecar(pages_dir, "p000")

    report = check_engine_volume("tesseract-py314-v1", 1, output_root=tmp_path)

    assert report["missing_manifest"] is True
    assert report["missing_state"] is True
    assert report["drift"] is True


def test_check_engine_volume_counts_duplicate_page_native_ids(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    _write_sidecar(pages_dir, "p000", page_native_id="same")
    _write_sidecar(pages_dir, "p001", page_native_id="same")
    _write_manifest(run_dir, 2)
    _write_state(run_dir, 2)

    report = check_engine_volume("tesseract-py314-v1", 1, output_root=tmp_path)

    assert report["duplicate_native_ids"] == 1
    assert report["drift"] is True


# ---------------------------------------------------------------------------
# run_doctor exit codes
# ---------------------------------------------------------------------------


def test_run_doctor_exits_zero_when_no_drift(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    for i in range(3):
        _write_sidecar(pages_dir, f"p{i:03d}")
    _write_manifest(run_dir, 3)
    _write_state(run_dir, 3)

    exit_code = run_doctor(
        volumes=[1],
        engines=["tesseract-py314-v1"],
        output_root=tmp_path,
    )
    assert exit_code == 0


def test_run_doctor_exits_one_when_drift_detected(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    for i in range(5):
        _write_sidecar(pages_dir, f"p{i:03d}")
    _write_manifest(run_dir, 3)
    _write_state(run_dir, 5)

    exit_code = run_doctor(
        volumes=[1],
        engines=["tesseract-py314-v1"],
        output_root=tmp_path,
    )
    assert exit_code == 1


def test_run_doctor_exits_one_when_failed_sidecar_exists(tmp_path: Path) -> None:
    run_dir = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True)
    _write_sidecar(pages_dir, "p000", failure_class="subprocess_timeout_batch")
    _write_manifest(run_dir, 1)
    _write_state(run_dir, 0)

    exit_code = run_doctor(
        volumes=[1],
        engines=["tesseract-py314-v1"],
        output_root=tmp_path,
    )
    assert exit_code == 1


def test_run_doctor_exits_zero_when_no_sidecars_exist(tmp_path: Path) -> None:
    exit_code = run_doctor(
        volumes=[1],
        engines=["tesseract-py314-v1"],
        output_root=tmp_path,
    )
    assert exit_code == 0


def test_run_doctor_exits_one_when_any_engine_has_drift(tmp_path: Path) -> None:
    # engine A: OK
    run_dir_a = tmp_path / "tesseract-py314-v1" / "vol_01"
    pages_dir_a = run_dir_a / "pages"
    pages_dir_a.mkdir(parents=True)
    for i in range(3):
        _write_sidecar(pages_dir_a, f"p{i:03d}")
    _write_manifest(run_dir_a, 3)

    # engine B: drift
    run_dir_b = tmp_path / "kraken-py312-v1" / "vol_01"
    pages_dir_b = run_dir_b / "pages"
    pages_dir_b.mkdir(parents=True)
    for i in range(5):
        _write_sidecar(pages_dir_b, f"p{i:03d}")
    _write_manifest(run_dir_b, 3)

    exit_code = run_doctor(
        volumes=[1],
        engines=["tesseract-py314-v1", "kraken-py312-v1"],
        output_root=tmp_path,
    )
    assert exit_code == 1
