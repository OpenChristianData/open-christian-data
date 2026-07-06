param(
    [switch]$SkipLocalTesseractVol1,
    [switch]$SkipSuryaVol1,
    [switch]$SkipKrakenVol1,
    [switch]$SkipSuryaRest,
    [switch]$ContinueOnError
)

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

$stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$LogPath = Join-Path $RepoRoot "logs\overnight-ocr-$stamp.log"
New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RepoRoot ".tmp") | Out-Null

$env:PYTHONIOENCODING = "utf-8"
$env:OMP_NUM_THREADS = "2"
$env:MKL_NUM_THREADS = "2"
$env:OPENBLAS_NUM_THREADS = "2"
$env:TF_NUM_INTRAOP_THREADS = "2"
$env:TF_NUM_INTEROP_THREADS = "1"
$env:OPENBLAS_CORETYPE = "VORTEX"

try {
    (Get-Process -Id $PID).PriorityClass = "Idle"
} catch {
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Could not lower runner priority: $($_.Exception.Message)" |
        Tee-Object -FilePath $LogPath -Append
}

function Write-Step {
    param([string]$Message)
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message" |
        Tee-Object -FilePath $LogPath -Append
}

function Invoke-LoggedNative {
    param(
        [string]$Label,
        [string[]]$Command
    )

    Write-Step "START $Label :: $($Command -join ' ')"
    $global:Error.Clear()
    (& $Command[0] @($Command[1..($Command.Count - 1)]) 2>&1) |
        ForEach-Object { $_.ToString() } |
        Tee-Object -FilePath $LogPath -Append
    $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
    Write-Step "END $Label :: exit=$exitCode"
    if ($exitCode -ne 0 -and -not $ContinueOnError) {
        Write-Step "ABORT after failed step: $Label"
        exit $exitCode
    }
}

function Invoke-LoggedPython {
    param(
        [string]$Label,
        [string]$Code
    )

    Write-Step "START $Label"
    $safeLabel = ($Label -replace "[^A-Za-z0-9_-]", "_")
    $snippetPath = Join-Path $RepoRoot ".tmp\overnight_ocr_$PID`_$safeLabel.py"
    $repoLiteral = $RepoRoot.Replace("\", "\\").Replace("'", "\'")
    $bootstrap = @"
from pathlib import Path
import sys
REPO_ROOT = Path('$repoLiteral')
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

"@
    Set-Content -Path $snippetPath -Value ($bootstrap + $Code) -Encoding UTF8
    $global:Error.Clear()
    (& py -3 $snippetPath 2>&1) |
        ForEach-Object { $_.ToString() } |
        Tee-Object -FilePath $LogPath -Append
    $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE }
    Write-Step "END $Label :: exit=$exitCode"
    if ($exitCode -ne 0 -and -not $ContinueOnError) {
        Write-Step "ABORT after failed step: $Label"
        exit $exitCode
    }
}

Write-Step "Overnight OCR queue booted. Log: $LogPath"
Write-Step "Thread caps: OMP/MKL/OpenBLAS/TF intra=2, TF inter=1. Parent priority: Idle."

if (-not $SkipLocalTesseractVol1) {
    Invoke-LoggedNative `
        -Label "vol_01 local Tesseract hOCR force run" `
        -Command @("py", "-3", "build/parsers/local_schaff_tesseract.py", "--volume", "1", "--force")
}

if (-not $SkipSuryaVol1) {
    $suryaVol1 = @'
from build.parsers.s1_surya_runner import normalize_volume
summary = normalize_volume(volume=1, throttle_mode="overnight")
print(f"surya vol_01 emitted={summary.emitted_pages} skipped={summary.skipped_pages} failed={summary.failed_pages} manifest={summary.manifest_path}")
'@
    Invoke-LoggedPython -Label "vol_01 S1 Surya sidecars" -Code $suryaVol1
}

if (-not $SkipKrakenVol1) {
    $krakenVol1 = @'
from build.parsers.s1_kraken_runner import normalize_volume
summary = normalize_volume(volume=1, throttle_mode="overnight")
print(f"kraken vol_01 emitted={summary.emitted_pages} skipped={summary.skipped_pages} failed={summary.failed_pages} manifest={summary.manifest_path}")
'@
    Invoke-LoggedPython -Label "vol_01 S1 Kraken sidecars" -Code $krakenVol1
}

if (-not $SkipSuryaRest) {
    foreach ($vol in 2..13) {
        $volLabel = "vol_{0:00}" -f $vol
        $suryaRest = @"
from build.parsers.s1_surya_runner import normalize_volume
summary = normalize_volume(volume=$vol, throttle_mode="overnight")
print("surya $volLabel emitted={} skipped={} failed={} manifest={}".format(
    summary.emitted_pages,
    summary.skipped_pages,
    summary.failed_pages,
    summary.manifest_path,
))
"@
        Invoke-LoggedPython -Label ("Surya resume vol_{0:00}" -f $vol) -Code $suryaRest
    }
}

Write-Step "Overnight OCR queue finished."
