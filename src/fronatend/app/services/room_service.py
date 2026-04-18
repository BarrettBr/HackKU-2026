from __future__ import annotations

import asyncio
import base64
import json
import secrets
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

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
class ChatMessage:
    id: int
    author: str
    text: str


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
        self._messages: list[ChatMessage] = []
        self._next_message_id = 1

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
        invite_link = build_invite_link(
            room_id=room_id,
            room_name=room_name,
            host=host,
            port=port,
        )
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
        self._messages = []
        self._next_message_id = 1
        return self.room

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self.room = None
        self._messages = []
        self._next_message_id = 1

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
        elif method == "POST" and path == "/leave":
            status, payload = self._handle_leave(body)
        elif method == "GET" and path.startswith("/messages"):
            status, payload = self._handle_get_messages(path)
        elif method == "POST" and path == "/messages":
            status, payload = self._handle_post_message(body)
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

    def _handle_leave(self, body: bytes) -> tuple[int, dict[str, Any]]:
        if self.room is None:
            return 503, {"ok": False, "error": "room is not active"}

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return 400, {"ok": False, "error": "invalid JSON"}

        if data.get("room_id") != self.room.room_id:
            return 404, {"ok": False, "error": "room ID does not match this host"}

        display_name = str(data.get("display_name") or "")
        if display_name and display_name != self.display_name:
            self.room.participants = [
                participant
                for participant in self.room.participants
                if participant != display_name
            ]

        return 200, {"ok": True, "room": self._room_payload()}

    def _handle_get_messages(self, path: str) -> tuple[int, dict[str, Any]]:
        after = 0
        parsed = urlparse(path)
        params = parse_qs(parsed.query)
        if "after" in params:
            after = int(params["after"][0])

        return 200, {
            "ok": True,
            "messages": [
                {"id": message.id, "author": message.author, "text": message.text}
                for message in self._messages
                if message.id > after
            ],
            "room": self._room_payload(),
        }

    def _handle_post_message(self, body: bytes) -> tuple[int, dict[str, Any]]:
        if self.room is None:
            return 503, {"ok": False, "error": "room is not active"}

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return 400, {"ok": False, "error": "invalid JSON"}

        if data.get("room_id") != self.room.room_id:
            return 404, {"ok": False, "error": "room ID does not match this host"}

        author = str(data.get("author") or "Viewer")
        text = str(data.get("text") or "").strip()
        if not text:
            return 400, {"ok": False, "error": "message cannot be empty"}

        message = ChatMessage(id=self._next_message_id, author=author, text=text)
        self._next_message_id += 1
        self._messages.append(message)
        if author not in self.room.participants:
            self.room.participants.append(author)

        return 200, {
            "ok": True,
            "message": {
                "id": message.id,
                "author": message.author,
                "text": message.text,
            },
            "room": self._room_payload(),
        }

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
        return room_info_from_payload(room_payload)

    async def leave(self, target: JoinTarget) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://{target.host}:{target.port}/leave",
                json={
                    "room_id": target.room_id,
                    "display_name": self.display_name,
                },
            )
            response.raise_for_status()

    async def send_message(self, target: JoinTarget, text: str) -> ChatMessage:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://{target.host}:{target.port}/messages",
                json={
                    "room_id": target.room_id,
                    "author": self.display_name,
                    "text": text,
                },
            )
            response.raise_for_status()
            payload = response.json()

        message = payload["message"]
        return ChatMessage(
            id=int(message["id"]),
            author=str(message["author"]),
            text=str(message["text"]),
        )

    async def fetch_messages(
        self,
        target: JoinTarget,
        after: int,
    ) -> tuple[RoomInfo, list[ChatMessage]]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"http://{target.host}:{target.port}/messages",
                params={"after": after},
            )
            response.raise_for_status()
            payload = response.json()

        return room_info_from_payload(payload["room"]), [
            ChatMessage(
                id=int(message["id"]),
                author=str(message["author"]),
                text=str(message["text"]),
            )
            for message in payload["messages"]
        ]


def room_info_from_payload(room_payload: dict[str, Any]) -> RoomInfo:
    return RoomInfo(
        room_id=room_payload["room_id"],
        room_name=room_payload["room_name"],
        host=room_payload["host"],
        port=int(room_payload["port"]),
        invite_link=room_payload["invite_link"],
        compact_code=room_payload["compact_code"],
        participants=list(room_payload["participants"]),
    )


def build_invite_link(room_id: str, room_name: str, host: str, port: int) -> str:
    slug = quote(_slugify(room_name))
    passkey = _encode_passkey({"room_id": room_id, "host": host, "port": port})
    return f"moovie:{slug}?key={passkey}"


def parse_join_target(invite_or_code: str) -> JoinTarget:
    value = invite_or_code.strip()
    if not value:
        raise ValueError("Enter an invite link or room code.")

    parsed = urlparse(value)
    if parsed.scheme == "moovie" and "key" in parse_qs(parsed.query):
        data = _decode_passkey(_single_param(parse_qs(parsed.query), "key"))
        return JoinTarget(
            room_id=str(data["room_id"]),
            host=str(data["host"]),
            port=int(data["port"]),
        )

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


def _slugify(room_name: str) -> str:
    words = "".join(
        character.lower() if character.isalnum() else "-" for character in room_name
    )
    slug = "-".join(part for part in words.split("-") if part)
    return slug or "room"


def _encode_passkey(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _decode_passkey(passkey: str) -> dict[str, Any]:
    padding = "=" * (-len(passkey) % 4)
    raw = base64.urlsafe_b64decode(f"{passkey}{padding}".encode("utf-8"))
    return json.loads(raw.decode("utf-8"))


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
