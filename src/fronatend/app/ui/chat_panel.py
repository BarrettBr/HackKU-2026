from __future__ import annotations

import asyncio
import base64
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QKeyEvent,
    QMovie,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import get_settings
from app.services.gif_service import (
    GifSearchResult,
    gif_result_to_attachment,
    search_giphy_gifs,
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


def _attachment_display_name(filename: str) -> str:
    return Path(filename).stem.replace("-", " ").replace("_", " ").title()


def _make_demo_gif_base64(background: str, foreground: str, pattern: str) -> str:
    width = 28
    height = 18
    frames = [
        _pattern_pixels(width, height, pattern, phase=0),
        _pattern_pixels(width, height, pattern, phase=1),
    ]
    gif = _build_two_color_gif(
        width=width,
        height=height,
        background=_hex_to_rgb(background),
        foreground=_hex_to_rgb(foreground),
        frames=frames,
    )
    return base64.b64encode(gif).decode("ascii")


def _pattern_pixels(width: int, height: int, pattern: str, phase: int) -> list[int]:
    center_x = width // 2
    center_y = height // 2
    pixels: list[int] = []
    for y in range(height):
        for x in range(width):
            pixels.append(_pattern_value(x, y, center_x, center_y, pattern, phase))
    return pixels


def _pattern_value(
    x: int,
    y: int,
    center_x: int,
    center_y: int,
    pattern: str,
    phase: int,
) -> int:
    if pattern == "sparkle":
        return int((x + y + phase * 3) % 7 in {0, 1})
    if pattern == "wipe":
        return int((x + phase * 7) % 12 < 5)
    if pattern == "bars":
        return int((y + phase * 3) % 8 < 4)
    if pattern == "diamond":
        return int(abs(x - center_x) + abs(y - center_y) < 7 + phase * 2)
    if pattern == "rings":
        distance = abs(x - center_x) + abs(y - center_y)
        return int(distance % 6 in ({0, 1} if phase == 0 else {2, 3}))
    if pattern == "cross":
        return int(abs(x - center_x) < 3 + phase or abs(y - center_y) < 2 + phase)
    if pattern == "chevron":
        return int((x + y + phase * 4) % 10 < 3 or (x - y + phase * 4) % 10 < 3)
    if pattern == "heart":
        left = (x - center_x + 5) ** 2 + (y - center_y + 3) ** 2 < 24
        right = (x - center_x - 5) ** 2 + (y - center_y + 3) ** 2 < 24
        point = abs(x - center_x) + max(0, y - center_y + 1) < 9 + phase
        return int(left or right or point)
    return int((x + y + phase) % 2 == 0)


def _build_two_color_gif(
    width: int,
    height: int,
    background: tuple[int, int, int],
    foreground: tuple[int, int, int],
    frames: Sequence[list[int]],
) -> bytes:
    data = bytearray()
    data.extend(b"GIF89a")
    data.extend(width.to_bytes(2, "little"))
    data.extend(height.to_bytes(2, "little"))
    data.extend(bytes([0x80, 0, 0]))
    data.extend(bytes(background))
    data.extend(bytes(foreground))
    data.extend(b"!\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00")

    for pixels in frames:
        data.extend(b"!\xf9\x04\x04\x18\x00\x00\x00")
        data.extend(b",\x00\x00\x00\x00")
        data.extend(width.to_bytes(2, "little"))
        data.extend(height.to_bytes(2, "little"))
        data.extend(b"\x00")
        data.extend(_gif_image_data(pixels))

    data.extend(b";")
    return bytes(data)


def _gif_image_data(pixels: Sequence[int]) -> bytes:
    min_code_size = 2
    clear_code = 1 << min_code_size
    end_code = clear_code + 1
    codes: list[int] = [clear_code]
    for pixel in pixels:
        codes.append(pixel)
        codes.append(clear_code)
    codes.append(end_code)

    packed = _pack_lzw_codes(codes, code_size=min_code_size + 1)
    blocks = bytearray([min_code_size])
    for index in range(0, len(packed), 255):
        chunk = packed[index : index + 255]
        blocks.append(len(chunk))
        blocks.extend(chunk)
    blocks.append(0)
    return bytes(blocks)


def _pack_lzw_codes(codes: Sequence[int], code_size: int) -> bytes:
    value = 0
    bit_count = 0
    output = bytearray()
    for code in codes:
        value |= code << bit_count
        bit_count += code_size
        while bit_count >= 8:
            output.append(value & 0xFF)
            value >>= 8
            bit_count -= 8
    if bit_count:
        output.append(value & 0xFF)
    return bytes(output)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    clean_value = value.removeprefix("#")
    return (
        int(clean_value[0:2], 16),
        int(clean_value[2:4], 16),
        int(clean_value[4:6], 16),
    )


GIF_LIBRARY: tuple[ChatAttachment, ...] = tuple(
    ChatAttachment(filename=filename, mime_type="image/gif", data_base64=data_base64)
    for filename, data_base64 in (
        ("popcorn.gif", _make_demo_gif_base64("#230c33", "#ffd166", "sparkle")),
        ("movie-night.gif", _make_demo_gif_base64("#17172c", "#30bced", "wipe")),
        ("standing-ovation.gif", _make_demo_gif_base64("#230c33", "#6bf178", "bars")),
        ("plot-twist.gif", _make_demo_gif_base64("#17172c", "#fc5130", "diamond")),
        ("big-laugh.gif", _make_demo_gif_base64("#230c33", "#e0bad7", "rings")),
        ("mind-blown.gif", _make_demo_gif_base64("#17172c", "#ff9a6c", "cross")),
        ("rewind-that.gif", _make_demo_gif_base64("#230c33", "#8ec7ff", "chevron")),
        ("cinema-love.gif", _make_demo_gif_base64("#17172c", "#f55d59", "heart")),
    )
)


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
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self._gif_buffers: list[QBuffer] = []
        self._gif_movies: list[QMovie] = []
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
        self._reaction_button.setIconSize(QSize(20, 20))
        self._reaction_button.setToolTip("React")
        self._reaction_button.setIcon(QIcon())
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
        self._reaction_button.setIcon(reaction_icon("🔥"))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._reaction_button.setIcon(QIcon())
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

        title_text = (
            _attachment_display_name(attachment.filename)
            if attachment.mime_type == "image/gif"
            else attachment.filename
        )
        title = QLabel(title_text)
        title.setObjectName("attachmentTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)

        file_data = base64.b64decode(attachment.data_base64)
        if attachment.mime_type == "image/gif":
            preview = QLabel()
            preview.setObjectName("attachmentImage")
            buffer = QBuffer(self)
            buffer.setData(QByteArray(file_data))
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            movie = QMovie(buffer, QByteArray(b"gif"), self)
            movie.setScaledSize(QSize(280, 180))
            preview.setMovie(movie)
            layout.addWidget(preview)
            self._gif_buffers.append(buffer)
            self._gif_movies.append(movie)
            movie.start()
        elif attachment.mime_type in {"image/png", "image/jpeg"}:
            pixmap = QPixmap()
            if pixmap.loadFromData(file_data):
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
    gif_sent = Signal(object)

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
        attach_button.clicked.connect(lambda: self._show_attach_menu(attach_button))

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

    def _show_attach_menu(self, button: QPushButton) -> None:
        menu = QMenu(self)
        attach_action = QAction(action_icon("attach"), "Attach file", menu)
        attach_action.triggered.connect(self._choose_file)
        menu.addAction(attach_action)

        gif_action = QAction("GIF library", menu)
        gif_action.triggered.connect(self._show_gif_library)
        menu.addAction(gif_action)

        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _show_gif_library(self) -> None:
        dialog = GifLibraryDialog(self)
        dialog.gif_selected.connect(self.gif_sent.emit)
        dialog.exec()

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


class GifLibraryDialog(QDialog):
    gif_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("GIF Library")
        self.setObjectName("gifLibraryDialog")
        self.setMinimumWidth(380)
        self._online_results: list[GifSearchResult] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Choose a GIF")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        settings = get_settings()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(
            "Search GIPHY GIFs..."
            if settings.giphy_api_key
            else "Search built-in fallback GIFs..."
        )
        self._search_input.returnPressed.connect(self._search_online)
        self._search_input.textChanged.connect(self._refresh_results)
        layout.addWidget(self._search_input)

        self._search_button = QPushButton("Search GIPHY")
        self._search_button.setObjectName("gifChoiceButton")
        self._search_button.setVisible(bool(settings.giphy_api_key))
        self._search_button.clicked.connect(self._search_online)
        layout.addWidget(self._search_button)

        self._status_label = QLabel(
            "Powered by GIPHY"
            if settings.giphy_api_key
            else "Add GIPHY_API_KEY to .env for Discord-style GIF search."
        )
        self._status_label.setObjectName("attachmentTitle")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._results = QVBoxLayout()
        self._results.setSpacing(8)
        layout.addLayout(self._results)
        self._refresh_results()

        if settings.giphy_api_key:
            self._search_input.setText("movie reaction")
            self._search_online()

    def _refresh_results(self) -> None:
        while self._results.count():
            item = self._results.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        query = self._search_input.text().strip().lower()
        if self._online_results:
            for result in self._online_results:
                if query and query not in result.title.lower():
                    continue

                button = QPushButton(result.title)
                button.setObjectName("gifChoiceButton")
                button.clicked.connect(
                    lambda _checked=False, value=result: self._select_online_gif(value)
                )
                self._results.addWidget(button)
            return

        for attachment in GIF_LIBRARY:
            label = _attachment_display_name(attachment.filename)
            if query and query not in label.lower():
                continue

            button = QPushButton(label)
            button.setObjectName("gifChoiceButton")
            button.clicked.connect(
                lambda _checked=False, value=attachment: self._select_gif(value)
            )
            self._results.addWidget(button)

    def _search_online(self) -> None:
        query = self._search_input.text().strip() or "movie reaction"
        self._status_label.setText(f"Searching GIPHY for {query}...")
        self._search_button.setEnabled(False)
        asyncio.create_task(self._search_online_async(query))

    async def _search_online_async(self, query: str) -> None:
        try:
            self._online_results = await search_giphy_gifs(query)
        except Exception as error:
            self._online_results = []
            self._status_label.setText(
                f"GIPHY search failed: {error}. Showing built-in fallback GIFs."
            )
        else:
            count = len(self._online_results)
            self._status_label.setText(f"Powered by GIPHY · {count} results")
        finally:
            self._search_button.setEnabled(True)
            self._refresh_results()

    def _select_online_gif(self, result: GifSearchResult) -> None:
        self._status_label.setText(f"Adding {result.title}...")
        asyncio.create_task(self._select_online_gif_async(result))

    async def _select_online_gif_async(self, result: GifSearchResult) -> None:
        try:
            attachment = await gif_result_to_attachment(result)
        except Exception as error:
            self._status_label.setText(f"Could not add GIF: {error}")
            return

        self._select_gif(attachment)

    def _select_gif(self, attachment: ChatAttachment) -> None:
        self.gif_selected.emit(attachment)
        self.accept()
