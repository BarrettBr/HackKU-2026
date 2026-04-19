from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
from pathlib import Path
import secrets
import socket
from dataclasses import dataclass, field, replace
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
    is_paused: bool = False
    movie: RoomMovieInfo | None = None
    subtitles: RoomSubtitleInfo | None = None


@dataclass(frozen=True)
class RoomMovieInfo:
    title: str
    year: str = ""
    plot: str = ""
    actors: str = ""
    rating: str = ""


@dataclass(frozen=True)
class RoomSubtitleInfo:
    filename: str
    content: str
    cue_count: int


@dataclass(frozen=True)
class WatcherSubscription:
    ipc_path: str
    width: int
    height: int
    pixel_format: str


@dataclass(frozen=True)
class ChatAttachment:
    filename: str
    mime_type: str
    data_base64: str


@dataclass(frozen=True)
class ChatMessage:
    id: int
    author: str
    text: str
    attachment: ChatAttachment | None = None
    reactions: dict[str, int] = field(default_factory=dict)


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
        self._is_paused = False
        self._movie: RoomMovieInfo | None = None
        self._subtitles: RoomSubtitleInfo | None = None

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
            is_paused=False,
        )
        self._messages = []
        self._next_message_id = 1
        self._is_paused = False
        self._movie = None
        self._subtitles = None
        return self.room

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self.room = None
        self._messages = []
        self._next_message_id = 1
        self._is_paused = False
        self._movie = None
        self._subtitles = None

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
        elif method == "POST" and path == "/reactions":
            status, payload = self._handle_post_reaction(body)
        elif method == "POST" and path == "/playback":
            status, payload = self._handle_playback(body)
        elif method == "POST" and path == "/movie":
            status, payload = self._handle_movie(body)
        elif method == "POST" and path == "/subtitles":
            status, payload = self._handle_subtitles(body)
        elif method == "POST" and path == "/webrtc/offer":
            status, payload = self._handle_webrtc_offer(body)
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
        # Keep endpoint signature stable; return full feed so reaction updates
        # on older messages stay in sync for all clients.
        _ = path
        return 200, {
            "ok": True,
            "messages": [_message_payload(message) for message in self._messages],
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
        attachment = _attachment_from_payload(data.get("attachment"))
        if not text and attachment is None:
            return 400, {"ok": False, "error": "message cannot be empty"}

        message = ChatMessage(
            id=self._next_message_id,
            author=author,
            text=text,
            attachment=attachment,
        )
        self._next_message_id += 1
        self._messages.append(message)
        if author not in self.room.participants:
            self.room.participants.append(author)

        return 200, {
            "ok": True,
            "message": _message_payload(message),
            "room": self._room_payload(),
        }

    def _handle_post_reaction(self, body: bytes) -> tuple[int, dict[str, Any]]:
        if self.room is None:
            return 503, {"ok": False, "error": "room is not active"}

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return 400, {"ok": False, "error": "invalid JSON"}

        if data.get("room_id") != self.room.room_id:
            return 404, {"ok": False, "error": "room ID does not match this host"}

        message_id = int(data.get("message_id") or 0)
        reaction = str(data.get("reaction") or "").strip()
        if not reaction:
            return 400, {"ok": False, "error": "reaction cannot be empty"}

        for index, message in enumerate(self._messages):
            if message.id != message_id:
                continue

            reactions = dict(message.reactions)
            reactions[reaction] = reactions.get(reaction, 0) + 1
            updated_message = replace(message, reactions=reactions)
            self._messages[index] = updated_message
            return 200, {
                "ok": True,
                "message": _message_payload(updated_message),
                "room": self._room_payload(),
            }

        return 404, {"ok": False, "error": "message not found"}

    def _handle_playback(self, body: bytes) -> tuple[int, dict[str, Any]]:
        if self.room is None:
            return 503, {"ok": False, "error": "room is not active"}

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return 400, {"ok": False, "error": "invalid JSON"}

        if data.get("room_id") != self.room.room_id:
            return 404, {"ok": False, "error": "room ID does not match this host"}

        self._is_paused = bool(data.get("is_paused"))
        self.room.is_paused = self._is_paused
        return 200, {"ok": True, "room": self._room_payload()}

    def _handle_movie(self, body: bytes) -> tuple[int, dict[str, Any]]:
        if self.room is None:
            return 503, {"ok": False, "error": "room is not active"}

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return 400, {"ok": False, "error": "invalid JSON"}

        if data.get("room_id") != self.room.room_id:
            return 404, {"ok": False, "error": "room ID does not match this host"}

        movie = _movie_from_payload(data.get("movie"))
        if movie is None:
            return 400, {"ok": False, "error": "movie info is missing"}

        self._movie = movie
        self.room.movie = movie
        return 200, {"ok": True, "room": self._room_payload()}

    def _handle_webrtc_offer(self, body: bytes) -> tuple[int, dict[str, Any]]:
        if self.room is None:
            return 503, {"ok": False, "error": "room is not active"}

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return 400, {"ok": False, "error": "invalid JSON"}

        if data.get("room_code") != self.room.room_id:
            return 404, {"ok": False, "error": "room code does not match this host"}

        offer_type = str(data.get("type") or "offer")
        sdp = str(data.get("sdp") or "")
        if not sdp:
            return 400, {"ok": False, "error": "missing SDP"}

        engine_url = f"http://{self.room.host}:8080/offer"
        try:
            response = httpx.post(
                engine_url,
                json={
                    "room_code": self.room.room_id,
                    "type": offer_type,
                    "sdp": sdp,
                },
                timeout=8.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            return 503, {"ok": False, "error": f"engine offer exchange failed: {error}"}

        return 200, payload

    def _handle_subtitles(self, body: bytes) -> tuple[int, dict[str, Any]]:
        if self.room is None:
            return 503, {"ok": False, "error": "room is not active"}

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return 400, {"ok": False, "error": "invalid JSON"}

        if data.get("room_id") != self.room.room_id:
            return 404, {"ok": False, "error": "room ID does not match this host"}

        subtitles = _subtitles_from_payload(data.get("subtitles"))
        if subtitles is None:
            return 400, {"ok": False, "error": "subtitle info is missing"}

        self._subtitles = subtitles
        self.room.subtitles = subtitles
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
            "is_paused": self._is_paused,
            "movie": _movie_payload(self._movie) if self._movie is not None else None,
            "subtitles": (
                _subtitles_payload(self._subtitles)
                if self._subtitles is not None
                else None
            ),
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
        return chat_message_from_payload(message)

    async def send_attachment(
        self,
        target: JoinTarget,
        file_path: str,
        caption: str = "",
    ) -> ChatMessage:
        attachment = attachment_from_file(file_path)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"http://{target.host}:{target.port}/messages",
                json={
                    "room_id": target.room_id,
                    "author": self.display_name,
                    "text": caption,
                    "attachment": _attachment_payload(attachment),
                },
            )
            response.raise_for_status()
            payload = response.json()

        return chat_message_from_payload(payload["message"])

    async def send_prepared_attachment(
        self,
        target: JoinTarget,
        attachment: ChatAttachment,
        caption: str = "",
    ) -> ChatMessage:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"http://{target.host}:{target.port}/messages",
                json={
                    "room_id": target.room_id,
                    "author": self.display_name,
                    "text": caption,
                    "attachment": _attachment_payload(attachment),
                },
            )
            response.raise_for_status()
            payload = response.json()

        return chat_message_from_payload(payload["message"])

    async def send_reaction(
        self,
        target: JoinTarget,
        message_id: int,
        reaction: str,
    ) -> ChatMessage:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://{target.host}:{target.port}/reactions",
                json={
                    "room_id": target.room_id,
                    "message_id": message_id,
                    "reaction": reaction,
                },
            )
            response.raise_for_status()
            payload = response.json()

        return chat_message_from_payload(payload["message"])

    async def update_playback(self, target: JoinTarget, is_paused: bool) -> RoomInfo:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://{target.host}:{target.port}/playback",
                json={
                    "room_id": target.room_id,
                    "is_paused": is_paused,
                },
            )
            response.raise_for_status()
            payload = response.json()

        return room_info_from_payload(payload["room"])

    async def update_movie(self, target: JoinTarget, movie: RoomMovieInfo) -> RoomInfo:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"http://{target.host}:{target.port}/movie",
                json={
                    "room_id": target.room_id,
                    "movie": _movie_payload(movie),
                },
            )
            response.raise_for_status()
            payload = response.json()

        return room_info_from_payload(payload["room"])

    async def update_subtitles(
        self,
        target: JoinTarget,
        subtitles: RoomSubtitleInfo,
    ) -> RoomInfo:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"http://{target.host}:{target.port}/subtitles",
                json={
                    "room_id": target.room_id,
                    "subtitles": _subtitles_payload(subtitles),
                },
            )
            response.raise_for_status()
            payload = response.json()

        return room_info_from_payload(payload["room"])

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
            chat_message_from_payload(message) for message in payload["messages"]
        ]


class EngineRuntimeClient:
    def __init__(
        self,
        engine_api_host: str = "127.0.0.1",
        engine_api_port: int = 8080,
    ) -> None:
        self.engine_api_host = engine_api_host
        self.engine_api_port = engine_api_port

    def _base_url(self) -> str:
        return f"http://{self.engine_api_host}:{self.engine_api_port}"

    async def subscribe_watcher(self, target: JoinTarget) -> WatcherSubscription:
        signaling_url = f"http://{target.host}:{target.port}/webrtc/offer"
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                f"{self._base_url()}/subscribe",
                json={
                    "room_code": target.room_id,
                    "signaling_url": signaling_url,
                },
            )
            response.raise_for_status()
            payload = response.json()

        subscription = payload.get("subscription") or {}
        return WatcherSubscription(
            ipc_path=str(subscription.get("ipc_path") or ""),
            width=int(subscription.get("width") or 0),
            height=int(subscription.get("height") or 0),
            pixel_format=str(subscription.get("pixel_format") or ""),
        )

    async def unsubscribe(self, target: JoinTarget) -> None:
        _ = target
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{self._base_url()}/unsubscribe", json={}
            )
            response.raise_for_status()

    async def get_subscription(self, target: JoinTarget) -> WatcherSubscription:
        _ = target
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{self._base_url()}/subscription")
            response.raise_for_status()
            payload = response.json()

        return WatcherSubscription(
            ipc_path=str(payload.get("ipc_path") or ""),
            width=int(payload.get("width") or 0),
            height=int(payload.get("height") or 0),
            pixel_format=str(payload.get("pixel_format") or ""),
        )


def room_info_from_payload(room_payload: dict[str, Any]) -> RoomInfo:
    return RoomInfo(
        room_id=room_payload["room_id"],
        room_name=room_payload["room_name"],
        host=room_payload["host"],
        port=int(room_payload["port"]),
        invite_link=room_payload["invite_link"],
        compact_code=room_payload["compact_code"],
        participants=list(room_payload["participants"]),
        is_paused=bool(room_payload.get("is_paused", False)),
        movie=_movie_from_payload(room_payload.get("movie")),
        subtitles=_subtitles_from_payload(room_payload.get("subtitles")),
    )


def chat_message_from_payload(message: dict[str, Any]) -> ChatMessage:
    return ChatMessage(
        id=int(message["id"]),
        author=str(message["author"]),
        text=str(message["text"]),
        attachment=_attachment_from_payload(message.get("attachment")),
        reactions={
            str(reaction): int(count)
            for reaction, count in dict(message.get("reactions") or {}).items()
        },
    )


def attachment_from_file(file_path: str) -> ChatAttachment:
    path = Path(file_path)
    data = path.read_bytes()
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return ChatAttachment(
        filename=path.name,
        mime_type=mime_type,
        data_base64=base64.b64encode(data).decode("ascii"),
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


def _message_payload(message: ChatMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "author": message.author,
        "text": message.text,
        "attachment": (
            _attachment_payload(message.attachment)
            if message.attachment is not None
            else None
        ),
        "reactions": message.reactions,
    }


def _attachment_payload(attachment: ChatAttachment) -> dict[str, str]:
    return {
        "filename": attachment.filename,
        "mime_type": attachment.mime_type,
        "data_base64": attachment.data_base64,
    }


def _attachment_from_payload(payload: Any) -> ChatAttachment | None:
    if not isinstance(payload, dict):
        return None

    filename = str(payload.get("filename") or "attachment")
    mime_type = str(payload.get("mime_type") or "application/octet-stream")
    data_base64 = str(payload.get("data_base64") or "")
    if not data_base64:
        return None

    return ChatAttachment(
        filename=filename,
        mime_type=mime_type,
        data_base64=data_base64,
    )


def _movie_payload(movie: RoomMovieInfo) -> dict[str, str]:
    return {
        "title": movie.title,
        "year": movie.year,
        "plot": movie.plot,
        "actors": movie.actors,
        "rating": movie.rating,
    }


def _movie_from_payload(payload: Any) -> RoomMovieInfo | None:
    if not isinstance(payload, dict):
        return None

    title = str(payload.get("title") or "")
    if not title:
        return None

    return RoomMovieInfo(
        title=title,
        year=str(payload.get("year") or ""),
        plot=str(payload.get("plot") or ""),
        actors=str(payload.get("actors") or ""),
        rating=str(payload.get("rating") or ""),
    )


def _subtitles_payload(subtitles: RoomSubtitleInfo) -> dict[str, Any]:
    return {
        "filename": subtitles.filename,
        "content": subtitles.content,
        "cue_count": subtitles.cue_count,
    }


def _subtitles_from_payload(payload: Any) -> RoomSubtitleInfo | None:
    if not isinstance(payload, dict):
        return None

    filename = str(payload.get("filename") or "")
    content = str(payload.get("content") or "")
    cue_count = int(payload.get("cue_count") or 0)
    if not filename or not content or cue_count <= 0:
        return None

    return RoomSubtitleInfo(
        filename=filename,
        content=content,
        cue_count=cue_count,
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
