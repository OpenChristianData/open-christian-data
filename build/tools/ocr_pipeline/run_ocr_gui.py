"""OCR pipeline GUI launcher.

Provides a window to configure, start, and stop the OCR pipeline without
keeping a terminal open. All CLI options exposed by run_ocr_pipeline.py are
available as form controls.

Stop triggers a graceful shutdown: the pipeline finishes its current page
(~10-45s) and saves state before exiting. Force Stop terminates immediately;
completed pages are safe, but the in-progress page is retried next run.

Usage:
    py -3 build/tools/ocr_pipeline/run_ocr_gui.py
"""

from __future__ import annotations

import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import scrolledtext, ttk

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PIPELINE_SCRIPT = _REPO_ROOT / "build" / "tools" / "ocr_pipeline" / "run_ocr_pipeline.py"
_STOP_SENTINEL = _REPO_ROOT / "reports" / ".pipeline_stop_requested"

# Engine names in default pipeline order.
_ENGINES = ["tesseract", "surya", "kraken", "kraken-greek", "abbyy"]

# Throttle options: (display label, CLI flag value).
_THROTTLE_OPTIONS = [
    ("Full speed", "full-speed"),
    ("Background (8 threads, below-normal priority)", "background-8"),
    ("Minimal impact (4 threads, idle priority)", "minimal-4"),
]
_THROTTLE_LABELS = [label for label, _ in _THROTTLE_OPTIONS]
_THROTTLE_LABEL_TO_VAL = {label: val for label, val in _THROTTLE_OPTIONS}

# Patterns for parsing log output into status fields.
_VOL_START_PAT = re.compile(r"^\[(\d+)/(\d+)\] (vol_\d+)")
_PROGRESS_PAT = re.compile(
    r"^\s+(\S+) vol_\d+: (\d+)/(\d+)"
    r" emitted=(\d+) skip=(\d+) fail=(\d+)"
    r"\s+(\d+)s elapsed"
    r"(?:\s+eta=(\d+)s)?"
)
_PROGRESS_SHUTDOWN_PAT = re.compile(
    r"^\s+(\S+) vol_\d+: (\d+)/(\d+)"
    r" emitted=(\d+) skip=(\d+) fail=(\d+)"
    r"(?:\s+-- shutdown)?$"
)
_VOL_DONE_PAT = re.compile(r"(vol_\w+): done in ([\d.]+)s")
_PIPELINE_DONE_PAT = re.compile(r"OCR pipeline complete:")
_SHUTDOWN_PAT = re.compile(r"[Ss]hutdown requested")
_S2_PROGRESS_PAT = re.compile(r"^\s*s2 \[(\d+)/(\d+)\]\s+(\S+)")


def _terminate_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """Terminate the OCR runner and any child worker processes."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return
        except (OSError, subprocess.CalledProcessError):
            # taskkill exits non-zero when the process is already dead — treat the same as OSError
            pass
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass


def _fmt_seconds(s: int) -> str:
    if s >= 3600:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    return f"{s // 60}m{s % 60:02d}s"


class PipelineGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("OCR Pipeline")
        self.root.minsize(700, 600)

        self._proc: subprocess.Popen[bytes] | None = None
        self._queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._stopping = False
        self._running = False

        self._build_ui()
        self._poll()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        mono = tkfont.Font(family="Courier", size=9)

        # ---- Status panel ----
        status_frame = ttk.LabelFrame(self.root, text="Status", padding=8)
        status_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        self._status_var = tk.StringVar(value="Idle")
        ttk.Label(
            status_frame, textvariable=self._status_var, font=("", 10, "bold")
        ).pack(anchor=tk.W)

        self._detail_var = tk.StringVar(value="")
        ttk.Label(status_frame, textvariable=self._detail_var).pack(anchor=tk.W)

        self._bar = ttk.Progressbar(status_frame, maximum=100, mode="determinate")
        self._bar.pack(fill=tk.X, pady=(4, 0))

        # ---- Log ----
        log_frame = ttk.LabelFrame(self.root, text="Log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._log_widget = scrolledtext.ScrolledText(
            log_frame, height=14, font=mono, state=tk.DISABLED, wrap=tk.NONE,
        )
        self._log_widget.pack(fill=tk.BOTH, expand=True)

        # ---- Settings ----
        settings_frame = ttk.LabelFrame(self.root, text="Settings", padding=(8, 4))
        settings_frame.pack(fill=tk.X, padx=8, pady=4)

        self._build_settings(settings_frame)

        # ---- Buttons ----
        btn_frame = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        btn_frame.pack(fill=tk.X)

        self._start_btn = ttk.Button(
            btn_frame, text="Start", command=self._start, width=14
        )
        self._start_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._stop_btn = ttk.Button(
            btn_frame, text="Stop", command=self._stop, width=14, state=tk.DISABLED
        )
        self._stop_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._force_btn = ttk.Button(
            btn_frame, text="Force Stop", command=self._force_stop, width=14,
            state=tk.DISABLED,
        )
        self._force_btn.pack(side=tk.LEFT)

    def _build_settings(self, parent: ttk.LabelFrame) -> None:
        g = parent  # grid parent

        # --- Row 0: Volumes ---
        ttk.Label(g, text="Volumes:").grid(row=0, column=0, sticky=tk.W, pady=2)

        vol_frame = ttk.Frame(g)
        vol_frame.grid(row=0, column=1, columnspan=3, sticky=tk.W, pady=2)

        self._vol_vars: list[tk.BooleanVar] = []
        for i in range(1, 14):
            var = tk.BooleanVar(value=True)
            self._vol_vars.append(var)
            cb = ttk.Checkbutton(vol_frame, text=str(i), variable=var)
            cb.pack(side=tk.LEFT, padx=1)

        ttk.Button(
            vol_frame, text="All", command=self._vols_all, width=5,
        ).pack(side=tk.LEFT, padx=(6, 2))
        ttk.Button(
            vol_frame, text="None", command=self._vols_none, width=5,
        ).pack(side=tk.LEFT)

        # --- Row 1: Engines ---
        ttk.Label(g, text="Engines:").grid(row=1, column=0, sticky=tk.W, pady=2)

        eng_frame = ttk.Frame(g)
        eng_frame.grid(row=1, column=1, columnspan=3, sticky=tk.W, pady=2)

        self._engine_order: list[str] = list(_ENGINES)
        self._engine_enabled: dict[str, tk.BooleanVar] = {
            name: tk.BooleanVar(value=True)
            for name in _ENGINES
        }

        self._eng_listbox = tk.Listbox(
            eng_frame, height=len(_ENGINES), width=20, selectmode=tk.SINGLE,
        )
        self._eng_listbox.pack(side=tk.LEFT)
        self._eng_listbox.bind("<Button-1>", self._engine_list_click)
        self._rebuild_engine_list()

        move_frame = ttk.Frame(eng_frame)
        move_frame.pack(side=tk.LEFT, padx=(4, 8), anchor=tk.N)
        ttk.Button(move_frame, text="Up", command=self._engine_move_up, width=4).pack()
        ttk.Button(move_frame, text="Down", command=self._engine_move_down, width=6).pack(pady=(2, 0))

        ttk.Button(
            eng_frame, text="All", command=self._engines_all, width=5,
        ).pack(side=tk.LEFT, padx=(0, 2), anchor=tk.N)
        ttk.Button(
            eng_frame, text="None", command=self._engines_none, width=5,
        ).pack(side=tk.LEFT, anchor=tk.N)
        ttk.Button(
            eng_frame, text="Geometry", command=self._engines_geometry, width=10,
        ).pack(side=tk.LEFT, padx=(4, 0), anchor=tk.N)

        # --- Row 2: Throttle ---
        ttk.Label(g, text="Throttle:").grid(row=2, column=0, sticky=tk.W, pady=2)

        thr_frame = ttk.Frame(g)
        thr_frame.grid(row=2, column=1, sticky=tk.W, pady=2)

        self._throttle_var = tk.StringVar(value=_THROTTLE_LABELS[0])
        self._throttle_combo = ttk.Combobox(
            thr_frame, textvariable=self._throttle_var,
            values=_THROTTLE_LABELS, state="readonly", width=46,
        )
        self._throttle_combo.pack(side=tk.LEFT)

        # --- Row 3: Pages + Surya max-width ---
        ttk.Label(g, text="Pages:").grid(row=3, column=0, sticky=tk.W, pady=2)

        self._pages_var = tk.StringVar()
        pages_entry = ttk.Entry(g, textvariable=self._pages_var, width=20)
        pages_entry.grid(row=3, column=1, sticky=tk.W, pady=2)
        ttk.Label(g, text="  e.g. 1-10 or 1 2 3 (optional)").grid(
            row=3, column=2, sticky=tk.W
        )

        ttk.Label(g, text="Surya max-width:").grid(row=3, column=3, sticky=tk.W, padx=(12, 0))

        self._surya_width_var = tk.StringVar(value="2500")
        ttk.Entry(g, textvariable=self._surya_width_var, width=6).grid(
            row=3, column=4, sticky=tk.W
        )
        ttk.Label(
            g,
            text="px  (GUI default: ~2x faster on NSH scans; clear = full resolution)",
        ).grid(row=3, column=5, sticky=tk.W, padx=(2, 0))

        # --- Row 4: Flags (line 1) ---
        flag_frame = ttk.Frame(g)
        flag_frame.grid(row=4, column=0, columnspan=6, sticky=tk.W, pady=(2, 0))

        self._allow_partial_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            flag_frame, text="Allow partial failures (exit 0 on engine errors)",
            variable=self._allow_partial_var,
        ).pack(side=tk.LEFT, padx=(0, 16))

        self._dry_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            flag_frame, text="Dry run (preflight check only, no OCR)",
            variable=self._dry_run_var,
        ).pack(side=tk.LEFT, padx=(0, 16))

        self._doctor_first_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            flag_frame, text="Doctor first (abort on stale sidecars)",
            variable=self._doctor_first_var,
        ).pack(side=tk.LEFT)

        # --- Row 5: Flags (line 2) ---
        flag_frame2 = ttk.Frame(g)
        flag_frame2.grid(row=5, column=0, columnspan=6, sticky=tk.W, pady=(0, 2))

        self._allow_stale_manifest_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            flag_frame2, text="Allow stale manifest (S2 when sidecar count > manifest)",
            variable=self._allow_stale_manifest_var,
        ).pack(side=tk.LEFT, padx=(0, 16))

        self._resume_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            flag_frame2, text="Resume (clear stale stop markers + doctor-first)",
            variable=self._resume_var,
        ).pack(side=tk.LEFT)

        # --- Row 6: Advanced path overrides (collapsed by default) ---
        self._advanced_visible = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            g, text="Show path overrides", variable=self._advanced_visible,
            command=self._toggle_advanced,
        ).grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

        self._adv_frame = ttk.Frame(g)
        # Not packed until toggle

        for row_idx, (label, attr) in enumerate([
            ("Input root:", "_input_root_var"),
            ("S1 root:", "_s1_root_var"),
            ("S2 root:", "_s2_root_var"),
        ]):
            setattr(self, attr, tk.StringVar())
            ttk.Label(self._adv_frame, text=label).grid(
                row=row_idx, column=0, sticky=tk.W, pady=1
            )
            ttk.Entry(
                self._adv_frame, textvariable=getattr(self, attr), width=55
            ).grid(row=row_idx, column=1, sticky=tk.EW, padx=(4, 0), pady=1)

        self._adv_frame.columnconfigure(1, weight=1)
        g.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def _vols_all(self) -> None:
        for v in self._vol_vars:
            v.set(True)

    def _vols_none(self) -> None:
        for v in self._vol_vars:
            v.set(False)

    def _engines_all(self) -> None:
        for v in self._engine_enabled.values():
            v.set(True)
        self._rebuild_engine_list()

    def _engines_none(self) -> None:
        for v in self._engine_enabled.values():
            v.set(False)
        self._rebuild_engine_list()

    def _engines_geometry(self) -> None:
        """Enable the WCT geometry preset: surya + tesseract + abbyy only."""
        geometry_set = {"surya", "tesseract", "abbyy"}
        for name, var in self._engine_enabled.items():
            var.set(name in geometry_set)
        self._rebuild_engine_list()

    def _rebuild_engine_list(self) -> None:
        sel = self._eng_listbox.curselection()
        self._eng_listbox.delete(0, tk.END)
        for name in self._engine_order:
            prefix = "[x]" if self._engine_enabled[name].get() else "[ ]"
            self._eng_listbox.insert(tk.END, f"{prefix} {name}")
        if sel:
            self._eng_listbox.selection_set(sel[0])

    def _engine_list_click(self, event: tk.Event) -> None:
        if self._running:
            return
        idx = self._eng_listbox.nearest(event.y)
        if 0 <= idx < len(self._engine_order):
            name = self._engine_order[idx]
            self._engine_enabled[name].set(not self._engine_enabled[name].get())
            self._rebuild_engine_list()
            self._eng_listbox.selection_set(idx)

    def _engine_move_up(self) -> None:
        sel = self._eng_listbox.curselection()
        if not sel or sel[0] == 0:
            return
        idx = sel[0]
        self._engine_order[idx - 1], self._engine_order[idx] = (
            self._engine_order[idx], self._engine_order[idx - 1]
        )
        self._rebuild_engine_list()
        self._eng_listbox.selection_set(idx - 1)

    def _engine_move_down(self) -> None:
        sel = self._eng_listbox.curselection()
        if not sel or sel[0] >= len(self._engine_order) - 1:
            return
        idx = sel[0]
        self._engine_order[idx], self._engine_order[idx + 1] = (
            self._engine_order[idx + 1], self._engine_order[idx]
        )
        self._rebuild_engine_list()
        self._eng_listbox.selection_set(idx + 1)

    def _toggle_advanced(self) -> None:
        if self._advanced_visible.get():
            self._adv_frame.grid(row=7, column=0, columnspan=6, sticky=tk.EW, pady=(2, 0))
        else:
            self._adv_frame.grid_remove()

    def _build_args(self) -> list[str]:
        """Translate current settings widget state into CLI args."""
        args: list[str] = []

        # Volumes: omit flag when all 13 are selected (pipeline default).
        selected_vols = [str(i) for i, var in enumerate(self._vol_vars, 1) if var.get()]
        if not selected_vols:
            # Nothing selected — still need to pass something; use vol 1 as fallback.
            selected_vols = ["1"]
        if len(selected_vols) < 13:
            args += ["--volumes"] + selected_vols

        # Engines: pass --engines whenever selection or order differs from pipeline default.
        selected_engines = [n for n in self._engine_order if self._engine_enabled[n].get()]
        if selected_engines and selected_engines != list(_ENGINES):
            args += ["--engines"] + selected_engines

        # Throttle: omit when "full-speed" (pipeline default == no override).
        throttle = _THROTTLE_LABEL_TO_VAL.get(self._throttle_var.get(), "full-speed")
        if throttle != "full-speed":
            args += ["--throttle", throttle]

        # Pages subset.
        pages = self._pages_var.get().strip()
        if pages:
            args += ["--pages"] + pages.split()

        # Surya max-width — only relevant when surya is running.
        max_width = self._surya_width_var.get().strip()
        surya_running = self._engine_enabled["surya"].get() or not selected_engines
        if max_width and surya_running:
            args += ["--surya-max-width", max_width]

        # Boolean flags.
        if self._allow_partial_var.get():
            args.append("--allow-partial")
        if self._dry_run_var.get():
            args.append("--dry-run")
        if self._doctor_first_var.get():
            args.append("--doctor-first")
        if self._allow_stale_manifest_var.get():
            args.append("--allow-stale-manifest")
        if self._resume_var.get():
            args.append("--resume")

        # Path overrides (only when non-empty).
        for flag, attr in [
            ("--input-root", "_input_root_var"),
            ("--s1-root", "_s1_root_var"),
            ("--s2-root", "_s2_root_var"),
        ]:
            val = getattr(self, attr).get().strip()
            if val:
                args += [flag, val]

        return args

    def _lock_settings(self, locked: bool) -> None:
        """Disable/enable all settings widgets while a run is active."""
        state = tk.DISABLED if locked else tk.NORMAL
        for widget in self._settings_widgets():
            try:
                widget.config(state=state)
            except tk.TclError:
                pass
        if not locked:
            self._throttle_combo.config(state="readonly")

    def _settings_widgets(self):
        """Yield every interactive widget in the settings panel."""
        # Volume checkboxes and All/None buttons are inside vol_frame; collect by
        # walking the widget tree of the settings LabelFrame.
        def _walk(w):
            yield w
            for child in w.winfo_children():
                yield from _walk(child)

        settings = self.root.winfo_children()
        for top in settings:
            if isinstance(top, ttk.LabelFrame) and top.cget("text") == "Settings":
                yield from _walk(top)
                return

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------

    def _start(self) -> None:
        if self._running:
            return

        selected_engines = [
            n for n in self._engine_order if self._engine_enabled[n].get()
        ]
        if not selected_engines:
            self._status_var.set("Error: select at least one engine")
            self._detail_var.set(
                "No engines selected — pipeline would silently run all engines."
            )
            return

        pages_raw = self._pages_var.get().strip()
        if pages_raw:
            try:
                from build.tools.ocr_pipeline.run_ocr_pipeline import _parse_pages_arg

                _parse_pages_arg(pages_raw.split())
            except ValueError as exc:
                self._status_var.set("Error: invalid Pages input")
                self._detail_var.set(str(exc))
                return

        width_raw = self._surya_width_var.get().strip()
        if width_raw:
            try:
                w = int(width_raw)
                if w <= 0:
                    raise ValueError("must be a positive integer")
            except ValueError:
                self._status_var.set("Error: invalid Surya max-width")
                self._detail_var.set(
                    f"Expected a positive integer, got: {width_raw!r}"
                )
                return

        args = self._build_args()
        cmd = [sys.executable, str(_PIPELINE_SCRIPT)] + args

        _STOP_SENTINEL.unlink(missing_ok=True)  # standards: log/temp rotation -- stop sentinel is a one-shot signal file
        self._stopping = False
        self._running = True
        self._bar["value"] = 0
        self._status_var.set("Starting...")
        self._detail_var.set(" ".join(args) if args else "(all volumes, all engines)")
        self._lock_settings(True)

        self._start_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.NORMAL)
        self._force_btn.config(state=tk.NORMAL)

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(_REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            self._running = False
            self._status_var.set("Failed to start")
            self._detail_var.set(str(exc))
            self._lock_settings(False)
            self._start_btn.config(state=tk.NORMAL)
            self._stop_btn.config(state=tk.DISABLED)
            self._force_btn.config(state=tk.DISABLED)
            return
        threading.Thread(target=self._read_output, daemon=True).start()

    def _stop(self) -> None:
        if not self._running or self._stopping:
            return
        _STOP_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
        _STOP_SENTINEL.touch()
        self._stopping = True
        self._stop_btn.config(state=tk.DISABLED)
        self._status_var.set("Stopping (finishing current page)...")

    def _force_stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            _terminate_process_tree(self._proc)
        _STOP_SENTINEL.unlink(missing_ok=True)  # standards: log/temp rotation -- stop sentinel is a one-shot signal file
        self._on_stopped(forced=True)

    def _on_stopped(
        self,
        return_code: int | None = None,
        *,
        forced: bool = False,
    ) -> None:
        # Idempotency guard: _on_stopped can be reached twice for one stop --
        # once from _force_stop (button callback) and once from _poll when it
        # dequeues the background thread's "done" message. Both run on the Tk
        # main thread, so _force_stop completes (clearing _proc) before _poll
        # can fire; this guard then absorbs the second call.
        already_stopped = not self._running and self._proc is None
        if already_stopped:
            return
        was_stopping = self._stopping
        self._running = False
        self._stopping = False
        if forced:
            self._status_var.set("Stopped")
            self._detail_var.set("Force stopped")
        elif return_code is not None and return_code != 0:
            self._status_var.set("Failed")
            self._detail_var.set(f"Process exited with code {return_code}")
        elif was_stopping:
            self._status_var.set("Stopped")
            self._detail_var.set("Gracefully stopped")
        elif self._status_var.get() != "Complete":
            self._status_var.set("Idle")
            self._detail_var.set("")
        self._lock_settings(False)
        self._start_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)
        self._force_btn.config(state=tk.DISABLED)
        self._proc = None

    # ------------------------------------------------------------------
    # Output reading (background thread)
    # ------------------------------------------------------------------

    def _read_output(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line_bytes in proc.stdout:
            text = line_bytes.decode("utf-8", errors="replace")
            self._queue.put(("log", text))
        return_code = proc.wait()
        self._queue.put(("done", str(return_code)))

    # ------------------------------------------------------------------
    # UI update loop (main thread, every 200ms)
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        try:
            while True:
                kind, data = self._queue.get_nowait()
                if kind == "log":
                    self._append_log(data)
                    self._parse_status(data)
                elif kind == "done":
                    self._on_stopped(int(data))
        except queue.Empty:
            pass
        self.root.after(200, self._poll)

    def _append_log(self, text: str) -> None:
        self._log_widget.config(state=tk.NORMAL)
        self._log_widget.insert(tk.END, text)
        line_count = int(self._log_widget.index("end-1c").split(".")[0])
        if line_count > 600:
            self._log_widget.delete("1.0", f"{line_count - 600}.0")
        self._log_widget.see(tk.END)
        self._log_widget.config(state=tk.DISABLED)

    def _parse_status(self, text: str) -> None:
        for line in text.splitlines():
            m = _VOL_START_PAT.match(line)
            if m:
                self._status_var.set(f"Running -- vol {m.group(1)}/{m.group(2)}")
                self._bar["value"] = 0
                self._detail_var.set("")
                continue

            m = _PROGRESS_PAT.match(line)
            if m:
                engine = m.group(1)
                page = int(m.group(2))
                total = int(m.group(3))
                emitted = int(m.group(4))
                fail = int(m.group(6))
                elapsed = int(m.group(7))
                eta = int(m.group(8)) if m.group(8) else None
                pct = page / total * 100 if total else 0
                self._bar["value"] = pct
                eta_str = f"  ETA {_fmt_seconds(eta)}" if eta else ""
                self._detail_var.set(
                    f"{engine}  |  page {page}/{total}  |  "
                    f"emitted={emitted} fail={fail}  |  "
                    f"{_fmt_seconds(elapsed)}{eta_str}"
                )
                continue

            m = _PROGRESS_SHUTDOWN_PAT.match(line)
            if m:
                engine = m.group(1)
                page = int(m.group(2))
                total = int(m.group(3))
                emitted = int(m.group(4))
                fail = int(m.group(6))
                pct = page / total * 100 if total else 0
                self._bar["value"] = pct
                self._detail_var.set(
                    f"{engine}  |  page {page}/{total}  |  "
                    f"emitted={emitted} fail={fail}"
                )
                continue

            m = _S2_PROGRESS_PAT.match(line)
            if m:
                cur = int(m.group(1))
                total = int(m.group(2))
                lineage = m.group(3).rstrip(":")
                pct = cur / total * 100 if total else 0
                self._bar["value"] = pct
                self._detail_var.set(f"S2  |  {cur}/{total}  |  {lineage}")
                continue

            m = _VOL_DONE_PAT.search(line)
            if m:
                self._bar["value"] = 100
                self._detail_var.set(
                    f"{m.group(1)} done in {_fmt_seconds(int(float(m.group(2))))}"
                )
                continue

            if _PIPELINE_DONE_PAT.search(line):
                self._status_var.set("Complete")
                self._bar["value"] = 100
                continue

            if _SHUTDOWN_PAT.search(line):
                self._status_var.set("Shutting down...")
                continue


def main() -> None:
    root = tk.Tk()
    root.geometry("1100x700")
    PipelineGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
