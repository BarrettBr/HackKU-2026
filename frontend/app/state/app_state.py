from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AppState:
    room_name: str = "Friday Movie Room"
    display_name: str = "Local User"
    participants: list[str] = field(
        default_factory=lambda: ["Barrett (Host)", "Alex", "Jordan"]
    )
