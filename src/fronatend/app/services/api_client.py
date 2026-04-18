from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings


class ApiClient:
    """Small async wrapper around the localhost HTTP API."""

    def __init__(self, settings: Settings, timeout_seconds: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.backend_http_url.rstrip("/"),
            timeout=timeout_seconds,
        )

    async def get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response

    async def post(
        self, path: str, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        response = await self._client.post(path, json=json)
        response.raise_for_status()
        return response

    async def close(self) -> None:
        await self._client.aclose()
