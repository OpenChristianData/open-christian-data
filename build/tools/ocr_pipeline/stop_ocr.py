"""Find and kill any running run_ocr_pipeline processes (orphan cleanup)."""
import json
import subprocess

ps = (
    "Get-CimInstance Win32_Process "
    "| Where-Object { $_.CommandLine -match 'run_remote_ocr|run_ocr_pipeline|run_ocr_gui' } "
    "| Select-Object ProcessId | ConvertTo-Json -Compress"
)
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, text=True)
out = (r.stdout or "").strip()
pids = []
if out:
    d = json.loads(out)
    if isinstance(d, dict):
        d = [d]
    pids = [str(x["ProcessId"]) for x in d]

if not pids:
    print("No run_ocr_pipeline processes running.")
for pid in pids:
    k = subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                       capture_output=True, text=True)
    print(f"PID {pid}: {(k.stdout or k.stderr).strip()[:90]}")
