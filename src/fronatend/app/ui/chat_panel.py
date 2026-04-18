from __future__ import annotations

import base64
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QKeyEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.room_service import ChatAttachment


REACTION_ICON_DIR = Path(__file__).resolve().parents[1] / "assets" / "reactions"
ACTION_ICON_DIR = Path(__file__).resolve().parents[1] / "assets" / "actions"

REACTION_CHOICES: tuple[tuple[str, str, str], ...] = (
    ("🔥", "Fire", "fire.svg"),
    ("👏", "Clap", "clap.svg"),
    ("😂", "Laugh", "laugh.svg"),
    ("😮", "Wow", "wow.svg"),
    ("♥", "Love", "love.svg"),
)


REACTION_LABELS = {reaction: label for reaction, label, _icon in REACTION_CHOICES}
REACTION_ICONS = {
    reaction: REACTION_ICON_DIR / icon for reaction, _label, icon in REACTION_CHOICES
}


def reaction_icon(reaction: str) -> QIcon:
    icon_path = REACTION_ICONS.get(reaction)
    if icon_path is None:
        return QIcon()
    return QIcon(str(icon_path))


def action_icon(name: str) -> QIcon:
    return QIcon(str(ACTION_ICON_DIR / f"{name}.svg"))


class ReactionPill(QFrame):
    def __init__(self, reaction: str, count: int) -> None:
        super().__init__()
        self.setObjectName("reactionPill")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(8)

        icon_label = QLabel()
        icon_label.setObjectName("reactionIcon")
        icon_label.setToolTip(REACTION_LABELS.get(reaction, reaction))
        icon_label.setPixmap(reaction_icon(reaction).pixmap(QSize(20, 20)))
        self._count_label = QLabel(str(count))
        self._count_label.setObjectName("reactionCount")

        layout.addWidget(icon_label)
        layout.addWidget(self._count_label)

    def set_count(self, count: int) -> None:
        self._count_label.setText(str(count))

    def count(self) -> int:
        return int(self._count_label.text())


class ComposerInput(QTextEdit):
    submitted = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("messageInput")
        self.setPlaceholderText("Type a message...")
        self.setAcceptRichText(False)
        self.setMinimumHeight(46)
        self.setMaximumHeight(118)
        self.textChanged.connect(self._fit_to_text)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.submitted.emit()
            return
        super().keyPressEvent(event)

    def _fit_to_text(self) -> None:
        doc_height = int(self.document().size().height()) + 20
        self.setFixedHeight(min(max(46, doc_height), 118))


class ChatBubble(QFrame):
    clicked = Signal(int)
    reaction_requested = Signal(int, str)

    def __init__(
        self,
        message_id: int,
        author: str,
        message: str,
        author_color: str,
        is_host: bool = False,
        attachment: ChatAttachment | None = None,
        reactions: Sequence[tuple[str, int]] | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("chatBubble")
        self.message_id = message_id
        self._reaction_pills: dict[str, ReactionPill] = {}
        self._reactions_row: QHBoxLayout | None = None
        self._selected = False
        self._author_color = author_color

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

        self._reaction_button = QPushButton()
        self._reaction_button.setObjectName("bubbleReactionButton")
        self._reaction_button.setIcon(reaction_icon("🔥"))
        self._reaction_button.setIconSize(QSize(20, 20))
        self._reaction_button.setToolTip("React")
        self._reaction_button.hide()
        self._reaction_button.clicked.connect(self._show_reaction_menu)

        header.addStretch()
        header.addWidget(self._reaction_button)
        self._layout.addLayout(header)
        self._apply_border()

        message_label = QLabel(message)
        message_label.setObjectName("chatMessage")
        message_label.setWordWrap(True)
        message_label.setTextFormat(Qt.TextFormat.PlainText)
        self._layout.addWidget(message_label)

        if attachment is not None:
            self._layout.addWidget(self._build_attachment_preview(attachment))

        if reactions:
            self.set_reactions(dict(reactions))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.message_id)
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._reaction_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._reaction_button.hide()
        super().leaveEvent(event)

    def _show_reaction_menu(self) -> None:
        self.clicked.emit(self.message_id)
        menu = QMenu(self)
        for reaction, label, _icon in REACTION_CHOICES:
            action = QAction(reaction_icon(reaction), label, menu)
            action.triggered.connect(
                lambda _checked=False, value=reaction: self.reaction_requested.emit(
                    self.message_id,
                    value,
                )
            )
            menu.addAction(action)
        menu.exec(
            self._reaction_button.mapToGlobal(self._reaction_button.rect().bottomLeft())
        )

    def _build_attachment_preview(self, attachment: ChatAttachment) -> QWidget:
        container = QFrame()
        container.setObjectName("attachmentPreview")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title = QLabel(attachment.filename)
        title.setObjectName("attachmentTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)

        if attachment.mime_type in {"image/png", "image/jpeg"}:
            pixmap = QPixmap()
            if pixmap.loadFromData(base64.b64decode(attachment.data_base64)):
                preview = QLabel()
                preview.setObjectName("attachmentImage")
                preview.setPixmap(
                    pixmap.scaledToWidth(
                        280,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                layout.addWidget(preview)

        download_button = QPushButton("Download")
        download_button.setObjectName("downloadButton")
        download_button.clicked.connect(lambda: self._download_attachment(attachment))
        layout.addWidget(download_button, 0, Qt.AlignmentFlag.AlignLeft)
        return container

    def _download_attachment(self, attachment: ChatAttachment) -> None:
        suggested_path = str(Path.home() / "Downloads" / attachment.filename)
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save attachment",
            suggested_path,
            "All files (*)",
        )
        if not file_path:
            return

        Path(file_path).write_bytes(base64.b64decode(attachment.data_base64))

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setProperty("selected", selected)
        self._apply_border()

    def _apply_border(self) -> None:
        border_width = 2 if self._selected else 1
        self.setStyleSheet(
            f"QFrame#chatBubble {{ border: {border_width}px solid {self._author_color}; }}"
        )

    def set_reactions(self, reactions: dict[str, int]) -> None:
        if self._reactions_row is None and reactions:
            self._reactions_row = QHBoxLayout()
            self._reactions_row.setSpacing(8)
            self._reactions_row.setContentsMargins(0, 0, 0, 0)
            self._layout.addLayout(self._reactions_row)
            self._reactions_row.addStretch()

        for reaction in list(self._reaction_pills):
            if reaction in reactions:
                continue
            pill = self._reaction_pills.pop(reaction)
            if self._reactions_row is not None:
                self._reactions_row.removeWidget(pill)
            pill.deleteLater()

        if self._reactions_row is None:
            return

        for reaction, count in reactions.items():
            existing_pill = self._reaction_pills.get(reaction)
            if existing_pill is None:
                new_pill = ReactionPill(reaction, count)
                self._reaction_pills[reaction] = new_pill
                self._reactions_row.insertWidget(
                    self._reactions_row.count() - 1,
                    new_pill,
                )
                continue
            existing_pill.set_count(count)

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
    reaction_sent = Signal(int, str)
    file_sent = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("chatPanel")
        self.setMinimumWidth(260)
        self.setMaximumWidth(680)
        self.setAcceptDrops(True)
        self._message_cards: list[ChatBubble] = []
        self._message_cards_by_id: dict[int, ChatBubble] = {}
        self._selected_message_id: int | None = None

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

        self._message_input = ComposerInput()
        self._message_input.submitted.connect(self._send_message)
        self._message_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        attach_button = QPushButton()
        attach_button.setObjectName("ghostSmallButton")
        attach_button.setToolTip("Attach file")
        attach_button.setIcon(action_icon("attach"))
        attach_button.setIconSize(QSize(18, 18))
        attach_button.clicked.connect(self._choose_file)

        send_button = QPushButton()
        send_button.setObjectName("primaryButton")
        send_button.setToolTip("Send")
        send_button.setIcon(action_icon("send"))
        send_button.setIconSize(QSize(18, 18))
        send_button.clicked.connect(self._send_message)

        composer_layout.addWidget(self._message_input, 1)
        composer_layout.addWidget(attach_button)
        composer_layout.addWidget(send_button)
        layout.addWidget(composer)

    def seed_messages(self) -> None:
        self.add_message(
            message_id=-1,
            author="User1",
            message="Hello everyone!",
            author_color="#65E7C6",
            is_host=True,
        )
        self.add_message(
            message_id=-2,
            author="User2",
            message="Hi there!",
            author_color="#C9BEFF",
        )
        self.add_message(
            message_id=-3,
            author="User1",
            message="Ready to watch!",
            author_color="#65E7C6",
            is_host=True,
            reactions=[("🔥", 3), ("👏", 1)],
        )
        self.add_message(
            message_id=-4,
            author="User4",
            message="Let's do this!",
            author_color="#FF9A6C",
            reactions=[("😂", 2)],
        )
        self.add_message(
            message_id=-5,
            author="User3",
            message="Glad we picked this one",
            author_color="#8EC7FF",
        )
        self.add_message(
            message_id=-6,
            author="User2",
            message="This scene is so good omg",
            author_color="#C9BEFF",
            reactions=[("😮", 4)],
        )

    def add_message(
        self,
        message_id: int,
        author: str,
        message: str,
        author_color: str = "#E0BAD7",
        is_host: bool = False,
        attachment: ChatAttachment | None = None,
        reactions: Sequence[tuple[str, int]] | None = None,
    ) -> None:
        existing = self._message_cards_by_id.get(message_id)
        if existing is not None:
            existing.set_reactions(dict(reactions or ()))
            return

        bubble = ChatBubble(
            message_id=message_id,
            author=author,
            message=message,
            author_color=author_color,
            is_host=is_host,
            attachment=attachment,
            reactions=reactions,
        )
        bubble.clicked.connect(self.select_message)
        bubble.reaction_requested.connect(self.reaction_sent.emit)
        self._message_cards.append(bubble)
        self._message_cards_by_id[message_id] = bubble
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, bubble)
        if self._selected_message_id is None:
            self.select_message(message_id)
        self._scroll_to_bottom()

    def select_message(self, message_id: int) -> None:
        self._selected_message_id = message_id
        for bubble in self._message_cards:
            bubble.set_selected(bubble.message_id == message_id)

    def _send_reaction(self, reaction: str) -> None:
        if self._selected_message_id is None:
            return
        self.reaction_sent.emit(self._selected_message_id, reaction)

    def clear_messages(self) -> None:
        while self._messages_layout.count() > 1:
            item = self._messages_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._message_cards.clear()
        self._message_cards_by_id.clear()
        self._selected_message_id = None

    def _send_message(self) -> None:
        message = self._message_input.toPlainText().strip()
        if not message:
            return

        self._message_input.clear()
        self.message_sent.emit(message)

    def _choose_file(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Attach a file",
            "",
            "All files (*);;Images (*.png *.jpg *.jpeg)",
        )
        if file_path:
            self.file_sent.emit(file_path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.file_sent.emit(url.toLocalFile())
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())
