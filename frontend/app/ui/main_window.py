from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
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
        self.setMinimumSize(1180, 720)
        self.setMouseTracking(True)

        self._controls_timer = QTimer(self)
        self._controls_timer.setInterval(1800)
        self._controls_timer.timeout.connect(self._hide_controls)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._clear_status_text)

        self._build_ui()
        self._apply_styles()
        self._install_mouse_tracking(self.centralWidget())
        self._show_controls()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        page = QVBoxLayout(root)
        page.setContentsMargins(16, 16, 16, 16)
        page.setSpacing(0)

        top_bar = self._build_top_bar()
        page.addWidget(top_bar)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        page.addWidget(self._splitter, 1)

        self._video_surface = self._build_video_surface()
        self._splitter.addWidget(self._video_surface)

        self._chat_panel = ChatPanel()
        self._chat_panel.seed_messages()
        self._chat_panel.message_sent.connect(self._handle_local_message)
        self._splitter.addWidget(self._chat_panel)
        self._splitter.setSizes([980, 360])

    def _build_top_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(12)

        room_name = QLabel(self.state.room_name)
        room_name.setObjectName("roomName")
        layout.addWidget(room_name, 1)

        self._participant_button = QPushButton(f"{len(self.state.participants)} people")
        self._participant_button.setObjectName("ghostButton")
        self._participant_button.clicked.connect(self._show_participants)
        layout.addWidget(self._participant_button)

        invite_button = QPushButton("Invite")
        invite_button.setObjectName("ghostButton")
        invite_button.clicked.connect(self._show_invite_hint)
        layout.addWidget(invite_button)

        self._unread_badge = QLabel("0")
        self._unread_badge.setObjectName("badge")
        self._unread_badge.hide()
        layout.addWidget(self._unread_badge)

        self._toggle_chat_button = QToolButton()
        self._toggle_chat_button.setText("☰")
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
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addStretch()

        title = QLabel("VIDEO\nSTREAM")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setObjectName("videoTitle")
        layout.addWidget(title)

        self._status_label = QLabel("Click anywhere on the video to pause")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setObjectName("videoStatus")
        layout.addWidget(self._status_label)

        layout.addStretch()

        self._controls_bar = self._build_controls_bar()
        layout.addWidget(self._controls_bar)

        opacity = QGraphicsOpacityEffect(self._controls_bar)
        opacity.setOpacity(1.0)
        self._controls_bar.setGraphicsEffect(opacity)
        return surface

    def _build_controls_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("controlsBar")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        self._pause_button = QPushButton("⏸")
        self._pause_button.setObjectName("iconButton")
        self._pause_button.clicked.connect(self._toggle_pause)
        layout.addWidget(self._pause_button)

        volume_button = QPushButton("🔊")
        volume_button.setObjectName("iconButton")
        volume_button.setToolTip("Volume")
        layout.addWidget(volume_button)

        reaction_button = QPushButton("🙂")
        reaction_button.setObjectName("iconButton")
        reaction_button.setToolTip("React")
        reaction_button.setMenu(self._build_reaction_menu(reaction_button))
        layout.addWidget(reaction_button)

        layout.addStretch()

        leave_button = QPushButton("Leave")
        leave_button.setObjectName("leaveButton")
        leave_button.clicked.connect(self._leave_room)
        layout.addWidget(leave_button)
        return frame

    def _build_reaction_menu(self, parent: QWidget) -> QMenu:
        menu = QMenu(parent)
        menu.setObjectName("reactionMenu")
        reactions = ["😀", "😂", "😍", "😮", "😭", "😡", "👏", "🔥"]
        for emoji in reactions:
            action = menu.addAction(emoji)
            action.triggered.connect(
                lambda _checked=False, value=emoji: self._send_reaction(value)
            )
        return menu

    def _handle_local_message(self, message: str) -> None:
        self._chat_panel.add_message(self.state.display_name, message, accent=True)
        if not self.chat_open:
            self.unread_count += 1
            self._refresh_unread_badge()

    def _send_reaction(self, emoji: str) -> None:
        self._chat_panel.add_message(self.state.display_name, f"reacted with {emoji}")
        if not self.chat_open:
            self.unread_count += 1
            self._refresh_unread_badge()

    def _toggle_pause(self) -> None:
        self.is_paused = not self.is_paused
        self._pause_button.setText("▶" if self.is_paused else "⏸")
        if self.is_paused:
            self._status_timer.stop()
            self._status_label.setText("Paused. Click anywhere on the video to resume.")
        else:
            self._status_label.setText(
                "Playing. Move your mouse to reveal room controls."
            )
            self._status_timer.start()

    def _clear_status_text(self) -> None:
        if not self.is_paused:
            self._status_label.clear()

    def _toggle_chat_panel(self) -> None:
        self.chat_open = not self.chat_open
        self._chat_panel.setVisible(self.chat_open)
        if self.chat_open:
            self.unread_count = 0
            self._refresh_unread_badge()
            self._splitter.setSizes([980, 360])
        else:
            self._splitter.setSizes([1340, 0])

    def _show_participants(self) -> None:
        if self._user_list_dialog is None:
            self._user_list_dialog = UserListDialog(self.state.participants)
            self._user_list_dialog.setStyleSheet(self.styleSheet())

        button_pos = self._participant_button.mapToGlobal(
            QPoint(0, self._participant_button.height() + 6)
        )
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

    def _refresh_unread_badge(self) -> None:
        if self.unread_count > 0:
            self._unread_badge.setText(str(self.unread_count))
            self._unread_badge.show()
        else:
            self._unread_badge.hide()

    def _show_controls(self) -> None:
        self._controls_bar.show()
        self._controls_timer.start()

    def _hide_controls(self) -> None:
        self._controls_bar.hide()

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
            self._show_controls()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Space:
            self._toggle_pause()
            return
        super().keyPressEvent(event)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #131820;
                color: #ffffff;
                font-family: "SF Pro Display", "Helvetica Neue", sans-serif;
                font-size: 14px;
            }
            QMainWindow {
                background: #131820;
            }
            QFrame#topBar,
            QFrame#chatPanel,
            QFrame#controlsBar,
            QFrame#chatHeader,
            QFrame#chatComposer {
                background: rgba(24, 20, 31, 0.95);
                border: 1px solid rgba(224, 186, 215, 0.14);
            }
            QFrame#topBar {
                border-top-left-radius: 18px;
                border-top-right-radius: 18px;
                border-bottom: none;
                background: rgba(30, 18, 43, 0.98);
            }
            QFrame#videoSurface {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #20172b, stop: 0.45 #181c25, stop: 1 #121720
                );
                border: 1px solid rgba(224, 186, 215, 0.16);
                border-bottom-left-radius: 18px;
            }
            QFrame#chatPanel {
                border-bottom-right-radius: 18px;
            }
            QFrame#chatHeader {
                border-top: none;
                border-left: none;
                border-right: none;
            }
            QFrame#chatComposer {
                border-left: none;
                border-right: none;
                border-bottom: none;
                border-top: 1px solid rgba(224, 186, 215, 0.18);
            }
            QLabel#roomName {
                font-size: 20px;
                font-weight: 700;
                color: #ffffff;
            }
            QLabel#videoStatus {
                color: #e0bad7;
            }
            QLabel#videoTitle {
                font-size: 54px;
                font-weight: 800;
                line-height: 1.1em;
                color: #ffffff;
                letter-spacing: 0.04em;
            }
            QLabel#chatTitle {
                font-size: 28px;
                font-weight: 800;
                color: #ffffff;
            }
            QLabel#badge {
                min-width: 24px;
                padding: 4px 8px;
                background: #fc5130;
                border-radius: 12px;
                font-weight: 800;
            }
            QLabel#chatAuthor,
            QLabel#sectionTitle {
                font-weight: 700;
                color: #6bf178;
            }
            QFrame#chatBubble,
            QFrame#chatBubbleAccent {
                border-radius: 14px;
                border: 1px solid rgba(224, 186, 215, 0.14);
                background: rgba(255, 255, 255, 0.05);
            }
            QFrame#chatBubbleAccent {
                background: rgba(224, 186, 215, 0.12);
                border: 1px solid rgba(224, 186, 215, 0.3);
            }
            QScrollArea,
            QListWidget,
            QLineEdit {
                background: transparent;
                border: none;
            }
            QLineEdit {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(224, 186, 215, 0.18);
                border-radius: 12px;
                padding: 12px;
                color: #ffffff;
            }
            QPushButton,
            QToolButton {
                border-radius: 12px;
                border: 1px solid rgba(224, 186, 215, 0.16);
                padding: 10px 14px;
                background: rgba(255, 255, 255, 0.05);
                color: #ffffff;
                font-weight: 700;
            }
            QPushButton:hover,
            QToolButton:hover {
                background: rgba(224, 186, 215, 0.12);
            }
            QPushButton#primaryButton {
                background: #6bf178;
                color: #111111;
                border-color: #6bf178;
            }
            QPushButton#primaryButton:hover {
                background: #8af394;
            }
            QPushButton#ghostButton,
            QPushButton#iconButton,
            QToolButton#menuButton {
                min-height: 40px;
            }
            QPushButton#iconButton {
                min-width: 46px;
                padding: 8px 10px;
            }
            QPushButton#leaveButton {
                background: #ff6b4a;
                border-color: #ff6b4a;
            }
            QPushButton#ghostButton {
                border-color: rgba(48, 188, 237, 0.28);
                color: #30bced;
            }
            QToolButton#menuButton {
                border-color: rgba(48, 188, 237, 0.28);
                color: #30bced;
            }
            QListWidget {
                border-radius: 12px;
                padding: 6px;
                background: rgba(255, 255, 255, 0.04);
            }
            QMenu#reactionMenu {
                background: #1c2029;
                border: 1px solid rgba(224, 186, 215, 0.18);
                padding: 8px;
            }
            QMenu#reactionMenu::item {
                padding: 8px 16px;
                border-radius: 8px;
                margin: 2px 0px;
            }
            QMenu#reactionMenu::item:selected {
                background: rgba(48, 188, 237, 0.18);
            }
            QStatusBar {
                background: #161d27;
                color: #e0bad7;
            }
            """
        )
