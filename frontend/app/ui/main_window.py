from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.services.api_client import ApiClient
from app.services.ws_client import WsClient
from app.state.app_state import AppState
from app.ui.chat_panel import ChatPanel
from app.ui.user_list import UserListDialog


class VideoSurface(QFrame):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(
        self, state: AppState, api_client: ApiClient, ws_client: WsClient
    ) -> None:
        super().__init__()
        self.state = state
        self.api_client = api_client
        self.ws_client = ws_client
        self.chat_open = True
        self.is_paused = False
        self.unread_count = 0
        self._user_list_dialog: UserListDialog | None = None

        self.setWindowTitle("Moovie Night")
        self.setMinimumSize(1260, 800)
        self.setMouseTracking(True)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._clear_status_text)
        self._chrome_timer = QTimer(self)
        self._chrome_timer.setInterval(1800)
        self._chrome_timer.timeout.connect(self._hide_chrome)

        self._build_ui()
        self._apply_styles()
        self._install_mouse_tracking(self.centralWidget())
        self._show_chrome()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        page = QVBoxLayout(root)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)

        shell = QFrame()
        shell.setObjectName("shell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        page.addWidget(shell)

        self._top_bar = self._build_top_bar()
        shell_layout.addWidget(self._top_bar)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("contentSplitter")
        self._splitter.setChildrenCollapsible(False)
        shell_layout.addWidget(self._splitter, 1)

        self._video_surface = self._build_video_surface()
        self._splitter.addWidget(self._video_surface)

        self._chat_panel = ChatPanel()
        self._chat_panel.seed_messages()
        self._chat_panel.message_sent.connect(self._handle_local_message)
        self._chat_panel.reaction_sent.connect(self._send_reaction)
        self._splitter.addWidget(self._chat_panel)
        self._splitter.setSizes([930, 500])

        self._bottom_bar = self._build_bottom_bar()
        shell_layout.addWidget(self._bottom_bar)

    def _build_top_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(32, 18, 32, 18)
        layout.setSpacing(18)

        room_name = QLabel(self.state.room_name)
        room_name.setObjectName("roomName")
        layout.addWidget(room_name)

        live_badge = QLabel("LIVE")
        live_badge.setObjectName("liveBadge")
        layout.addWidget(live_badge)

        layout.addStretch()

        avatars = QFrame()
        avatars.setObjectName("avatarRow")
        avatars_layout = QHBoxLayout(avatars)
        avatars_layout.setContentsMargins(0, 0, 0, 0)
        avatars_layout.setSpacing(-8)

        avatar_colors = ("#6657E5", "#1E9F86", "#C8682B", "#BA4D7F")
        for text, name, color in zip(
            ("U1", "U2", "U3", "U4"), self.state.participants, avatar_colors
        ):
            avatar = QPushButton(text)
            avatar.setObjectName("avatarChip")
            avatar.setToolTip(name)
            avatar.setStyleSheet(f"background: {color}; color: white;")
            avatar.clicked.connect(self._show_participants)
            avatars_layout.addWidget(avatar)

        layout.addWidget(avatars)

        watching = QLabel(f"{len(self.state.participants)} watching")
        watching.setObjectName("watchingLabel")
        layout.addWidget(watching)

        invite_button = QPushButton("Invite")
        invite_button.setObjectName("ghostButton")
        invite_button.clicked.connect(self._show_invite_hint)
        layout.addWidget(invite_button)

        self._toggle_chat_button = QToolButton()
        self._toggle_chat_button.setText("≡")
        self._toggle_chat_button.setObjectName("menuButton")
        self._toggle_chat_button.clicked.connect(self._toggle_chat_panel)
        layout.addWidget(self._toggle_chat_button)

        return frame

    def _build_video_surface(self) -> VideoSurface:
        surface = VideoSurface()
        surface.setObjectName("videoSurface")
        surface.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        surface.clicked.connect(self._toggle_pause)

        layout = QVBoxLayout(surface)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(18)
        layout.addStretch()

        live_stream = QLabel("LIVE STREAM")
        live_stream.setObjectName("streamEyebrow")
        live_stream.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(live_stream)

        title = QLabel("VIDEO STREAM")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setObjectName("videoTitle")
        layout.addWidget(title)

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setObjectName("videoStatus")
        layout.addWidget(self._status_label)
        layout.addStretch()
        return surface

    def _build_bottom_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("bottomBar")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(32, 20, 32, 20)
        layout.setSpacing(16)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)

        movie_title = QLabel(f"{self.state.movie_title} ({self.state.movie_year})")
        movie_title.setObjectName("movieTitle")
        info_col.addWidget(movie_title)

        viewers = QLabel(f"{len(self.state.participants)} viewers")
        viewers.setObjectName("viewerLabel")
        info_col.addWidget(viewers)
        layout.addLayout(info_col)

        layout.addStretch()

        self._pause_button = QPushButton("⏸  Pause")
        self._pause_button.setObjectName("transportButton")
        self._pause_button.clicked.connect(self._toggle_pause)
        layout.addWidget(self._pause_button)

        volume_button = QPushButton("🔊")
        volume_button.setObjectName("iconButton")
        volume_button.setToolTip("Volume")
        layout.addWidget(volume_button)

        leave_button = QPushButton("Leave")
        leave_button.setObjectName("leaveButton")
        leave_button.clicked.connect(self._leave_room)
        layout.addWidget(leave_button)
        return frame

    def _handle_local_message(self, message: str) -> None:
        self._chat_panel.add_message(
            author="You",
            message=message,
            author_color="#E0BAD7",
        )
        if not self.chat_open:
            self.unread_count += 1

    def _send_reaction(self, emoji: str) -> None:
        self._chat_panel.add_reaction_to_latest_message(emoji)
        if not self.chat_open:
            self.unread_count += 1

    def _toggle_pause(self) -> None:
        self.is_paused = not self.is_paused
        self._pause_button.setText("▶  Play" if self.is_paused else "⏸  Pause")
        if self.is_paused:
            self._status_timer.stop()
            self._status_label.setText("Paused")
        else:
            self._status_label.setText("Playing")
            self._status_timer.start()

    def _clear_status_text(self) -> None:
        if not self.is_paused:
            self._status_label.clear()

    def _show_chrome(self) -> None:
        self._top_bar.show()
        self._bottom_bar.show()
        self._chrome_timer.start()

    def _hide_chrome(self) -> None:
        self._top_bar.hide()
        self._bottom_bar.hide()

    def _toggle_chat_panel(self) -> None:
        self.chat_open = not self.chat_open
        self._chat_panel.setVisible(self.chat_open)
        if self.chat_open:
            self._splitter.setSizes([930, 500])
        else:
            self._splitter.setSizes([1440, 0])

    def _show_participants(self) -> None:
        if self._user_list_dialog is None:
            self._user_list_dialog = UserListDialog(self.state.participants)
            self._user_list_dialog.setStyleSheet(self.styleSheet())

        button_pos = self.mapToGlobal(QPoint(self.width() - 360, 78))
        self._user_list_dialog.move(button_pos)
        self._user_list_dialog.show()
        self._user_list_dialog.raise_()
        self._user_list_dialog.activateWindow()

    def _show_invite_hint(self) -> None:
        self.statusBar().showMessage(
            "Invite flow placeholder: copy room code later.", 2500
        )

    def _leave_room(self) -> None:
        self.statusBar().showMessage(
            "Leaving room would end the session for everyone.", 3000
        )

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Space:
            self._toggle_pause()
            return
        super().keyPressEvent(event)

    def _install_mouse_tracking(self, widget: QObject | None) -> None:
        if widget is None:
            return

        widget.installEventFilter(self)
        if isinstance(widget, QWidget):
            widget.setMouseTracking(True)
            for child in widget.findChildren(QWidget):
                child.setMouseTracking(True)
                child.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in {QEvent.Type.MouseMove, QEvent.Type.Enter}:
            self._show_chrome()
        return super().eventFilter(watched, event)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                color: #ffffff;
                font-family: "SF Pro Display", "Helvetica Neue", sans-serif;
                font-size: 14px;
            }
            QMainWindow {
                background: #0b0c13;
            }
            QLabel {
                background: transparent;
            }
            QFrame#shell {
                background: #121224;
                border-radius: 30px;
            }
            QFrame#topBar,
            QFrame#bottomBar,
            QFrame#chatHeader,
            QFrame#chatComposer {
                background: #17172c;
            }
            QFrame#topBar {
                border-top-left-radius: 30px;
                border-top-right-radius: 30px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            }
            QFrame#bottomBar {
                border-top: 1px solid rgba(255, 255, 255, 0.08);
                border-bottom-left-radius: 30px;
                border-bottom-right-radius: 30px;
            }
            QFrame#videoSurface {
                background: #0a0914;
                border-right: 1px solid rgba(255, 255, 255, 0.08);
                border-bottom-left-radius: 0px;
            }
            QFrame#chatPanel {
                background: #17172c;
            }
            QFrame#chatHeader {
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            }
            QFrame#chatComposer {
                border-top: 1px solid rgba(255, 255, 255, 0.08);
            }
            QScrollArea#chatScrollArea,
            QScrollArea#chatScrollArea > QWidget,
            QWidget#chatFeed {
                background: #e0bad7;
            }
            QFrame#chatBubble {
                background: #232339;
                border-radius: 18px;
                border: 1px solid rgba(255, 255, 255, 0.03);
            }
            QLabel#roomName {
                font-size: 24px;
                font-weight: 700;
                color: #ffffff;
            }
            QLabel#liveBadge {
                background: #f55d59;
                color: #ffffff;
                border-radius: 10px;
                padding: 7px 15px;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#watchingLabel,
            QLabel#viewerLabel,
            QLabel#videoStatus {
                color: rgba(255, 255, 255, 0.62);
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#movieTitle {
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#streamEyebrow {
                color: rgba(255, 255, 255, 0.35);
                font-size: 22px;
                font-weight: 600;
                letter-spacing: 0.22em;
            }
            QLabel#videoTitle {
                color: rgba(255, 255, 255, 0.16);
                font-size: 46px;
                font-weight: 800;
                letter-spacing: 0.08em;
            }
            QLabel#chatTitle {
                font-size: 26px;
                font-weight: 800;
                color: #ffffff;
            }
            QLabel#chatAuthor {
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#chatMessage {
                color: rgba(255, 255, 255, 0.82);
                font-size: 17px;
                font-weight: 600;
            }
            QLabel#hostBadge {
                background: rgba(101, 231, 198, 0.14);
                color: #65e7c6;
                border-radius: 8px;
                padding: 4px 10px;
                font-size: 12px;
                font-weight: 700;
            }
            QFrame#reactionPill {
                background: rgba(255, 255, 255, 0.08);
                border-radius: 10px;
            }
            QLabel#reactionEmoji,
            QLabel#reactionCount {
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton,
            QToolButton {
                background: rgba(255, 255, 255, 0.02);
                color: rgba(255, 255, 255, 0.82);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 16px;
                padding: 12px 18px;
                font-size: 15px;
                font-weight: 700;
            }
            QPushButton:hover,
            QToolButton:hover {
                background: rgba(255, 255, 255, 0.08);
            }
            QPushButton#ghostButton {
                min-width: 108px;
            }
            QPushButton#ghostButton,
            QToolButton#menuButton,
            QPushButton#transportButton,
            QPushButton#iconButton,
            QPushButton#leaveButton {
                background: transparent;
                border-color: transparent;
                box-shadow: none;
            }
            QPushButton#ghostButton:hover,
            QToolButton#menuButton:hover,
            QPushButton#transportButton:hover,
            QPushButton#iconButton:hover,
            QPushButton#leaveButton:hover {
                background: rgba(255, 255, 255, 0.04);
                border-color: transparent;
            }
            QPushButton#avatarChip {
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
                border-radius: 21px;
                padding: 0px;
                border: none;
            }
            QPushButton#quickReactionButton {
                min-width: 52px;
                min-height: 52px;
                border-radius: 18px;
                padding: 0px;
                font-size: 24px;
            }
            QPushButton#primaryButton {
                min-width: 120px;
                background: rgba(255, 255, 255, 0.04);
                color: rgba(255, 255, 255, 0.35);
            }
            QPushButton#transportButton {
                min-width: 150px;
                color: rgba(255, 255, 255, 0.42);
            }
            QPushButton#iconButton {
                min-width: 52px;
                min-height: 52px;
                padding: 0px;
                font-size: 22px;
            }
            QPushButton#leaveButton {
                color: #ff8c7c;
                min-width: 110px;
            }
            QToolButton#menuButton {
                min-width: 52px;
                min-height: 52px;
                padding: 0px;
                font-size: 24px;
            }
            QLineEdit {
                background: #e0bad7;
                color: #1a1a1a;
                border: none;
                border-radius: 14px;
                padding: 16px 18px;
                font-size: 18px;
                font-weight: 600;
            }
            QListWidget {
                background: transparent;
                border: none;
            }
            QStatusBar {
                background: #141626;
                color: #e0bad7;
            }
            """
        )
