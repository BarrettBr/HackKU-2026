from __future__ import annotations

from collections.abc import Sequence

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


class ReactionPill(QFrame):
    def __init__(self, emoji: str, count: int) -> None:
        super().__init__()
        self.setObjectName("reactionPill")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(8)

        emoji_label = QLabel(emoji)
        emoji_label.setObjectName("reactionEmoji")
        self._count_label = QLabel(str(count))
        self._count_label.setObjectName("reactionCount")

        layout.addWidget(emoji_label)
        layout.addWidget(self._count_label)

    def set_count(self, count: int) -> None:
        self._count_label.setText(str(count))

    def count(self) -> int:
        return int(self._count_label.text())


class ChatBubble(QFrame):
    def __init__(
        self,
        author: str,
        message: str,
        author_color: str,
        is_host: bool = False,
        reactions: Sequence[tuple[str, int]] | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("chatBubble")
        self._reaction_pills: dict[str, ReactionPill] = {}
        self._reactions_row: QHBoxLayout | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(20, 16, 20, 16)
        self._layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)

        author_label = QLabel(author)
        author_label.setObjectName("chatAuthor")
        author_label.setStyleSheet(f"color: {author_color};")
        header.addWidget(author_label)

        if is_host:
            host_badge = QLabel("host")
            host_badge.setObjectName("hostBadge")
            header.addWidget(host_badge)

        header.addStretch()
        self._layout.addLayout(header)

        message_label = QLabel(message)
        message_label.setObjectName("chatMessage")
        message_label.setWordWrap(True)
        message_label.setTextFormat(Qt.TextFormat.PlainText)
        self._layout.addWidget(message_label)

        if reactions:
            for emoji, count in reactions:
                self.add_reaction(emoji, count)

    def add_reaction(self, emoji: str, increment: int = 1) -> None:
        if self._reactions_row is None:
            self._reactions_row = QHBoxLayout()
            self._reactions_row.setSpacing(8)
            self._reactions_row.setContentsMargins(0, 0, 0, 0)
            self._layout.addLayout(self._reactions_row)
            self._reactions_row.addStretch()

        pill = self._reaction_pills.get(emoji)
        if pill is None:
            pill = ReactionPill(emoji, increment)
            self._reaction_pills[emoji] = pill
            self._reactions_row.insertWidget(self._reactions_row.count() - 1, pill)
            return

        pill.set_count(pill.count() + increment)


class ChatPanel(QFrame):
    message_sent = Signal(str)
    reaction_sent = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("chatPanel")
        self.setMinimumWidth(430)
        self.setMaximumWidth(540)
        self._message_cards: list[ChatBubble] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("chatHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 22, 24, 18)
        header_layout.setSpacing(14)

        title = QLabel("Chat")
        title.setObjectName("chatTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()

        for emoji in ("🔥", "👋", "😂", "😮"):
            button = QPushButton(emoji)
            button.setObjectName("quickReactionButton")
            button.clicked.connect(
                lambda _checked=False, value=emoji: self.reaction_sent.emit(value)
            )
            header_layout.addWidget(button)

        layout.addWidget(header)

        self._scroll_area = QScrollArea()
        self._scroll_area.setObjectName("chatScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self._messages_root = QWidget()
        self._messages_root.setObjectName("chatFeed")
        self._messages_layout = QVBoxLayout(self._messages_root)
        self._messages_layout.setContentsMargins(24, 20, 24, 20)
        self._messages_layout.setSpacing(14)
        self._messages_layout.addStretch()
        self._scroll_area.setWidget(self._messages_root)

        layout.addWidget(self._scroll_area, 1)

        composer = QFrame()
        composer.setObjectName("chatComposer")
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(24, 18, 24, 18)
        composer_layout.setSpacing(12)

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
        self.add_message(
            author="User1",
            message="Hello everyone!",
            author_color="#65E7C6",
            is_host=True,
        )
        self.add_message(author="User2", message="Hi there!", author_color="#C9BEFF")
        self.add_message(
            author="User1",
            message="Ready to watch!",
            author_color="#65E7C6",
            is_host=True,
            reactions=[("🔥", 3), ("👋", 1)],
        )
        self.add_message(
            author="User4",
            message="Let's do this!",
            author_color="#FF9A6C",
            reactions=[("😂", 2)],
        )
        self.add_message(
            author="User3",
            message="Glad we picked this one",
            author_color="#8EC7FF",
        )
        self.add_message(
            author="User2",
            message="This scene is so good omg",
            author_color="#C9BEFF",
            reactions=[("😮", 4)],
        )

    def add_message(
        self,
        author: str,
        message: str,
        author_color: str = "#E0BAD7",
        is_host: bool = False,
        reactions: Sequence[tuple[str, int]] | None = None,
    ) -> None:
        bubble = ChatBubble(
            author=author,
            message=message,
            author_color=author_color,
            is_host=is_host,
            reactions=reactions,
        )
        self._message_cards.append(bubble)
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, bubble)
        self._scroll_to_bottom()

    def add_reaction_to_latest_message(self, emoji: str) -> None:
        if not self._message_cards:
            return
        self._message_cards[-1].add_reaction(emoji)
        self._scroll_to_bottom()

    def clear_messages(self) -> None:
        while self._messages_layout.count() > 1:
            item = self._messages_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._message_cards.clear()

    def _send_message(self) -> None:
        message = self._message_input.text().strip()
        if not message:
            return

        self._message_input.clear()
        self.message_sent.emit(message)

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())
