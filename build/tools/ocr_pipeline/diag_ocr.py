"""Snapshot all OCR-related processes (cmd wrapper, pipeline, GUI) with parents."""
import json
import subprocess

ps = (
    "Get-CimInstance Win32_Process "
    "| Where-Object { $_.CommandLine -match 'run_remote_ocr|run_ocr_pipeline|run_ocr_gui' } "
    "| Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
)
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, text=True)
out = (r.stdout or "").strip()
data = json.loads(out) if out else []
if isinstance(data, dict):
    data = [data]
print(f"{len(data)} process(es):")
for p in data:
    cl = (p.get("CommandLine") or "")[:110]
    print(f"  PID {p['ProcessId']:>6}  parent {p['ParentProcessId']:>6}  {p['Name']}")
    print(f"        {cl}")
