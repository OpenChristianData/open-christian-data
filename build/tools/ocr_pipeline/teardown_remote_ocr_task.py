"""Undo the remote-launch OCR setup: kill processes, delete task, restore sleep.

Inverse of setup_remote_ocr_task.py + harden_remote_ocr_task.py.

What this does:
  1. Kills any running run_ocr_pipeline processes (mirrors stop_ocr.py).
  2. Deletes the OCD-Remote-OCR scheduled task if it exists.
  3. Restores DC standby to 30 min (harden sets it to never; 30 min is the
     Balanced-plan default and what prior teardowns have used).
  4. Restores DC hibernate to 0 (leave as-is -- harden set this, but
     never-hibernate on DC is fine to leave).
  5. AC standby is left at 0/never -- that is the Balanced-plan default and
     setup_remote_ocr_task.py only confirms it; it does not change it.

Run from the repo root:
    py -3 build/tools/ocr_pipeline/teardown_remote_ocr_task.py
"""
from __future__ import annotations

import json
import subprocess

TASK = "OCD-Remote-OCR"
DC_STANDBY_MINUTES = 30


def _kill_ocr_processes() -> None:
    ps = (
        "Get-CimInstance Win32_Process "
        "| Where-Object { $_.CommandLine -match 'run_remote_ocr|run_ocr_pipeline|run_ocr_gui' } "
        "| Select-Object ProcessId | ConvertTo-Json -Compress"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, check=False,
    )
    out = (r.stdout or "").strip()
    if not out:
        print("No OCR processes running.")
        return
    data = json.loads(out)
    if isinstance(data, dict):
        data = [data]
    for entry in data:
        pid = str(entry["ProcessId"])
        k = subprocess.run(
            ["taskkill", "/PID", pid, "/T", "/F"],
            capture_output=True, text=True, check=False,
        )
        print(f"Killed PID {pid}: {(k.stdout or k.stderr).strip()[:90]}")


def _delete_task() -> None:
    r = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK, "/f"],
        capture_output=True, text=True, check=False,
    )
    if r.returncode == 0:
        print(f"Deleted scheduled task: {TASK}")
    else:
        msg = (r.stdout or r.stderr or "").strip()
        if "cannot find" in msg.lower() or "does not exist" in msg.lower():
            print(f"Task {TASK!r} not found -- nothing to delete.")
        else:
            print(f"schtasks /delete returned {r.returncode}: {msg}")


def _restore_sleep() -> None:
    subprocess.run(
        ["powercfg", "/change", "standby-timeout-dc", str(DC_STANDBY_MINUTES)],
        check=True,
    )
    print(f"DC standby restored to {DC_STANDBY_MINUTES} min.")


def main() -> None:
    print("=== 1. Kill OCR processes ===")
    _kill_ocr_processes()

    print("\n=== 2. Delete scheduled task ===")
    _delete_task()

    print("\n=== 3. Restore sleep settings ===")
    _restore_sleep()

    print("\nTeardown complete.")


if __name__ == "__main__":
    main()
