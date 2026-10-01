"""LiveKit agent dispatch (docs/outbound/02-ARCHITECTURE.md §2 step 1).

`get_dispatcher` is a FastAPI dependency so tests can swap in a fake.
"""

import json
import logging
from typing import Any, Protocol

from fastapi import HTTPException, status

from app.config import get_settings

log = logging.getLogger("maria.dialer.livekit")


class Dispatcher(Protocol):
    async def dispatch(self, room: str, metadata: dict[str, Any]) -> str:
        """Create an agent dispatch into `room`; returns the dispatch id."""
        ...


class LiveKitDispatcher:
    def __init__(self, url: str, api_key: str, api_secret: str, agent_name: str) -> None:
        self._url = url
        self._key = api_key
        self._secret = api_secret
        self.agent_name = agent_name

    async def dispatch(self, room: str, metadata: dict[str, Any]) -> str:
        from livekit import api

        lkapi = api.LiveKitAPI(self._url, self._key, self._secret)
        try:
            d = await lkapi.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=self.agent_name, room=room, metadata=json.dumps(metadata)
                )
            )
        finally:
            await lkapi.aclose()
        log.info("agent dispatched", extra={"room": room, "dispatch_id": d.id})
        return d.id


def get_dispatcher() -> Dispatcher:
    s = get_settings()
    if not (s.livekit_url and s.livekit_api_key and s.livekit_api_secret):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "LiveKit is not configured (LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET)",
        )
    return LiveKitDispatcher(
        s.livekit_url,
        s.livekit_api_key.get_secret_value(),
        s.livekit_api_secret.get_secret_value(),
        s.livekit_agent_name,
    )
