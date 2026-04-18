from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AppState:
    room_name: str = "Friday Movie Room"
    display_name: str = "Local User"
    movie_title: str = "Movie Title"
    movie_year: str = "2024"
    participants: list[str] = field(
        default_factory=lambda: ["User1 (Host)", "User2", "User3", "User4"]
    )
