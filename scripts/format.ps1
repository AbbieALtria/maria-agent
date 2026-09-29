# make format
. "$PSScriptRoot\_common.ps1"
Invoke-Step "." "uv" @("run", "ruff", "check", "--fix", ".")
Invoke-Step "." "uv" @("run", "ruff", "format", ".")
