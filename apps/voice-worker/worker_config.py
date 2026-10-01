"""Voice-worker settings from environment variables (docs/outbound/02-ARCHITECTURE.md §6).

The repo-root .env is loaded for local dev. Secrets are never logged.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env() -> None:
    load_dotenv(REPO_ROOT / ".env", override=False)
    # livekit-plugins-elevenlabs reads ELEVEN_API_KEY; our .env uses ELEVENLABS_API_KEY.
    if os.environ.get("ELEVENLABS_API_KEY") and not os.environ.get("ELEVEN_API_KEY"):
        os.environ["ELEVEN_API_KEY"] = os.environ["ELEVENLABS_API_KEY"]
    os.environ.setdefault("LIVEKIT_AGENT_NAME", "maria-outbound")


REQUIRED = (
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "ANTHROPIC_API_KEY",
    "DEEPGRAM_API_KEY",
    "ELEVEN_API_KEY",
    "INTERNAL_API_SECRET",
)


@dataclass(frozen=True)
class WorkerConfig:
    api_base_url: str
    internal_api_secret: str
    agent_name: str

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        missing = [k for k in REQUIRED if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"voice-worker: missing environment variables: {', '.join(missing)}")
        return cls(
            api_base_url=os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/"),
            internal_api_secret=os.environ["INTERNAL_API_SECRET"],
            agent_name=os.environ["LIVEKIT_AGENT_NAME"],
        )
