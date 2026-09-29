# make seed — admin user, client "YP", placeholder SIP trunk, "YP SEO US (test)" campaign, sample DNC numbers.
# Needs SEED_ADMIN_PASSWORD in .env. Safe to re-run.
. "$PSScriptRoot\_common.ps1"
Invoke-Step "apps\api" "uv" @("run", "python", "-m", "app.seed")
