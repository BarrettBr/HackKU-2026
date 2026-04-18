from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class ChatPanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Room Chat")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        transcript = QTextEdit()
        transcript.setReadOnly(True)
        transcript.setPlainText(
            "Host: Welcome to Moovie Night!\n"
            "Viewer: Ready when you are.\n"
            "System: Chat service will connect to the backend over localhost."
        )
        layout.addWidget(transcript, 1)

        composer = QHBoxLayout()
        composer.setSpacing(8)

        message_input = QLineEdit()
        message_input.setPlaceholderText("Send a message to the room")
        send_button = QPushButton("Send")

        composer.addWidget(message_input, 1)
        composer.addWidget(send_button, 0)
        layout.addLayout(composer)
