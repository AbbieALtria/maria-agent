"""HTTP client for the API's /internal/* endpoints (header X-Internal-Secret)."""

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger("maria.worker.crm")


class CrmError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class CrmClient:
    def __init__(
        self,
        base_url: str,
        secret: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        retries: int = 3,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=f"{base_url}/internal",
            headers={"X-Internal-Secret": secret},
            timeout=httpx.Timeout(10.0, connect=5.0),
            transport=transport,
        )
        self._retries = retries

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, url: str, json: Any = None) -> dict[str, Any]:
        """Retries connection errors and 5xx with backoff; 4xx raise CrmError immediately."""
        for attempt in range(self._retries + 1):
            try:
                r = await self._http.request(method, url, json=json)
            except httpx.TransportError as exc:
                if attempt == self._retries:
                    raise CrmError(0, f"API unreachable: {type(exc).__name__}") from exc
            else:
                if r.status_code < 400:
                    return r.json()
                if r.status_code < 500 or attempt == self._retries:
                    try:
                        detail = r.json().get("detail", r.text)
                    except ValueError:
                        detail = r.text
                    raise CrmError(r.status_code, str(detail))
            await asyncio.sleep(0.25 * 2**attempt)
        raise AssertionError("unreachable")

    async def dispatch_context(self, attempt_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/dispatch-context/{attempt_id}")

    async def patch_call(self, attempt_id: str, **fields: Any) -> dict[str, Any]:
        return await self._request("PATCH", f"/calls/{attempt_id}", json=fields)

    async def post_event(self, attempt_id: str, event: dict[str, Any]) -> None:
        await self._request("POST", f"/calls/{attempt_id}/events", json=event)

    async def tool(self, attempt_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/calls/{attempt_id}/tool/{name}", json=args)
