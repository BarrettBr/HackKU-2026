from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class ChatBubble(QFrame):
    def __init__(self, author: str, message: str, accent: bool = False) -> None:
        super().__init__()
        self.setObjectName("chatBubbleAccent" if accent else "chatBubble")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        author_label = QLabel(author)
        author_label.setObjectName("chatAuthor")

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setTextFormat(Qt.TextFormat.PlainText)

        layout.addWidget(author_label)
        layout.addWidget(message_label)


class ChatPanel(QFrame):
    message_sent = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("chatPanel")
        self.setMinimumWidth(320)
        self.setMaximumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("chatHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 18, 20, 14)

        title = QLabel("Chat")
        title.setObjectName("chatTitle")
        header_layout.addWidget(title)
        layout.addWidget(header)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self._messages_root = QWidget()
        self._messages_layout = QVBoxLayout(self._messages_root)
        self._messages_layout.setContentsMargins(12, 12, 12, 12)
        self._messages_layout.setSpacing(10)
        self._messages_layout.addStretch()
        self._scroll_area.setWidget(self._messages_root)

        layout.addWidget(self._scroll_area, 1)

        composer = QFrame()
        composer.setObjectName("chatComposer")
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(12, 12, 12, 12)
        composer_layout.setSpacing(8)

        self._message_input = QLineEdit()
        self._message_input.setPlaceholderText("Type a message...")
        self._message_input.returnPressed.connect(self._send_message)
        self._message_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        send_button = QPushButton("Send")
        send_button.setObjectName("primaryButton")
        send_button.clicked.connect(self._send_message)

        composer_layout.addWidget(self._message_input, 1)
        composer_layout.addWidget(send_button)
        layout.addWidget(composer)

    def seed_messages(self) -> None:
        self.add_message("User1 (Host)", "Hello everyone!", accent=True)
        self.add_message("User2", "Hi there!")
        self.add_message("User1", "Ready to watch!", accent=True)
        self.add_message("User4", "Let's do this!")

    def add_message(self, author: str, message: str, accent: bool = False) -> None:
        bubble = ChatBubble(author=author, message=message, accent=accent)
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, bubble)
        self._scroll_to_bottom()

    def _send_message(self) -> None:
        message = self._message_input.text().strip()
        if not message:
            return

        self._message_input.clear()
        self.message_sent.emit(message)

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())
