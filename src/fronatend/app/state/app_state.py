from __future__ import annotations

from dataclasses import dataclass, field
import secrets


@dataclass
class AppState:
    room_name: str = "Friday Movie Room"
    display_name: str = field(
        default_factory=lambda: f"User{100 + secrets.randbelow(900)}"
    )
    movie_title: str = "Movie Title"
    movie_year: str = "2024"
    room_id: str = ""
    invite_link: str = ""
    compact_room_code: str = ""
    is_host: bool = False
    connection_status: str = "Not connected"
    participants: list[str] = field(default_factory=list)
