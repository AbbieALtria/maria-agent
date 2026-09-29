# make test — needs Postgres reachable via DATABASE_URL (tests create/drop "<db>_test").
. "$PSScriptRoot\_common.ps1"
Invoke-Step "." "uv" @("run", "pytest")
Invoke-Step "apps\web" "npm" @("test")
