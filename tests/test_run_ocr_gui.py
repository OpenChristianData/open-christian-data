from __future__ import annotations

import subprocess
import types

import pytest

from build.tools.ocr_pipeline import run_ocr_gui


class _Var:
    """Minimal stand-in for tk.BooleanVar / tk.StringVar."""

    def __init__(self, value=None):
        self._val = value

    def get(self):
        return self._val

    def set(self, v):
        self._val = v


class _Bar(types.SimpleNamespace):
    def __setitem__(self, key, value):
        setattr(self, key, value)


def _make_gui(
    *,
    vols=None,
    engine_order=None,
    enabled=None,
    throttle="Full speed",
    pages="",
    surya_width="2500",
    allow_partial=False,
    dry_run=False,
    doctor_first=False,
    allow_stale_manifest=False,
    resume=False,
    input_root="",
    s1_root="",
    s2_root="",
):
    """Build a headless PipelineGui with fake tk vars - no display needed."""
    g = object.__new__(run_ocr_gui.PipelineGui)
    g._vol_vars = [_Var(v) for v in (vols if vols is not None else [True] * 13)]
    g._engine_order = list(
        engine_order if engine_order is not None else run_ocr_gui._ENGINES
    )
    g._engine_enabled = {
        n: _Var(enabled.get(n, True) if enabled else True)
        for n in g._engine_order
    }
    g._throttle_var = _Var(throttle)
    g._pages_var = _Var(pages)
    g._surya_width_var = _Var(surya_width)
    g._allow_partial_var = _Var(allow_partial)
    g._dry_run_var = _Var(dry_run)
    g._doctor_first_var = _Var(doctor_first)
    g._allow_stale_manifest_var = _Var(allow_stale_manifest)
    g._resume_var = _Var(resume)
    g._input_root_var = _Var(input_root)
    g._s1_root_var = _Var(s1_root)
    g._s2_root_var = _Var(s2_root)
    return g


def test_build_args_all_defaults_passes_gui_surya_default():
    """All-default state passes the GUI's Surya performance default."""
    g = _make_gui()
    assert g._build_args() == ["--surya-max-width", "2500"]


def test_build_args_subset_volumes():
    vols = [True, True, False] + [False] * 10
    g = _make_gui(vols=vols)
    args = g._build_args()
    assert "--volumes" in args
    idx = args.index("--volumes")
    assert args[idx + 1] == "1"
    assert args[idx + 2] == "2"


def test_build_args_no_volumes_falls_back_to_vol1():
    """Nothing selected: GUI falls back to vol 1 rather than crashing."""
    g = _make_gui(vols=[False] * 13)
    args = g._build_args()
    assert "--volumes" in args
    assert "1" in args


def test_build_args_engine_subset_passes_engines_flag():
    enabled = {n: (n == "tesseract") for n in run_ocr_gui._ENGINES}
    g = _make_gui(enabled=enabled)
    args = g._build_args()
    assert "--engines" in args
    idx = args.index("--engines")
    assert args[idx + 1] == "tesseract"


def test_build_args_no_engines_selected_omits_engines_flag():
    """Zero engines selected: _build_args omits --engines.

    The blocking logic sits in _start(), not _build_args().
    """
    enabled = {n: False for n in run_ocr_gui._ENGINES}
    g = _make_gui(enabled=enabled)
    args = g._build_args()
    assert "--engines" not in args


def test_build_args_throttle_minimal():
    g = _make_gui(throttle="Minimal impact (4 threads, idle priority)")
    args = g._build_args()
    assert "--throttle" in args
    idx = args.index("--throttle")
    assert args[idx + 1] == "minimal-4"


def test_build_args_throttle_background():
    g = _make_gui(throttle="Background (8 threads, below-normal priority)")
    args = g._build_args()
    assert "--throttle" in args
    idx = args.index("--throttle")
    assert args[idx + 1] == "background-8"


def test_build_args_pages_range():
    g = _make_gui(pages="1-10")
    args = g._build_args()
    assert "--pages" in args
    idx = args.index("--pages")
    assert args[idx + 1] == "1-10"


def test_build_args_surya_width_passed_when_surya_enabled():
    g = _make_gui(surya_width="2500")
    args = g._build_args()
    assert "--surya-max-width" in args
    idx = args.index("--surya-max-width")
    assert args[idx + 1] == "2500"


def test_build_args_surya_width_omitted_when_surya_disabled():
    enabled = {n: (n != "surya") for n in run_ocr_gui._ENGINES}
    g = _make_gui(enabled=enabled, surya_width="2500")
    args = g._build_args()
    assert "--surya-max-width" not in args


def test_build_args_boolean_flags():
    g = _make_gui(
        allow_partial=True,
        dry_run=True,
        doctor_first=True,
        allow_stale_manifest=True,
        resume=True,
    )
    args = g._build_args()
    assert "--allow-partial" in args
    assert "--dry-run" in args
    assert "--doctor-first" in args
    assert "--allow-stale-manifest" in args
    assert "--resume" in args


def test_build_args_path_overrides():
    g = _make_gui(s1_root="/tmp/s1", s2_root="/tmp/s2", input_root="/tmp/input")
    args = g._build_args()
    assert "--s1-root" in args
    assert "--s2-root" in args
    assert "--input-root" in args


def _make_status_gui():
    """Build a minimal headless gui for testing _parse_status."""
    g = object.__new__(run_ocr_gui.PipelineGui)
    g._status_var = _Var("Idle")
    g._detail_var = _Var("")
    g._bar = _Bar(value=0)
    return g


def test_parse_status_vol_start():
    g = _make_status_gui()
    g._parse_status("[2/13] vol_02\n")
    assert "vol 2/13" in g._status_var.get()
    assert g._bar.value == 0


def test_parse_status_progress_line():
    g = _make_status_gui()
    g._parse_status(
        "  tesseract vol_02: 50/200 emitted=48 skip=1 fail=1  "
        "120s elapsed  eta=240s\n"
    )
    assert "tesseract" in g._detail_var.get()
    assert "50/200" in g._detail_var.get()
    assert g._bar.value == pytest.approx(25.0)


def test_parse_status_vol_done():
    g = _make_status_gui()
    g._parse_status("vol_02: done in 3600.0s\n")
    assert g._bar.value == 100


def test_parse_status_pipeline_done():
    g = _make_status_gui()
    g._parse_status("OCR pipeline complete:\n")
    assert g._status_var.get() == "Complete"
    assert g._bar.value == 100


def test_parse_status_shutdown():
    g = _make_status_gui()
    g._parse_status("Shutdown requested\n")
    assert "Shutting down" in g._status_var.get()


def test_parse_status_s2_progress():
    g = _make_status_gui()
    g._parse_status("  s2 [10/20]  some-lineage:\n")
    assert "10/20" in g._detail_var.get()
    assert g._bar.value == pytest.approx(50.0)


def test_parse_status_shutdown_progress_without_elapsed():
    g = _make_status_gui()
    g._parse_status(
        "    surya-py312-v1 vol_02: 5/100 emitted=5 skip=0 fail=0 -- shutdown\n"
    )
    assert "surya-py312-v1" in g._detail_var.get()
    assert "5/100" in g._detail_var.get()
    assert g._bar.value == pytest.approx(5.0)


class _FakeProc:
    pid = 1234

    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        raise subprocess.TimeoutExpired("fake", timeout)

    def kill(self) -> None:
        self.killed = True


def test_terminate_process_tree_uses_taskkill_on_windows(monkeypatch) -> None:
    calls: list[list[str]] = []
    proc = _FakeProc()
    monkeypatch.setattr(run_ocr_gui.sys, "platform", "win32")

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(run_ocr_gui.subprocess, "run", fake_run)

    run_ocr_gui._terminate_process_tree(proc)

    assert calls == [["taskkill", "/PID", "1234", "/T", "/F"]]
    assert proc.terminated is False
    assert proc.killed is False


def test_terminate_process_tree_falls_back_to_direct_kill(monkeypatch) -> None:
    proc = _FakeProc()
    monkeypatch.setattr(run_ocr_gui.sys, "platform", "linux")

    run_ocr_gui._terminate_process_tree(proc)

    assert proc.terminated is True
    assert proc.killed is True
