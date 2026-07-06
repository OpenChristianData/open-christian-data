"""Make the remote-launch OCR task battery-proof.

The first registration (schtasks /create) defaults to Stop-On-Battery +
No-Start-On-Battery. This re-registers the task from XML with battery guards
OFF, no time limit, and DC sleep disabled -- so an unattended run survives on
battery.

Run after setup_remote_ocr_task.py if the machine is a laptop and you want
the task to continue if unplugged.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WRAPPER = REPO / "run_remote_ocr.cmd"
TASK = "OCD-Remote-OCR"
USER = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"

XML = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>NSH OCR unattended run: ABBYY -&gt; Tesseract -&gt; Kraken, vols 1-13</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>2026-06-21T23:59:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{USER}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <AllowHardTerminate>true</AllowHardTerminate>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd</Command>
      <Arguments>/c "{WRAPPER}"</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _kill_orphan_ocr() -> None:
    """Kill any lingering OCR process tree before re-registering.

    `schtasks /end` stops the registered task instance but does NOT reliably kill
    the descendant `py`/`python` workers the wrapper spawned -- under Task Scheduler
    the wrapper cmd exits early and orphans them. Without this, harden's own
    `/run` below starts a SECOND OCR run alongside the orphan, and two processes
    writing the same sidecars race. Mirror stop_ocr.py's process-tree kill.
    """
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
        return
    data = json.loads(out)
    if isinstance(data, dict):
        data = [data]
    for entry in data:
        pid = str(entry["ProcessId"])
        # /T kills the whole tree, /F forces it. The CIM-query powershell self-
        # matches but has already exited by now, so its kill is a harmless no-op.
        subprocess.run(
            ["taskkill", "/PID", pid, "/T", "/F"],
            capture_output=True, text=True, check=False,
        )
        print(f"killed lingering OCR process tree {pid}", flush=True)


def main() -> None:
    for setting in ("standby-timeout-dc", "hibernate-timeout-dc"):
        subprocess.run(["powercfg", "/change", setting, "0"], check=True)
    print("DC sleep + hibernate disabled (set to never).", flush=True)

    subprocess.run(["schtasks", "/end", "/tn", TASK], check=False, capture_output=True)
    subprocess.run(["schtasks", "/delete", "/tn", TASK, "/f"], check=False, capture_output=True)
    # Kill any orphaned workers the prior run left behind BEFORE /run starts a new
    # one -- otherwise two OCR processes write the same sidecars concurrently.
    _kill_orphan_ocr()

    xml_path = Path(tempfile.gettempdir()) / "remote_ocr_task.xml"
    xml_path.write_text(XML, encoding="utf-16")
    subprocess.run(
        ["schtasks", "/create", "/tn", TASK, "/xml", str(xml_path), "/f"],
        check=True,
    )
    subprocess.run(["schtasks", "/run", "/tn", TASK], check=True)

    print("=== task power/battery settings now ===", flush=True)
    out = subprocess.run(
        ["schtasks", "/query", "/tn", TASK, "/v", "/fo", "LIST"],
        check=False, capture_output=True, text=True,
    ).stdout
    for line in out.splitlines():
        if any(k in line for k in ("Status:", "Power Management", "Stop Task If", "Run As User", "Logon Mode")):
            print(line.rstrip(), flush=True)


if __name__ == "__main__":
    main()
