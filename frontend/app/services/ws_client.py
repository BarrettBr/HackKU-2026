from __future__ import annotations

from collections.abc import Awaitable, Callable

from websockets.asyncio.client import ClientConnection, connect

from app.config import Settings


MessageHandler = Callable[[str], Awaitable[None]]


class WsClient:
    """Minimal websocket client for room events and chat updates."""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.backend_ws_url
        self._connection: ClientConnection | None = None

    async def connect(self) -> ClientConnection:
        if self._connection is None:
            self._connection = await connect(self._url)
        return self._connection

    async def listen(self, handler: MessageHandler) -> None:
        connection = await self.connect()
        async for message in connection:
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            await handler(message)

    async def send(self, message: str) -> None:
        connection = await self.connect()
        await connection.send(message)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
