from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QVBoxLayout


class UserList(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Participants")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        users = QListWidget()
        users.addItems(
            [
                "Barrett (Host)",
                "Alex",
                "Jordan",
            ]
        )
        layout.addWidget(users)
