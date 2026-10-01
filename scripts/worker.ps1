# Voice-worker in dev mode (registers as LIVEKIT_AGENT_NAME with LiveKit Cloud). Ctrl+C stops it.
# The first run downloads the turn-detector / VAD model files.
. "$PSScriptRoot\_common.ps1"
Invoke-Step "apps\voice-worker" "uv" @("run", "python", "main.py", "download-files")
Invoke-Step "apps\voice-worker" "uv" @("run", "python", "main.py", "dev")
