# Shared helpers for the PowerShell equivalents of the Makefile targets.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Step {
    param([string]$Dir, [string]$Exe, [string[]]$ArgList)
    Push-Location (Join-Path $RepoRoot $Dir)
    try {
        & $Exe @ArgList
        if ($LASTEXITCODE -ne 0) { throw "$Exe $($ArgList -join ' ') failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}
