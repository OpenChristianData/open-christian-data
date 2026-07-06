<#
.SYNOPSIS
  Activate this repo's tracked pre-commit hook (.githooks/pre-commit), which runs
  the repo gates -- gitleaks, parser-test, scoped pytest, schema-enum freshness,
  writer-manifest, and the NSH content-position OCR tripwire -- and then chains to
  the global identity hook (~/.git-hooks/pre-commit).

.DESCRIPTION
  Run from the repo root. The script points core.hooksPath at the tracked
  .githooks directory so the version-controlled hook is the one git executes.
  It does NOT modify the shared global identity hook (~/.git-hooks/pre-commit) --
  the tracked hook chains to it unchanged.

  NOTE: this also activates the other repo gates listed above, which the current
  active hook (.git/hooks/pre-commit, an identity-only stub) does not run. That is
  intentional -- review .githooks/pre-commit before running if you want to confirm
  what will be enforced. gitleaks must be installed (winget install gitleaks.gitleaks).

.EXAMPLE
  pwsh -File build/tools/install_nsh_precommit_hook.ps1
#>
[CmdletBinding()]
param(
    [switch]$Revert
)

$ErrorActionPreference = 'Stop'

# Resolve repo root from this script's location (two levels up from build/tools/).
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $repoRoot
try {
    $tracked = Join-Path $repoRoot '.githooks\pre-commit'
    if (-not (Test-Path $tracked)) {
        throw "Tracked hook not found at .githooks/pre-commit -- run from a full checkout."
    }

    $current = (git config --get core.hooksPath) 2>$null

    if ($Revert) {
        git config --unset core.hooksPath 2>$null | Out-Null
        Write-Host "Reverted: core.hooksPath unset (git falls back to .git/hooks)."
        return
    }

    Write-Host "Current core.hooksPath: $current"
    git config core.hooksPath '.githooks'
    Write-Host "Set core.hooksPath -> .githooks (tracked hook is now active)."
    Write-Host ""
    Write-Host "Smoke-test the NSH OCR tripwire (no commit):"
    Write-Host "  py -3 build/tools/nsh_precommit_ocr_gate.py --selftest"
    Write-Host "  py -3 build/tools/nsh_precommit_ocr_gate.py --volume 3   # control, expect OK"
    Write-Host ""
    Write-Host "To revert: pwsh -File build/tools/install_nsh_precommit_hook.ps1 -Revert"
}
finally {
    Pop-Location
}
