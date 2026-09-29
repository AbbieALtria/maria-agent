# make db-up  (skip if you use a local Postgres or Railway Postgres via DATABASE_URL)
. "$PSScriptRoot\_common.ps1"
Invoke-Step "." "docker" @("compose", "up", "-d", "--wait", "postgres")
