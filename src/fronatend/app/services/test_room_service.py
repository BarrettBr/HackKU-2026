from __future__ import annotations

import httpx
import pytest

from app.services.room_service import (
    ChatAttachment,
    RoomClient,
    RoomHostService,
    RoomMovieInfo,
    RoomSubtitleInfo,
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


@pytest.mark.anyio
async def test_playback_state_updates_for_room() -> None:
    host = RoomHostService(display_name="Host")
    room = await host.start_room("Pause Room")

    try:
        local_invite = build_invite_link(
            room_id=room.room_id,
            room_name=room.room_name,
            host="127.0.0.1",
            port=room.port,
        )
        target = parse_join_target(local_invite)
        client = RoomClient(display_name="Viewer")

        updated_room = await client.update_playback(target, is_paused=True)
        fetched_room, _messages = await client.fetch_messages(target=target, after=0)

        assert updated_room.is_paused is True
        assert fetched_room.is_paused is True
    finally:
        await host.stop()


@pytest.mark.anyio
async def test_attachment_message_round_trips(tmp_path) -> None:
    host = RoomHostService(display_name="Host")
    room = await host.start_room("File Room")

    try:
        image_path = tmp_path / "poster.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-data")
        local_invite = build_invite_link(
            room_id=room.room_id,
            room_name=room.room_name,
            host="127.0.0.1",
            port=room.port,
        )
        target = parse_join_target(local_invite)
        client = RoomClient(display_name="Viewer")

        await client.send_attachment(target=target, file_path=str(image_path))
        _room, messages = await client.fetch_messages(target=target, after=0)

        assert messages[-1].attachment is not None
        assert messages[-1].attachment.filename == "poster.png"
        assert messages[-1].attachment.mime_type == "image/png"
    finally:
        await host.stop()


@pytest.mark.anyio
async def test_reaction_updates_selected_message() -> None:
    host = RoomHostService(display_name="Host")
    room = await host.start_room("Reaction Room")

    try:
        local_invite = build_invite_link(
            room_id=room.room_id,
            room_name=room.room_name,
            host="127.0.0.1",
            port=room.port,
        )
        target = parse_join_target(local_invite)
        client = RoomClient(display_name="Viewer")

        first = await client.send_message(target=target, text="First")
        await client.send_message(target=target, text="Second")
        updated = await client.send_reaction(
            target=target,
            message_id=first.id,
            reaction="🔥",
        )
        _room, messages = await client.fetch_messages(target=target, after=999)

        assert updated.id == first.id
        assert updated.reactions == {"🔥": 1}
        assert messages[0].reactions == {"🔥": 1}
        assert messages[1].reactions == {}
    finally:
        await host.stop()


@pytest.mark.anyio
async def test_non_image_attachment_keeps_filename_and_extension(tmp_path) -> None:
    host = RoomHostService(display_name="Host")
    room = await host.start_room("Document Room")

    try:
        file_path = tmp_path / "example.txt"
        file_path.write_text("hello")
        local_invite = build_invite_link(
            room_id=room.room_id,
            room_name=room.room_name,
            host="127.0.0.1",
            port=room.port,
        )
        target = parse_join_target(local_invite)
        client = RoomClient(display_name="Viewer")

        await client.send_attachment(target=target, file_path=str(file_path))
        _room, messages = await client.fetch_messages(target=target, after=0)

        assert messages[-1].attachment is not None
        assert messages[-1].attachment.filename == "example.txt"
        assert messages[-1].attachment.mime_type == "text/plain"
    finally:
        await host.stop()


@pytest.mark.anyio
async def test_prepared_gif_attachment_round_trips() -> None:
    host = RoomHostService(display_name="Host")
    room = await host.start_room("GIF Room")

    try:
        local_invite = build_invite_link(
            room_id=room.room_id,
            room_name=room.room_name,
            host="127.0.0.1",
            port=room.port,
        )
        target = parse_join_target(local_invite)
        client = RoomClient(display_name="Viewer")
        attachment = ChatAttachment(
            filename="popcorn.gif",
            mime_type="image/gif",
            data_base64="R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==",
        )

        await client.send_prepared_attachment(target=target, attachment=attachment)
        _room, messages = await client.fetch_messages(target=target, after=0)

        assert messages[-1].attachment is not None
        assert messages[-1].attachment.filename == "popcorn.gif"
        assert messages[-1].attachment.mime_type == "image/gif"
    finally:
        await host.stop()


@pytest.mark.anyio
async def test_movie_info_updates_for_room() -> None:
    host = RoomHostService(display_name="Host")
    room = await host.start_room("Movie Info Room")

    try:
        local_invite = build_invite_link(
            room_id=room.room_id,
            room_name=room.room_name,
            host="127.0.0.1",
            port=room.port,
        )
        target = parse_join_target(local_invite)
        client = RoomClient(display_name="Viewer")
        movie = RoomMovieInfo(
            title="The Matrix",
            year="1999",
            plot="A hacker discovers reality is not what it seems.",
            actors="Keanu Reeves, Laurence Fishburne",
            rating="8.7",
        )

        updated_room = await client.update_movie(target=target, movie=movie)
        fetched_room, _messages = await client.fetch_messages(target=target, after=0)

        assert updated_room.movie == movie
        assert fetched_room.movie == movie
    finally:
        await host.stop()


@pytest.mark.anyio
async def test_subtitles_update_for_room() -> None:
    host = RoomHostService(display_name="Host")
    room = await host.start_room("Subtitle Room")

    try:
        local_invite = build_invite_link(
            room_id=room.room_id,
            room_name=room.room_name,
            host="127.0.0.1",
            port=room.port,
        )
        target = parse_join_target(local_invite)
        client = RoomClient(display_name="Viewer")
        subtitles = RoomSubtitleInfo(
            filename="movie.srt",
            content=("1\n00:00:01,000 --> 00:00:03,000\n" "Hello from subtitles.\n"),
            cue_count=1,
        )

        updated_room = await client.update_subtitles(
            target=target,
            subtitles=subtitles,
        )
        fetched_room, _messages = await client.fetch_messages(target=target, after=0)

        assert updated_room.subtitles == subtitles
        assert fetched_room.subtitles == subtitles
    finally:
        await host.stop()
