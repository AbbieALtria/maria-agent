# make install
. "$PSScriptRoot\_common.ps1"
Invoke-Step "." "uv" @("sync", "--all-packages")
Invoke-Step "apps\web" "npm" @("install")
