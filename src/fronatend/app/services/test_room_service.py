from __future__ import annotations

import pytest

from app.services.room_service import (
    RoomClient,
    RoomHostService,
    build_invite_link,
    parse_join_target,
)


def test_parse_invite_link() -> None:
    invite = build_invite_link(room_id="MN-ABC123", host="127.0.0.1", port=4321)

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
            host="127.0.0.1",
            port=room.port,
        )
        client = RoomClient(display_name="Viewer")

        joined_room = await client.join(local_invite)

        assert joined_room.room_id == room.room_id
        assert joined_room.room_name == "Test Room"
        assert "Host" in joined_room.participants
        assert "Viewer" in joined_room.participants
    finally:
        await host.stop()
