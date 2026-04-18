from __future__ import annotations

import asyncio
import json
import secrets
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx


def generate_room_id() -> str:
    return f"MN-{secrets.token_hex(3).upper()}"


def get_lan_ip() -> str:
    """Best-effort LAN IP detection for invite links."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


@dataclass
class RoomInfo:
    room_id: str
    room_name: str
    host: str
    port: int
    invite_link: str
    compact_code: str
    participants: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class JoinTarget:
    room_id: str
    host: str
    port: int


class RoomHostService:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name
        self.room: RoomInfo | None = None
        self._server: asyncio.AbstractServer | None = None

    async def start_room(self, room_name: str) -> RoomInfo:
        await self.stop()

        room_id = generate_room_id()
        self._server = await asyncio.start_server(
            self._handle_client,
            host="0.0.0.0",
            port=0,
        )
        socket_name = self._server.sockets[0].getsockname()
        port = int(socket_name[1])
        host = get_lan_ip()
        invite_link = build_invite_link(room_id=room_id, host=host, port=port)
        compact_code = f"{room_id}@{host}:{port}"

        self.room = RoomInfo(
            room_id=room_id,
            room_name=room_name,
            host=host,
            port=port,
            invite_link=invite_link,
            compact_code=compact_code,
            participants=[self.display_name],
        )
        return self.room

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self.room = None

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request = await reader.readuntil(b"\r\n\r\n")
        except asyncio.IncompleteReadError:
            writer.close()
            await writer.wait_closed()
            return

        header_text = request.decode("utf-8", errors="replace")
        headers = header_text.split("\r\n")
        method, path, _version = headers[0].split(" ", maxsplit=2)
        content_length = _read_content_length(headers)
        body = b""
        if content_length > 0:
            body = await reader.readexactly(content_length)

        status = 404
        payload: dict[str, Any] = {"ok": False, "error": "not found"}

        if self.room is None:
            status = 503
            payload = {"ok": False, "error": "room is not active"}
        elif method == "GET" and path.startswith("/room"):
            status = 200
            payload = {"ok": True, "room": self._room_payload()}
        elif method == "POST" and path == "/join":
            status, payload = self._handle_join(body)
        elif method == "GET" and path == "/health":
            status = 200
            payload = {"ok": True}

        response = _json_response(status, payload)
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    def _handle_join(self, body: bytes) -> tuple[int, dict[str, Any]]:
        if self.room is None:
            return 503, {"ok": False, "error": "room is not active"}

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return 400, {"ok": False, "error": "invalid JSON"}

        if data.get("room_id") != self.room.room_id:
            return 404, {"ok": False, "error": "room ID does not match this host"}

        display_name = str(data.get("display_name") or "Viewer")
        if display_name not in self.room.participants:
            self.room.participants.append(display_name)

        return 200, {"ok": True, "room": self._room_payload()}

    def _room_payload(self) -> dict[str, Any]:
        if self.room is None:
            return {}

        return {
            "room_id": self.room.room_id,
            "room_name": self.room.room_name,
            "host": self.room.host,
            "port": self.room.port,
            "invite_link": self.room.invite_link,
            "compact_code": self.room.compact_code,
            "participants": self.room.participants,
        }


class RoomClient:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name

    async def join(self, invite_or_code: str) -> RoomInfo:
        target = parse_join_target(invite_or_code)
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://{target.host}:{target.port}/join",
                json={
                    "room_id": target.room_id,
                    "display_name": self.display_name,
                },
            )
            response.raise_for_status()
            payload = response.json()

        room_payload = payload["room"]
        return RoomInfo(
            room_id=room_payload["room_id"],
            room_name=room_payload["room_name"],
            host=room_payload["host"],
            port=int(room_payload["port"]),
            invite_link=room_payload["invite_link"],
            compact_code=room_payload["compact_code"],
            participants=list(room_payload["participants"]),
        )


def build_invite_link(room_id: str, host: str, port: int) -> str:
    query = urlencode({"room_id": room_id, "host": host, "port": str(port)})
    return f"moovie://join?{query}"


def parse_join_target(invite_or_code: str) -> JoinTarget:
    value = invite_or_code.strip()
    if not value:
        raise ValueError("Enter an invite link or room code.")

    parsed = urlparse(value)
    if parsed.scheme == "moovie" and parsed.netloc == "join":
        params = parse_qs(parsed.query)
        room_id = _single_param(params, "room_id")
        host = _single_param(params, "host")
        port = int(_single_param(params, "port"))
        return JoinTarget(room_id=room_id, host=host, port=port)

    if "@" in value and ":" in value.rsplit("@", maxsplit=1)[1]:
        room_id, address = value.rsplit("@", maxsplit=1)
        host, port_text = address.rsplit(":", maxsplit=1)
        return JoinTarget(room_id=room_id, host=host, port=int(port_text))

    raise ValueError(
        "Room IDs need host info for P2P. Paste the invite link or ROOM@host:port code."
    )


def _single_param(params: dict[str, list[str]], name: str) -> str:
    value = params.get(name, [""])[0]
    if not value:
        raise ValueError(f"Invite link is missing {name}.")
    return value


def _read_content_length(headers: list[str]) -> int:
    for header in headers:
        if header.lower().startswith("content-length:"):
            return int(header.split(":", maxsplit=1)[1].strip())
    return 0


def _json_response(status: int, payload: dict[str, Any]) -> bytes:
    reason = {
        200: "OK",
        400: "Bad Request",
        404: "Not Found",
        503: "Service Unavailable",
    }.get(status, "Error")
    body = json.dumps(payload).encode("utf-8")
    headers = [
        f"HTTP/1.1 {status} {reason}",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(headers).encode("utf-8") + body
