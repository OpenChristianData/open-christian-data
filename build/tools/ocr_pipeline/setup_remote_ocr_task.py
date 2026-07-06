"""Set up the unattended (remote-launch) NSH OCR run as a Windows Scheduled Task.

Use this to launch the OCR run when it must survive the launching session
ending and run with no one at the console -- e.g. kicked off remotely. Running
the pipeline interactively from a terminal needs none of this scaffolding;
this exists purely so an unattended run keeps going.

What this does (all via Windows APIs called directly, no shell mangling):
  1. Disables AC sleep + hibernate so the machine cannot sleep mid-run.
  2. Writes run_remote_ocr.cmd at the repo root with a timestamped log path.
  3. Registers a Windows Scheduled Task for that wrapper and starts it NOW.

The Scheduled Task runs under the Task Scheduler service, independent of the
launching session -- it survives that session/terminal closing. Sleep is
prevented by the powercfg change here PLUS the orchestrator's own
SetThreadExecutionState lock while it runs.

Throttle is full-speed (no CPU cap): an unattended run has the machine to
itself, so there is no reason to throttle the CPU engines.

Run from the repo root:
    py -3 build/tools/ocr_pipeline/setup_remote_ocr_task.py
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WRAPPER = REPO / "run_remote_ocr.cmd"
_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
LOG = REPO / "logs" / f"remote-ocr-{_stamp}.log"
TASK = "OCD-Remote-OCR"


def main() -> None:
    # 1. Prevent sleep on AC (reversible; original value printed for restore).
    print("=== current AC standby timeout (minutes; note for restore) ===", flush=True)
    subprocess.run(
        ["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"],
        check=False,
    )
    for setting in ("standby-timeout-ac", "hibernate-timeout-ac"):
        subprocess.run(["powercfg", "/change", setting, "0"], check=True)
    print("AC sleep + hibernate disabled (set to never).", flush=True)

    # 2. Write the .cmd wrapper (pure cmd -- no PowerShell).
    # The log dir must exist before the wrapper runs: cmd's `>> logs\...`
    # redirection does NOT create parent dirs, so on a clean checkout (no logs/)
    # the wrapper would fail before Python starts. Create it now, at setup time.
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # All three engines run inside ONE run_ocr_pipeline.py invocation (it runs
    # engines sequentially itself). A single process -- not a cmd for-loop over
    # three -- means that if the wrapper cmd is ever orphaned/killed, the lone
    # Python process still finishes all three engines; the chain cannot break
    # mid-way. run_ocr_pipeline.py itself catches a per-engine failure and
    # continues to the next engine; --allow-partial only forces exit 0 despite
    # such failures (so an unattended run isn't flagged as failed mid-corpus).
    wrapper = (
        "@echo off\r\n"
        f'cd /d "{REPO}"\r\n'
        f'echo === REMOTE OCR START %DATE% %TIME% === >> "{LOG}"\r\n'
        "py -3 build\\tools\\ocr_pipeline\\run_ocr_pipeline.py "
        "--engines abbyy tesseract kraken "
        f'--throttle full-speed --allow-partial >> "{LOG}" 2>&1\r\n'
        f'echo === REMOTE OCR COMPLETE (exit %ERRORLEVEL%) %DATE% %TIME% === >> "{LOG}"\r\n'
    )
    WRAPPER.write_text(wrapper, encoding="ascii")
    print(f"wrapper written: {WRAPPER}", flush=True)

    # 3. Register + start the task, independent of the launching session.
    subprocess.run(
        ["schtasks", "/delete", "/tn", TASK, "/f"],
        check=False, capture_output=True,
    )
    subprocess.run(
        [
            "schtasks", "/create", "/tn", TASK,
            "/tr", f'cmd /c "{WRAPPER}"',
            "/sc", "ONCE", "/st", "23:59",
            "/rl", "LIMITED", "/f",
        ],
        check=True,
    )
    subprocess.run(["schtasks", "/run", "/tn", TASK], check=True)
    print("=== task status ===", flush=True)
    subprocess.run(
        ["schtasks", "/query", "/tn", TASK, "/v", "/fo", "LIST"],
        check=False,
    )
    print(f"\nLog file: {LOG}", flush=True)


if __name__ == "__main__":
    main()
