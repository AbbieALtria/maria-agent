# make migrate
. "$PSScriptRoot\_common.ps1"
Invoke-Step "apps\api" "uv" @("run", "alembic", "upgrade", "head")
