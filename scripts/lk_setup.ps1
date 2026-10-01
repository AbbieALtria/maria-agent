# LiveKit SIP trunk "telnyx-us" + test campaign/lead/playbook setup (Phase 2). Safe to re-run.
# Also appends a generated INTERNAL_API_SECRET to .env if missing. Run scripts/seed.ps1 first.
. "$PSScriptRoot\_common.ps1"
Invoke-Step "." "uv" @("run", "python", "scripts/lk_setup.py")
