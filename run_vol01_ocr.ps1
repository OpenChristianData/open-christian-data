# Run as much vol_01 OCR as possible, overnight, resumable.
# S1 + S2 + coverage for all engines (live: surya/tesseract/kraken/kraken-greek;
# imported: abbyy). NO --force-s1 -> pages already done are skipped, so you can
# re-run this every night and it resumes where it left off (Surya is the long pole).
#
# Usage:  pwsh -File run_vol01_ocr.ps1
# Stop:   Ctrl+C is safe -- per-page state is checkpointed; next run resumes.

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot
New-Item -ItemType Directory -Force -Path "$RepoRoot\logs" | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$log = "$RepoRoot\logs\vol01-ocr-$stamp.log"

"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] vol_01 full OCR start -> $log" | Tee-Object -FilePath $log

# --throttle overnight = idle CPU priority + reduced threads (gentle, unattended).
# --surya-max-width 2500 = ~3.6x Surya speedup on the 5034px scans, no measurable quality loss.
py -3 build\tools\ocr_pipeline\run_ocr_pipeline.py --volumes 1 --throttle overnight --surya-max-width 2500 *>&1 |
    Tee-Object -FilePath $log -Append

"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] vol_01 full OCR end (exit $LASTEXITCODE)" | Tee-Object -FilePath $log -Append
