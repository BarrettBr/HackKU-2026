from __future__ import annotations

import asyncio
import hashlib

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.services.api_client import ApiClient
from app.services.room_service import (
    ChatMessage,
    JoinTarget,
    RoomClient,
    RoomHostService,
    RoomInfo,
    parse_join_target,
)
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
        self._user_list_dialog: UserListDialog | None = None
        self._room_host = RoomHostService(display_name=self.state.display_name)
        self._room_client = RoomClient(display_name=self.state.display_name)
        self._room_target: JoinTarget | None = None
        self._last_message_id = 0
        self._author_colors: dict[str, str] = {}
        self._author_avatars: dict[str, str] = {}
        self._participant_buttons: list[QPushButton] = []
        self._palette = (
            "#65E7C6",
            "#C9BEFF",
            "#FF9A6C",
            "#8EC7FF",
            "#E0BAD7",
            "#30BCED",
            "#6BF178",
            "#FC5130",
        )
        self._avatar_choices = ("🦊", "🐸", "🐧", "🦝", "🐙", "🦉", "🐯", "🐳")

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
        self._room_poll_timer = QTimer(self)
        self._room_poll_timer.setInterval(900)
        self._room_poll_timer.timeout.connect(self._poll_room)

        self._build_ui()
        self._apply_styles()
        self._install_mouse_tracking(self.centralWidget())
        self._show_landing()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        page = QVBoxLayout(root)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)

        self._stack = QStackedWidget()
        page.addWidget(self._stack)

        self._landing_page = self._build_landing_page()
        self._stack.addWidget(self._landing_page)

        self._room_shell = self._build_room_shell()
        self._stack.addWidget(self._room_shell)

    def _build_landing_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("landingPage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(80, 80, 80, 80)
        layout.setSpacing(24)
        layout.addStretch()

        card = QFrame()
        card.setObjectName("landingCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 36, 36, 36)
        card_layout.setSpacing(18)

        eyebrow = QLabel("Moovie Night")
        eyebrow.setObjectName("landingEyebrow")
        card_layout.addWidget(eyebrow)

        title = QLabel("Watch together from one room.")
        title.setObjectName("landingTitle")
        title.setWordWrap(True)
        card_layout.addWidget(title)

        subtitle = QLabel(
            "Create a room to host a stream, or join with a P2P invite link."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("landingSubtitle")
        card_layout.addWidget(subtitle)

        self._landing_flow = QStackedWidget()

        chooser = QWidget()
        chooser_layout = QVBoxLayout(chooser)
        chooser_layout.setContentsMargins(0, 0, 0, 0)
        chooser_layout.setSpacing(12)

        create_button = QPushButton("Create Room")
        create_button.setObjectName("landingPrimaryButton")
        create_button.clicked.connect(self._show_create_flow)

        join_button = QPushButton("Join Room")
        join_button.setObjectName("landingSecondaryButton")
        join_button.clicked.connect(self._show_join_flow)

        chooser_layout.addWidget(create_button)
        chooser_layout.addWidget(join_button)
        self._landing_flow.addWidget(chooser)

        create_form = QWidget()
        create_layout = QVBoxLayout(create_form)
        create_layout.setContentsMargins(0, 0, 0, 0)
        create_layout.setSpacing(12)

        self._room_name_input = QLineEdit()
        self._room_name_input.setObjectName("roomNameInput")
        self._room_name_input.setPlaceholderText("Choose a room name")
        self._room_name_input.returnPressed.connect(self._create_room)
        create_layout.addWidget(self._room_name_input)

        create_actions = QHBoxLayout()
        create_actions.setSpacing(12)

        start_button = QPushButton("Start Streaming")
        start_button.setObjectName("landingPrimaryButton")
        start_button.clicked.connect(self._create_room)

        back_from_create = QPushButton("Back")
        back_from_create.setObjectName("landingSecondaryButton")
        back_from_create.clicked.connect(self._show_landing_options)

        create_actions.addWidget(start_button)
        create_actions.addWidget(back_from_create)
        create_layout.addLayout(create_actions)
        self._landing_flow.addWidget(create_form)

        join_form = QWidget()
        join_layout = QVBoxLayout(join_form)
        join_layout.setContentsMargins(0, 0, 0, 0)
        join_layout.setSpacing(12)

        self._room_id_input = QLineEdit()
        self._room_id_input.setObjectName("roomIdInput")
        self._room_id_input.setPlaceholderText("Paste invite link or ROOM@host:port")
        self._room_id_input.returnPressed.connect(self._join_room)
        join_layout.addWidget(self._room_id_input)

        join_actions = QHBoxLayout()
        join_actions.setSpacing(12)

        enter_button = QPushButton("Enter Room")
        enter_button.setObjectName("landingPrimaryButton")
        enter_button.clicked.connect(self._join_room)

        back_from_join = QPushButton("Back")
        back_from_join.setObjectName("landingSecondaryButton")
        back_from_join.clicked.connect(self._show_landing_options)

        join_actions.addWidget(enter_button)
        join_actions.addWidget(back_from_join)
        join_layout.addLayout(join_actions)
        self._landing_flow.addWidget(join_form)

        self._landing_status = QLabel("No room connection yet.")
        self._landing_status.setObjectName("landingStatus")
        self._landing_status.setWordWrap(True)
        card_layout.addWidget(self._landing_status)

        card_layout.addWidget(self._landing_flow)

        layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        return page

    def _build_room_shell(self) -> QWidget:
        shell = QFrame()
        shell.setObjectName("shell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self._top_bar = self._build_top_bar()
        shell_layout.addWidget(self._top_bar)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
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
        return shell

    def _build_top_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(32, 18, 32, 18)
        layout.setSpacing(18)

        self._room_name_label = QLabel(self.state.room_name)
        self._room_name_label.setObjectName("roomName")
        layout.addWidget(self._room_name_label)

        live_badge = QLabel("LIVE")
        live_badge.setObjectName("liveBadge")
        layout.addWidget(live_badge)

        layout.addStretch()

        avatars = QFrame()
        avatars.setObjectName("avatarRow")
        self._avatars_layout = QHBoxLayout(avatars)
        self._avatars_layout.setContentsMargins(0, 0, 0, 0)
        self._avatars_layout.setSpacing(-8)

        layout.addWidget(avatars)

        self._watching_label = QLabel(f"{len(self.state.participants)} watching")
        self._watching_label.setObjectName("watchingLabel")
        layout.addWidget(self._watching_label)

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

        self._movie_title_label = QLabel(
            f"{self.state.movie_title} ({self.state.movie_year})"
        )
        self._movie_title_label.setObjectName("movieTitle")
        info_col.addWidget(self._movie_title_label)

        self._viewer_label = QLabel(f"{len(self.state.participants)} viewers")
        self._viewer_label.setObjectName("viewerLabel")
        info_col.addWidget(self._viewer_label)

        self._connection_label = QLabel(self.state.connection_status)
        self._connection_label.setObjectName("connectionLabel")
        info_col.addWidget(self._connection_label)
        layout.addLayout(info_col)

        self._invite_link_field = QLineEdit()
        self._invite_link_field.setObjectName("inviteLinkField")
        self._invite_link_field.setReadOnly(True)
        self._invite_link_field.setPlaceholderText("Invite link appears here for hosts")
        layout.addWidget(self._invite_link_field)

        layout.addStretch()

        self._pause_button = QPushButton("⏸  Pause")
        self._pause_button.setObjectName("transportButton")
        self._pause_button.clicked.connect(self._toggle_pause)
        layout.addWidget(self._pause_button)

        self._volume_button = QPushButton("🔊")
        self._volume_button.setObjectName("iconButton")
        self._volume_button.clicked.connect(self._toggle_volume_controls)
        layout.addWidget(self._volume_button)

        self._volume_controls = QFrame()
        self._volume_controls.setObjectName("volumeControls")
        volume_layout = QHBoxLayout(self._volume_controls)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.setSpacing(10)

        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setObjectName("volumeSlider")
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(70)
        volume_layout.addWidget(self._volume_slider)

        self._volume_label = QLabel("70%")
        self._volume_label.setObjectName("volumeLabel")
        self._volume_slider.valueChanged.connect(
            lambda value: self._volume_label.setText(f"{value}%")
        )
        volume_layout.addWidget(self._volume_label)
        self._volume_controls.hide()
        layout.addWidget(self._volume_controls)

        leave_button = QPushButton("Leave")
        leave_button.setObjectName("leaveButton")
        leave_button.clicked.connect(self._leave_room)
        layout.addWidget(leave_button)
        return frame

    def _show_landing(self) -> None:
        self._stack.setCurrentWidget(self._landing_page)
        self._chrome_timer.stop()
        self._show_landing_options()

    def _show_room(self) -> None:
        self._stack.setCurrentWidget(self._room_shell)
        self._show_chrome()
        self._volume_controls.hide()
        self._room_poll_timer.start()

    def _show_landing_options(self) -> None:
        self._landing_flow.setCurrentIndex(0)

    def _show_create_flow(self) -> None:
        self._landing_flow.setCurrentIndex(1)
        self._landing_status.setText("Name the room, then start the host listener.")
        self._room_name_input.setFocus()

    def _show_join_flow(self) -> None:
        self._landing_flow.setCurrentIndex(2)
        self._landing_status.setText("Paste a P2P invite link from the host.")
        self._room_id_input.setFocus()

    def _create_room(self) -> None:
        asyncio.create_task(self._create_room_async())

    def _join_room(self) -> None:
        asyncio.create_task(self._join_room_async())

    async def _create_room_async(self) -> None:
        room_name = self._room_name_input.text().strip() or "Friday Movie Room"
        self._landing_status.setText("Creating room and opening P2P join listener...")
        try:
            room = await self._room_host.start_room(room_name)
        except OSError as error:
            self._landing_status.setText(f"Could not start room: {error}")
            return

        self._apply_room_info(room=room, is_host=True)
        self._room_target = parse_join_target(room.invite_link)
        self._landing_status.setText(
            f"Room created. Share this code: {room.compact_code}"
        )
        self._show_room()

    async def _join_room_async(self) -> None:
        invite = self._room_id_input.text().strip()
        self._landing_status.setText("Connecting to host...")
        try:
            target = parse_join_target(invite)
            room = await self._room_client.join(invite)
        except Exception as error:
            self._landing_status.setText(f"Could not join room: {error}")
            return

        self._apply_room_info(room=room, is_host=False)
        self._room_target = target
        self._landing_status.setText(f"Connected to {room.room_name}.")
        self._show_room()

    def _apply_room_info(self, room: RoomInfo, is_host: bool) -> None:
        self.state.room_id = room.room_id
        self.state.room_name = room.room_name
        self.state.invite_link = room.invite_link
        self.state.compact_room_code = room.compact_code
        self.state.is_host = is_host
        self.state.connection_status = (
            f"Hosting {room.compact_code}" if is_host else f"Joined {room.room_id}"
        )
        self.state.participants = room.participants

        self._room_name_label.setText(room.room_name)
        self._connection_label.setText(self.state.connection_status)
        self._invite_link_field.setText(
            room.invite_link if is_host else room.compact_code
        )
        self._last_message_id = 0
        self._chat_panel.clear_messages()
        self._refresh_participants(room.participants)

    def _refresh_participants(self, participants: list[str]) -> None:
        self.state.participants = participants
        self._watching_label.setText(f"{len(participants)} watching")
        self._viewer_label.setText(f"{len(participants)} viewers")

        while self._avatars_layout.count():
            item = self._avatars_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._participant_buttons.clear()
        for participant in participants[:6]:
            avatar = QPushButton(self._avatar_for_participant(participant))
            avatar.setObjectName("avatarChip")
            avatar.setToolTip(participant)
            avatar.setStyleSheet(
                f"background: {self._color_for_author(participant)}; color: white;"
            )
            avatar.clicked.connect(self._show_participants)
            self._avatars_layout.addWidget(avatar)
            self._participant_buttons.append(avatar)

    def _toggle_volume_controls(self) -> None:
        self._volume_controls.setVisible(not self._volume_controls.isVisible())

    def _handle_local_message(self, message: str) -> None:
        if self._room_target is None:
            self.statusBar().showMessage("Join or create a room before chatting.", 2500)
            return
        asyncio.create_task(self._send_chat_message_async(self._room_target, message))

    def _send_reaction(self, emoji: str) -> None:
        self._chat_panel.add_reaction_to_latest_message(emoji)

    async def _send_chat_message_async(self, target: JoinTarget, message: str) -> None:
        try:
            chat_message = await self._room_client.send_message(target, message)
        except Exception as error:
            self.statusBar().showMessage(f"Message failed: {error}", 3000)
            return
        self._append_chat_message(chat_message)

    def _poll_room(self) -> None:
        if self._stack.currentWidget() is not self._room_shell:
            return
        if self._room_target is None:
            return
        asyncio.create_task(self._poll_room_async(self._room_target))

    async def _poll_room_async(self, target: JoinTarget) -> None:
        try:
            room, messages = await self._room_client.fetch_messages(
                target=target,
                after=self._last_message_id,
            )
        except Exception:
            if not self.state.is_host:
                self._room_poll_timer.stop()
                self._show_landing()
                self._landing_status.setText("The host ended the room.")
            return

        self._refresh_participants(room.participants)
        for message in messages:
            self._append_chat_message(message)

    def _append_chat_message(self, message: ChatMessage) -> None:
        if message.id <= self._last_message_id:
            return
        self._last_message_id = message.id
        self._chat_panel.add_message(
            author=message.author,
            message=message.text,
            author_color=self._color_for_author(message.author),
            is_host=message.author == self._host_name(),
        )

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
        if self._stack.currentWidget() is not self._room_shell:
            return
        self._top_bar.show()
        self._bottom_bar.show()
        self._chrome_timer.start()

    def _hide_chrome(self) -> None:
        if self._stack.currentWidget() is not self._room_shell:
            return
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
        self._user_list_dialog = UserListDialog(self.state.participants)
        self._user_list_dialog.setStyleSheet(self.styleSheet())
        button_pos = self.mapToGlobal(QPoint(self.width() - 360, 78))
        self._user_list_dialog.move(button_pos)
        self._user_list_dialog.show()
        self._user_list_dialog.raise_()
        self._user_list_dialog.activateWindow()

    def _show_invite_hint(self) -> None:
        if not self.state.invite_link:
            self.statusBar().showMessage("Create a room before inviting people.", 2500)
            return

        self._invite_link_field.setFocus()
        self._invite_link_field.selectAll()
        self.statusBar().showMessage(
            f"Invite link selected. Code: {self.state.compact_room_code}", 5000
        )

    def _leave_room(self) -> None:
        if self.state.is_host:
            asyncio.create_task(self._room_host.stop())
        elif self._room_target is not None:
            asyncio.create_task(self._leave_room_async(self._room_target))
        self._room_poll_timer.stop()
        self._room_target = None
        self._show_landing()
        self.statusBar().showMessage("Left the room.", 2000)

    async def _leave_room_async(self, target: JoinTarget) -> None:
        try:
            await self._room_client.leave(target)
        except Exception:
            # Leaving should never trap someone in the local UI.
            pass

    def _host_name(self) -> str:
        return self.state.participants[0] if self.state.participants else ""

    def _color_for_author(self, author: str) -> str:
        color = self._author_colors.get(author)
        if color is not None:
            return color

        color = self._palette[len(self._author_colors) % len(self._palette)]
        self._author_colors[author] = color
        return color

    def _avatar_for_participant(self, participant: str) -> str:
        avatar = self._author_avatars.get(participant)
        if avatar is not None:
            return avatar

        digest = hashlib.sha256(participant.encode("utf-8")).digest()
        avatar = self._avatar_choices[digest[0] % len(self._avatar_choices)]
        self._author_avatars[participant] = avatar
        return avatar

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

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if (
            event.key() == Qt.Key.Key_Space
            and self._stack.currentWidget() is self._room_shell
        ):
            self._toggle_pause()
            return
        super().keyPressEvent(event)

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
            QWidget#landingPage {
                background: #0b0c13;
            }
            QFrame#landingCard {
                background: #17172c;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 28px;
                min-width: 620px;
                max-width: 620px;
            }
            QLabel#landingEyebrow {
                color: #e0bad7;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#landingTitle {
                font-size: 34px;
                font-weight: 800;
                min-height: 96px;
            }
            QLabel#landingSubtitle {
                color: rgba(255, 255, 255, 0.72);
                font-size: 16px;
            }
            QLabel#landingStatus {
                color: #e0bad7;
                font-size: 14px;
                font-weight: 600;
                min-height: 36px;
            }
            QLineEdit#roomIdInput,
            QLineEdit#roomNameInput {
                background: #232339;
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 14px;
                padding: 16px 18px;
                font-size: 16px;
                font-weight: 600;
                min-height: 26px;
            }
            QPushButton#landingPrimaryButton {
                background: #f55d59;
                color: #ffffff;
                border: none;
                border-radius: 14px;
                padding: 14px 18px;
                font-weight: 700;
                min-height: 24px;
            }
            QPushButton#landingSecondaryButton {
                background: transparent;
                color: #e0bad7;
                border: 1px solid rgba(224, 186, 215, 0.3);
                border-radius: 14px;
                padding: 14px 18px;
                font-weight: 700;
                min-height: 24px;
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
            QDialog#participantDialog {
                background: #17172c;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
            }
            QListWidget#participantList {
                background: #232339;
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 8px;
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
            QLabel#videoStatus,
            QLabel#volumeLabel,
            QLabel#connectionLabel {
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
            QPushButton#leaveButton {
                background: transparent;
                border-color: transparent;
            }
            QPushButton#ghostButton:hover,
            QToolButton#menuButton:hover,
            QPushButton#transportButton:hover,
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
            QPushButton#leaveButton {
                color: #ff8c7c;
                min-width: 110px;
            }
            QFrame#volumeControls {
                background: transparent;
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
            QLineEdit#inviteLinkField {
                background: rgba(255, 255, 255, 0.06);
                color: rgba(255, 255, 255, 0.76);
                border: 1px solid rgba(255, 255, 255, 0.08);
                min-width: 360px;
                max-width: 460px;
                font-size: 12px;
                padding: 10px 12px;
            }
            QSlider#volumeSlider {
                min-width: 140px;
            }
            QListWidget {
                border: none;
            }
            QStatusBar {
                background: #141626;
                color: #e0bad7;
            }
            """
        )
