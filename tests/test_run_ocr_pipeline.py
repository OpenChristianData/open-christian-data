from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from build.tools.ocr_pipeline.run_ocr_pipeline import (
    ABBYY_LINEAGES,
    _Tee,
    _doctor_lineages_for_engines,
    _parse_pages_arg,
    _resolve_engines,
    _run_abbyy_lineages,
    main,
    process_volume,
)
from build.tools.ocr_pipeline import run_ocr_pipeline as pipeline


FAILING_SUMMARY = {
    "volume": 1,
    "s1_count": 0,
    "s2_count": 0,
    "s1_failures": {"tesseract": "some error"},
    "s2_failures": {},
    "engine_times": {},
}

CLEAN_SUMMARY = {**FAILING_SUMMARY, "s1_failures": {}, "s1_count": 1}


def test_parse_pages_arg_valid_integers() -> None:
    assert _parse_pages_arg(["3", "1", "3"]) == [1, 3]


def test_parse_pages_arg_valid_range() -> None:
    assert _parse_pages_arg(["1-3", "5"]) == [1, 2, 3, 5]


def test_parse_pages_arg_empty_returns_none() -> None:
    assert _parse_pages_arg([]) is None


def test_parse_pages_arg_reversed_range_raises() -> None:
    with pytest.raises(ValueError, match="reversed"):
        _parse_pages_arg(["5-1"])


def test_parse_pages_arg_page_zero_raises() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        _parse_pages_arg(["0"])


def test_parse_pages_arg_negative_raises() -> None:
    with pytest.raises(ValueError):
        _parse_pages_arg(["-1"])


def test_parse_pages_arg_empty_result_raises() -> None:
    with pytest.raises(ValueError):
        _parse_pages_arg(["3-1"])


def test_resolve_engines_none_returns_none() -> None:
    assert _resolve_engines(None) is None


def test_resolve_engines_geometry_expands() -> None:
    assert _resolve_engines(["geometry"]) == ["surya", "tesseract", "abbyy"]


def test_resolve_engines_deduplicates() -> None:
    assert _resolve_engines(["tesseract", "tesseract"]) == ["tesseract"]


def test_resolve_engines_geometry_plus_kraken() -> None:
    assert _resolve_engines(["geometry", "kraken"]) == [
        "surya",
        "tesseract",
        "abbyy",
        "kraken",
    ]


def test_doctor_lineages_expand_abbyy_selector() -> None:
    assert _doctor_lineages_for_engines(["abbyy"]) == ABBYY_LINEAGES


def test_doctor_lineages_expand_default_to_all_lineages() -> None:
    lineages = _doctor_lineages_for_engines(None)

    assert lineages[:4] == [
        "tesseract-py314-v1",
        "surya-py312-v1",
        "kraken-py312-v1",
        "kraken-greek-py312-v1",
    ]
    assert lineages[4:] == ABBYY_LINEAGES


def test_run_abbyy_lineages_returns_tuple(tmp_path: Path) -> None:
    summary = MagicMock()
    with patch(
        "build.tools.ocr_pipeline.run_ocr_pipeline.normalize_abbyy_rich_volume",
        return_value=summary,
    ):
        summaries, failures = _run_abbyy_lineages(
            1,
            s1_root=tmp_path / "s1",
            input_root=tmp_path / "input",
            repo_root=tmp_path,
        )

    assert summaries == [summary] * len(ABBYY_LINEAGES)
    assert failures == {}


def test_run_abbyy_lineages_unexpected_exception_goes_to_failures_not_raises(
    tmp_path: Path,
) -> None:
    with patch(
        "build.tools.ocr_pipeline.run_ocr_pipeline.normalize_abbyy_rich_volume",
        side_effect=RuntimeError("broken sidecar"),
    ):
        summaries, failures = _run_abbyy_lineages(
            1,
            s1_root=tmp_path / "s1",
            input_root=tmp_path / "input",
            repo_root=tmp_path,
        )

    assert summaries == []
    assert failures == {lineage: "broken sidecar" for lineage in ABBYY_LINEAGES}


def test_run_abbyy_lineages_filenotfounderror_is_skipped(tmp_path: Path) -> None:
    with patch(
        "build.tools.ocr_pipeline.run_ocr_pipeline.normalize_abbyy_rich_volume",
        side_effect=FileNotFoundError,
    ):
        summaries, failures = _run_abbyy_lineages(
            1,
            s1_root=tmp_path / "s1",
            input_root=tmp_path / "input",
            repo_root=tmp_path,
        )

    assert summaries == []
    assert failures == {}


def test_process_volume_marks_abbyy_failure_when_no_sidecars(
    tmp_path: Path,
) -> None:
    with patch(
        "build.tools.ocr_pipeline.run_ocr_pipeline._run_abbyy_lineages",
        return_value=([], {}),
    ):
        summary = process_volume(
            1,
            s1_root=tmp_path / "s1",
            s2_root=tmp_path / "s2",
            input_root=tmp_path / "input",
            engines=["abbyy"],
        )

    assert summary["s1_failures"] == {
        "abbyy": "no ABBYY sidecars found for selected volume/pages"
    }
    assert summary["s1_count"] == 0


def test_tee_writes_log_with_path_open(tmp_path: Path) -> None:
    log_path = tmp_path / "ocr.log"
    tee = _Tee(log_path)
    try:
        tee.write("hello\n")
        tee.flush()
    finally:
        tee.close()

    assert log_path.read_text(encoding="utf-8") == "hello\n"


def test_tee_flush_and_write_after_close_do_not_raise(tmp_path: Path) -> None:
    log_path = tmp_path / "ocr.log"
    tee = _Tee(log_path)
    tee.close()
    # Python's interpreter-shutdown flush must not raise ValueError on a closed Tee.
    tee.flush()
    tee.write("ignored\n")


def _main_args(tmp_path: Path, *extra: str) -> list[str]:
    input_root = tmp_path / "input"
    (input_root / "vol_01").mkdir(parents=True)
    return [
        "--volumes",
        "1",
        "--engines",
        "tesseract",
        "--input-root",
        str(input_root),
        "--s1-root",
        str(tmp_path / "s1"),
        "--s2-root",
        str(tmp_path / "s2"),
        *extra,
    ]


def _install_test_tee() -> tuple[io.StringIO, object, object]:
    original_stdout = sys.stdout
    sink = io.StringIO()

    def fake_init(self, _log_path: Path) -> None:
        self._stdout = sink
        self._log = sink

    return sink, patch(
        "build.tools.ocr_pipeline.run_ocr_pipeline._Tee.__init__",
        fake_init,
    ), original_stdout


def test_main_returns_nonzero_on_s1_failure(tmp_path: Path) -> None:
    _sink, tee_patch, original_stdout = _install_test_tee()
    try:
        with tee_patch, patch(
            "build.tools.ocr_pipeline.run_ocr_pipeline.process_volume",
            return_value=FAILING_SUMMARY,
        ):
            assert main(_main_args(tmp_path)) == 1
    finally:
        sys.stdout = original_stdout


def test_main_returns_zero_with_allow_partial(tmp_path: Path) -> None:
    _sink, tee_patch, original_stdout = _install_test_tee()
    try:
        with tee_patch, patch(
            "build.tools.ocr_pipeline.run_ocr_pipeline.process_volume",
            return_value=FAILING_SUMMARY,
        ):
            assert main(_main_args(tmp_path, "--allow-partial")) == 0
    finally:
        sys.stdout = original_stdout


def test_main_doctor_first_exits_before_processing_when_doctor_fails(
    tmp_path: Path,
) -> None:
    _sink, tee_patch, original_stdout = _install_test_tee()
    try:
        with tee_patch, patch(
            "build.tools.ocr_pipeline.run_ocr_pipeline._run_doctor_preflight",
            return_value=1,
        ), patch(
            "build.tools.ocr_pipeline.run_ocr_pipeline.process_volume",
            side_effect=AssertionError("process_volume should not run"),
        ):
            assert main(_main_args(tmp_path, "--doctor-first")) == 2
    finally:
        sys.stdout = original_stdout


def test_main_resume_runs_doctor_and_clears_stale_stop_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop_sentinel = tmp_path / ".pipeline_stop_requested"
    stop_sentinel.write_text("stop\n", encoding="utf-8")
    monkeypatch.setattr(pipeline, "_STOP_SENTINEL", stop_sentinel)
    doctor_calls: list[tuple[list[int], list[str] | None, Path]] = []

    def fake_doctor(
        volumes: list[int],
        engines: list[str] | None,
        *,
        s1_root: Path,
    ) -> int:
        doctor_calls.append((volumes, engines, s1_root))
        return 0

    _sink, tee_patch, original_stdout = _install_test_tee()
    try:
        with tee_patch, patch(
            "build.tools.ocr_pipeline.run_ocr_pipeline._run_doctor_preflight",
            fake_doctor,
        ), patch(
            "build.tools.ocr_pipeline.run_ocr_pipeline.process_volume",
            return_value=CLEAN_SUMMARY,
        ):
            assert main(_main_args(tmp_path, "--resume")) == 0
    finally:
        sys.stdout = original_stdout

    assert doctor_calls == [([1], ["tesseract"], tmp_path / "s1")]
    assert not stop_sentinel.exists()


def test_main_returns_two_on_invalid_volumes() -> None:
    assert main(["--volumes", "0"]) == 2


def test_main_returns_two_on_reversed_pages() -> None:
    assert main(["--volumes", "1", "--pages", "5-1"]) == 2


def test_tee_flush_after_close_does_not_raise(tmp_path: Path) -> None:
    # main() registers atexit.register(sys.stdout.close), which closes the Tee's
    # log file; the interpreter's final stdout flush at shutdown then calls
    # _Tee.flush() on the closed log. Before the fix that raised ValueError("I/O
    # operation on closed file") and Python exited 120, clobbering main()'s real
    # 0/1 return code. flush()/write() after close must be no-ops on the log.
    tee = _Tee(tmp_path / "tee.log")
    tee.close()
    tee.flush()
    tee.write("after close")


def test_tee_close_is_idempotent(tmp_path: Path) -> None:
    tee = _Tee(tmp_path / "tee.log")
    tee.close()
    tee.close()
