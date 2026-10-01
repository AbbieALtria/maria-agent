# Place a test call to TEST_PHONE and follow it live. Extra args pass through, e.g. -- --lead <id>
. "$PSScriptRoot\_common.ps1"
Invoke-Step "." "uv" (@("run", "python", "scripts/test_call.py") + $args)
