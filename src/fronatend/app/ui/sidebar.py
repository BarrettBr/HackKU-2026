from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout


class Sidebar(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("panel")
        self.setFixedWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Moovie Night")
        title.setObjectName("sectionTitle")
        subtitle = QLabel("Room controls")
        subtitle.setObjectName("mutedLabel")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        for label in ("Create Room", "Join Room", "Media Queue", "Settings"):
            layout.addWidget(QPushButton(label))

        layout.addStretch()
