# make lint
. "$PSScriptRoot\_common.ps1"
Invoke-Step "." "uv" @("run", "ruff", "check", ".")
Invoke-Step "." "uv" @("run", "ruff", "format", "--check", ".")
Invoke-Step "apps\web" "npm" @("run", "lint")
