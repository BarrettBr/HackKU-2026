from __future__ import annotations

import httpx
import pytest

from app.services.room_service import (
    RoomClient,
    RoomHostService,
    build_invite_link,
    parse_join_target,
)


def test_parse_invite_link() -> None:
    invite = build_invite_link(
        room_id="MN-ABC123",
        room_name="Friday Movie Room",
        host="127.0.0.1",
        port=4321,
    )

    assert invite.startswith("moovie:friday-movie-room?key=")

    target = parse_join_target(invite)

    assert target.room_id == "MN-ABC123"
    assert target.host == "127.0.0.1"
    assert target.port == 4321


def test_parse_compact_room_code() -> None:
    target = parse_join_target("MN-ABC123@127.0.0.1:4321")

    assert target.room_id == "MN-ABC123"
    assert target.host == "127.0.0.1"
    assert target.port == 4321


@pytest.mark.anyio
async def test_host_room_accepts_join_from_invite_link() -> None:
    host = RoomHostService(display_name="Host")
    room = await host.start_room("Test Room")

    try:
        local_invite = build_invite_link(
            room_id=room.room_id,
            room_name=room.room_name,
            host="127.0.0.1",
            port=room.port,
        )
        client = RoomClient(display_name="Viewer")

        joined_room = await client.join(local_invite)
        message = await client.send_message(
            target=parse_join_target(local_invite),
            text="Hello from viewer",
        )
        _room, messages = await client.fetch_messages(
            target=parse_join_target(local_invite),
            after=0,
        )

        assert joined_room.room_id == room.room_id
        assert joined_room.room_name == "Test Room"
        assert "Host" in joined_room.participants
        assert "Viewer" in joined_room.participants
        assert message.text == "Hello from viewer"
        assert messages[-1].text == "Hello from viewer"
    finally:
        await host.stop()


@pytest.mark.anyio
async def test_host_stop_ends_room_for_clients() -> None:
    host = RoomHostService(display_name="Host")
    room = await host.start_room("Short Room")
    local_invite = build_invite_link(
        room_id=room.room_id,
        room_name=room.room_name,
        host="127.0.0.1",
        port=room.port,
    )
    target = parse_join_target(local_invite)
    client = RoomClient(display_name="Viewer")

    await client.join(local_invite)
    await host.stop()

    with pytest.raises(httpx.HTTPError):
        await client.fetch_messages(target=target, after=0)


@pytest.mark.anyio
async def test_viewer_leave_updates_participants() -> None:
    host = RoomHostService(display_name="Host")
    room = await host.start_room("Leave Room")

    try:
        local_invite = build_invite_link(
            room_id=room.room_id,
            room_name=room.room_name,
            host="127.0.0.1",
            port=room.port,
        )
        target = parse_join_target(local_invite)
        client = RoomClient(display_name="Viewer")

        await client.join(local_invite)
        await client.leave(target)
        updated_room, _messages = await client.fetch_messages(target=target, after=0)

        assert "Host" in updated_room.participants
        assert "Viewer" not in updated_room.participants
    finally:
        await host.stop()
