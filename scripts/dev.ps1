# make dev — API on :8000 (background) + web on :5173 (foreground). Ctrl+C stops both.
. "$PSScriptRoot\_common.ps1"
$api = Start-Process -FilePath "uv" `
    -ArgumentList "run", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000" `
    -WorkingDirectory (Join-Path $RepoRoot "apps\api") -NoNewWindow -PassThru
try {
    Invoke-Step "apps\web" "npm" @("run", "dev")
} finally {
    if ($api -and -not $api.HasExited) {
        # /T kills uvicorn's reloader child processes too.
        taskkill /PID $api.Id /T /F | Out-Null
    }
}
