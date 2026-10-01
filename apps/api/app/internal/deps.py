"""X-Internal-Secret check for /internal/* (voice-worker → API)."""

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings


async def require_internal_secret(
    x_internal_secret: Annotated[str | None, Header()] = None,
) -> None:
    expected = get_settings().internal_api_secret
    if expected is None or not expected.get_secret_value():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "INTERNAL_API_SECRET not set")
    if not x_internal_secret or not hmac.compare_digest(
        x_internal_secret.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad internal secret")


InternalAuth = Depends(require_internal_secret)
