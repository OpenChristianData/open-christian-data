# Scheduled provenance gate for the publish pipeline. Runs the verifier and
# fails the task (nonzero exit) on any provenance drift so the schedule alerts.
param(
    [Parameter(Mandatory = $true)][string]$ReleaseRoot,
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
)
$ErrorActionPreference = "Stop"
$tool = Join-Path $RepoRoot "build/tools/verify_publish_provenance.py"
& py -3 $tool --release-root $ReleaseRoot
exit $LASTEXITCODE
