from __future__ import annotations

import asyncio

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
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
from app.services.movie_info_service import MovieInfo, MovieInfoService
from app.services.room_service import (
    ChatAttachment,
    ChatMessage,
    JoinTarget,
    RoomClient,
    RoomHostService,
    RoomInfo,
    RoomMovieInfo,
    RoomSubtitleInfo,
    parse_join_target,
)
from app.services.subtitle_service import load_srt_file, search_opensubtitles_srt
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
        self._movie_info_service = MovieInfoService(api_client)
        self.chat_open = True
        self.is_paused = False
        self._user_list_dialog: UserListDialog | None = None
        self._movie_info_dialog: QDialog | None = None
        self._movie_search_input: QLineEdit
        self._movie_info_title: QLabel
        self._movie_info_plot: QLabel
        self._movie_info_cast: QLabel
        self._movie_search_button: QPushButton
        self._subtitle_button: QPushButton
        self._subtitle_auto_button: QPushButton
        self._subtitle_status: QLabel
        self._current_movie: RoomMovieInfo | None = None
        self._current_subtitles: RoomSubtitleInfo | None = None
        self._room_host = RoomHostService(display_name=self.state.display_name)
        self._room_client = RoomClient(display_name=self.state.display_name)
        self._room_target: JoinTarget | None = None
        self._last_message_id = 0
        self._author_colors: dict[str, str] = {}
        self._author_avatars: dict[str, str] = {}
        self._participant_buttons: list[QPushButton] = []
        self._palette = (
            "#30BCED",
            "#6BF178",
            "#FC5130",
            "#E0BAD7",
            "#C9BEFF",
            "#FF9A6C",
            "#65E7C6",
            "#8EC7FF",
        )

        self.setWindowTitle("Moovie Night")
        self.setMinimumSize(1000, 620)
        self.setMouseTracking(True)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._clear_status_text)

        self._chrome_timer = QTimer(self)
        self._chrome_timer.setInterval(3600)
        self._chrome_timer.timeout.connect(self._hide_chrome)
        self._room_poll_timer = QTimer(self)
        self._room_poll_timer.setInterval(900)
        self._room_poll_timer.timeout.connect(self._poll_room)

        self._build_ui()
        self._apply_styles()
        self._install_mouse_tracking(self._video_surface)
        self._install_mouse_tracking(self._top_bar)
        self._install_mouse_tracking(self._bottom_bar)
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

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        shell_layout.addWidget(self._splitter, 1)

        video_column = QFrame()
        video_column.setObjectName("videoColumn")
        video_layout = QVBoxLayout(video_column)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(0)

        self._top_bar = self._build_top_bar()
        video_layout.addWidget(self._top_bar)

        self._video_surface = self._build_video_surface()
        video_layout.addWidget(self._video_surface, 1)

        self._bottom_bar = self._build_bottom_bar()
        video_layout.addWidget(self._bottom_bar)
        self._splitter.addWidget(video_column)

        self._chat_panel = ChatPanel()
        self._chat_panel.seed_messages()
        self._chat_panel.message_sent.connect(self._handle_local_message)
        self._chat_panel.file_sent.connect(self._handle_local_file)
        self._chat_panel.gif_sent.connect(self._handle_local_gif)
        self._chat_panel.reaction_sent.connect(self._send_reaction)
        self._splitter.addWidget(self._chat_panel)
        self._splitter.setSizes([1000, 420])
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
        self._invite_link_field.hide()
        layout.addWidget(self._invite_link_field)

        layout.addStretch()

        movie_info_button = QPushButton("IMDb")
        movie_info_button.setObjectName("ghostButton")
        movie_info_button.clicked.connect(self._show_movie_info_dialog)
        layout.addWidget(movie_info_button)

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
        self._invite_link_field.hide()
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
        self.is_paused = room.is_paused
        self._current_movie = room.movie
        self._current_subtitles = room.subtitles

        self._room_name_label.setText(room.room_name)
        self._connection_label.setText(self.state.connection_status)
        self._invite_link_field.setText(
            room.invite_link if is_host else room.compact_code
        )
        self._invite_link_field.hide()
        self._last_message_id = 0
        self._chat_panel.clear_messages()
        self._refresh_participants(room.participants)
        self._apply_pause_state(room.is_paused)
        if room.movie is not None:
            self._apply_room_movie(room.movie)
        if room.subtitles is not None:
            self._apply_room_subtitles(room.subtitles)

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

    def _handle_local_file(self, file_path: str) -> None:
        if self._room_target is None:
            self.statusBar().showMessage(
                "Join or create a room before attaching.", 2500
            )
            return
        asyncio.create_task(self._send_file_async(self._room_target, file_path))

    def _handle_local_gif(self, attachment: ChatAttachment) -> None:
        if self._room_target is None:
            self.statusBar().showMessage(
                "Join or create a room before sending GIFs.", 2500
            )
            return
        asyncio.create_task(self._send_gif_async(self._room_target, attachment))

    def _send_reaction(self, message_id: int, reaction: str) -> None:
        if self._room_target is None:
            self.statusBar().showMessage("Join or create a room before reacting.", 2500)
            return
        asyncio.create_task(
            self._send_reaction_async(self._room_target, message_id, reaction)
        )

    async def _send_chat_message_async(self, target: JoinTarget, message: str) -> None:
        try:
            chat_message = await self._room_client.send_message(target, message)
        except Exception as error:
            self.statusBar().showMessage(f"Message failed: {error}", 3000)
            return
        self._append_chat_message(chat_message)

    async def _send_reaction_async(
        self,
        target: JoinTarget,
        message_id: int,
        reaction: str,
    ) -> None:
        try:
            chat_message = await self._room_client.send_reaction(
                target=target,
                message_id=message_id,
                reaction=reaction,
            )
        except Exception as error:
            self.statusBar().showMessage(f"Reaction failed: {error}", 3000)
            return
        self._append_chat_message(chat_message)

    async def _send_file_async(self, target: JoinTarget, file_path: str) -> None:
        try:
            chat_message = await self._room_client.send_attachment(target, file_path)
        except Exception as error:
            self.statusBar().showMessage(f"Upload failed: {error}", 3000)
            return
        self._append_chat_message(chat_message)

    async def _send_gif_async(
        self,
        target: JoinTarget,
        attachment: ChatAttachment,
    ) -> None:
        try:
            chat_message = await self._room_client.send_prepared_attachment(
                target,
                attachment,
            )
        except Exception as error:
            self.statusBar().showMessage(f"GIF failed: {error}", 3000)
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
        if not self.state.is_host and room.is_paused != self.is_paused:
            self._apply_pause_state(room.is_paused)
        if room.movie is not None:
            self._apply_room_movie(room.movie)
        if room.subtitles is not None:
            self._apply_room_subtitles(room.subtitles)
        for message in messages:
            self._append_chat_message(message)

    def _append_chat_message(self, message: ChatMessage) -> None:
        self._last_message_id = max(self._last_message_id, message.id)
        self._chat_panel.add_message(
            message_id=message.id,
            author=message.author,
            message=message.text,
            author_color=self._color_for_author(message.author),
            is_host=message.author == self._host_name(),
            attachment=message.attachment,
            reactions=tuple(message.reactions.items()),
        )

    def _toggle_pause(self) -> None:
        next_state = not self.is_paused
        self._apply_pause_state(next_state)
        if self.state.is_host and self._room_target is not None:
            asyncio.create_task(self._broadcast_pause_state(self._room_target))

    def _apply_pause_state(self, is_paused: bool) -> None:
        self.is_paused = is_paused
        self._pause_button.setText("▶  Play" if self.is_paused else "⏸  Pause")
        if self.is_paused:
            self._status_timer.stop()
            self._status_label.setText("Paused")
        else:
            self._status_label.setText("Playing")
            self._status_timer.start()

    async def _broadcast_pause_state(self, target: JoinTarget) -> None:
        try:
            await self._room_client.update_playback(target, self.is_paused)
        except Exception as error:
            self.statusBar().showMessage(f"Could not sync pause: {error}", 3000)

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
        self._invite_link_field.hide()
        self._top_bar.hide()
        self._bottom_bar.hide()

    def _toggle_chat_panel(self) -> None:
        self.chat_open = not self.chat_open
        self._chat_panel.setVisible(self.chat_open)
        if self.chat_open:
            self._splitter.setSizes([1000, 420])
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

    def _show_movie_info_dialog(self) -> None:
        if self._movie_info_dialog is None:
            self._movie_info_dialog = self._build_movie_info_dialog()
            self._movie_info_dialog.setStyleSheet(self.styleSheet())

        if self.state.is_host:
            self._movie_search_input.show()
            self._movie_search_button.show()
            self._subtitle_button.show()
            self._subtitle_auto_button.show()
            self._movie_search_input.setText(self.state.movie_title)
        else:
            self._movie_search_input.hide()
            self._movie_search_button.hide()
            self._subtitle_button.hide()
            self._subtitle_auto_button.hide()
            if self._current_movie is None:
                self._movie_info_title.setText("No movie selected yet.")
                self._movie_info_plot.setText(
                    "The host has not imported movie information yet."
                )
                self._movie_info_cast.setText("")
        if self._current_movie is not None:
            self._apply_room_movie(self._current_movie)
        if self._current_subtitles is not None:
            self._apply_room_subtitles(self._current_subtitles)
        self._movie_info_dialog.show()
        self._movie_info_dialog.raise_()
        self._movie_info_dialog.activateWindow()

    def _build_movie_info_dialog(self) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("Movie Info")
        dialog.setModal(False)
        dialog.setMinimumWidth(460)
        dialog.setObjectName("movieInfoDialog")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Movie lookup")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self._movie_search_input = QLineEdit()
        self._movie_search_input.setObjectName("movieSearchInput")
        self._movie_search_input.setPlaceholderText("Search IMDb title...")
        self._movie_search_input.returnPressed.connect(self._search_movie_info)
        layout.addWidget(self._movie_search_input)

        self._movie_search_button = QPushButton("Search")
        self._movie_search_button.setObjectName("primaryButton")
        self._movie_search_button.clicked.connect(self._search_movie_info)
        layout.addWidget(self._movie_search_button)

        self._subtitle_button = QPushButton("Choose .srt subtitles")
        self._subtitle_button.setObjectName("ghostButton")
        self._subtitle_button.clicked.connect(self._choose_subtitles)
        layout.addWidget(self._subtitle_button)

        self._subtitle_auto_button = QPushButton("Find subtitles")
        self._subtitle_auto_button.setObjectName("ghostButton")
        self._subtitle_auto_button.clicked.connect(self._find_subtitles)
        layout.addWidget(self._subtitle_auto_button)

        self._subtitle_status = QLabel("No subtitle file selected.")
        self._subtitle_status.setObjectName("movieInfoBody")
        self._subtitle_status.setWordWrap(True)
        layout.addWidget(self._subtitle_status)

        self._movie_info_title = QLabel("No movie selected yet.")
        self._movie_info_title.setObjectName("movieInfoTitle")
        self._movie_info_title.setWordWrap(True)
        layout.addWidget(self._movie_info_title)

        self._movie_info_plot = QLabel(
            "Search a title to select it for the room. The app uses no-key "
            "public lookup first, with OMDb as an optional richer fallback."
        )
        self._movie_info_plot.setObjectName("movieInfoBody")
        self._movie_info_plot.setWordWrap(True)
        layout.addWidget(self._movie_info_plot)

        self._movie_info_cast = QLabel("")
        self._movie_info_cast.setObjectName("movieInfoBody")
        self._movie_info_cast.setWordWrap(True)
        layout.addWidget(self._movie_info_cast)

        return dialog

    def _choose_subtitles(self) -> None:
        if not self.state.is_host:
            return

        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Choose subtitles",
            "",
            "SRT subtitles (*.srt)",
        )
        if not file_path:
            return

        try:
            parsed = load_srt_file(file_path)
        except ValueError as error:
            self._subtitle_status.setText(str(error))
            return

        subtitles = RoomSubtitleInfo(
            filename=parsed.filename,
            content=parsed.content,
            cue_count=parsed.cue_count,
        )
        self._apply_room_subtitles(subtitles)
        if self._room_target is not None:
            asyncio.create_task(self._broadcast_subtitles(self._room_target, subtitles))

    def _find_subtitles(self) -> None:
        if not self.state.is_host:
            return

        movie_title = self.state.movie_title.strip()
        if not movie_title or movie_title == "Movie Title":
            movie_title = self._movie_search_input.text().strip()
        if not movie_title:
            self._subtitle_status.setText(
                "Choose a movie title before finding subtitles."
            )
            return

        self._subtitle_status.setText(f"Searching subtitles for {movie_title}...")
        asyncio.create_task(self._find_subtitles_async(movie_title))

    async def _find_subtitles_async(self, movie_title: str) -> None:
        try:
            parsed = await search_opensubtitles_srt(movie_title)
        except Exception as error:
            self._subtitle_status.setText(
                "Could not auto-find subtitles. Add OPENSUBTITLES_API_KEY to .env "
                f"or choose an .srt manually. Error: {error}"
            )
            return

        subtitles = RoomSubtitleInfo(
            filename=parsed.filename,
            content=parsed.content,
            cue_count=parsed.cue_count,
        )
        self._apply_room_subtitles(subtitles)
        if self._room_target is not None:
            asyncio.create_task(self._broadcast_subtitles(self._room_target, subtitles))

    def _search_movie_info(self) -> None:
        query = self._movie_search_input.text().strip()
        if not query:
            return

        self._movie_info_title.setText("Searching movie info...")
        self._movie_info_plot.setText("")
        self._movie_info_cast.setText("")
        asyncio.create_task(self._search_movie_info_async(query))

    async def _search_movie_info_async(self, query: str) -> None:
        try:
            movie = await self._movie_info_service.search(query)
        except Exception as error:
            self._movie_info_title.setText("Movie lookup failed.")
            self._movie_info_plot.setText(
                "The title was not changed because the lookup failed. "
                f"Current error: {error}"
            )
            self._movie_info_cast.setText("")
            return

        self._apply_movie_info(movie)

    def _apply_movie_info(self, movie: MovieInfo) -> None:
        room_movie = RoomMovieInfo(
            title=movie.title,
            year=movie.year,
            plot=movie.plot,
            actors=movie.actors,
            rating=movie.rating,
        )
        self._apply_room_movie(room_movie)
        if self.state.is_host and self._room_target is not None:
            asyncio.create_task(
                self._broadcast_movie_info(self._room_target, room_movie)
            )

    def _apply_room_movie(self, movie: RoomMovieInfo) -> None:
        year_suffix = f" ({movie.year})" if movie.year else ""
        rating_suffix = f" • IMDb {movie.rating}" if movie.rating else ""
        self._current_movie = movie
        self.state.movie_title = movie.title
        self.state.movie_year = movie.year
        self._movie_title_label.setText(f"{movie.title}{year_suffix}")
        if self._movie_info_dialog is None:
            return

        self._movie_info_title.setText(f"{movie.title}{year_suffix}{rating_suffix}")
        self._movie_info_plot.setText(movie.plot or "No description available yet.")
        self._movie_info_cast.setText(f"Cast: {movie.actors or 'Unknown cast'}")

    async def _broadcast_movie_info(
        self,
        target: JoinTarget,
        movie: RoomMovieInfo,
    ) -> None:
        try:
            await self._room_client.update_movie(target, movie)
        except Exception as error:
            self.statusBar().showMessage(f"Movie info did not sync: {error}", 3000)

    def _apply_room_subtitles(self, subtitles: RoomSubtitleInfo) -> None:
        self._current_subtitles = subtitles
        if self._movie_info_dialog is not None:
            self._subtitle_status.setText(
                f"Subtitles: {subtitles.filename} ({subtitles.cue_count} cues)"
            )
        self.statusBar().showMessage(
            f"Loaded subtitles: {subtitles.filename}",
            3000,
        )

    async def _broadcast_subtitles(
        self,
        target: JoinTarget,
        subtitles: RoomSubtitleInfo,
    ) -> None:
        try:
            await self._room_client.update_subtitles(target, subtitles)
        except Exception as error:
            self.statusBar().showMessage(f"Subtitles did not sync: {error}", 3000)

    def _show_invite_hint(self) -> None:
        if not self.state.invite_link:
            self.statusBar().showMessage("Create a room before inviting people.", 2500)
            return

        self._invite_link_field.show()
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

        avatar = self._initials_for(participant)
        self._author_avatars[participant] = avatar
        return avatar

    def _initials_for(self, participant: str) -> str:
        clean_name = participant.replace("(Host)", "").strip()
        parts = [part for part in clean_name.split() if part]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return "".join(part[0].upper() for part in parts[:2])

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
                border-radius: 0px;
            }
            QFrame#videoColumn {
                background: #0a0914;
            }
            QFrame#topBar,
            QFrame#bottomBar,
            QFrame#chatHeader,
            QFrame#chatComposer {
                background: #17172c;
            }
            QFrame#topBar {
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            }
            QFrame#bottomBar {
                border-top: 1px solid rgba(255, 255, 255, 0.08);
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
                background: #17172c;
            }
            QFrame#chatBubble {
                background: #232339;
                border-radius: 18px;
            }
            QFrame#chatBubble[selected="true"] {
                border: 1px solid rgba(101, 231, 198, 0.85);
            }
            QFrame#attachmentPreview {
                background: rgba(255, 255, 255, 0.07);
                border-radius: 14px;
            }
            QDialog#participantDialog {
                background: #17172c;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
            }
            QDialog#movieInfoDialog {
                background: #17172c;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
            }
            QDialog#gifLibraryDialog {
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
            QLabel#movieInfoTitle,
            QLabel#sectionTitle {
                color: #ffffff;
                font-size: 20px;
                font-weight: 800;
            }
            QLabel#movieInfoBody {
                color: rgba(255, 255, 255, 0.72);
                font-size: 14px;
                font-weight: 600;
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
            QLabel#attachmentTitle {
                color: rgba(255, 255, 255, 0.72);
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#attachmentImage {
                background: transparent;
                border-radius: 10px;
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
            QLabel#reactionIcon {
                min-width: 20px;
                min-height: 20px;
            }
            QPushButton#bubbleReactionButton {
                min-width: 34px;
                max-width: 34px;
                min-height: 34px;
                max-height: 34px;
                border-radius: 17px;
                padding: 0px;
                background: transparent;
                border: 1px solid transparent;
            }
            QPushButton#bubbleReactionButton:hover {
                background: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.12);
            }
            QPushButton#avatarChip {
                font-family: "Apple Color Emoji", "Noto Color Emoji", "Segoe UI Emoji", "Twemoji Mozilla", sans-serif;
            }
            QMenu {
                background: #232339;
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
                padding: 8px;
            }
            QMenu::item {
                padding: 8px 24px 8px 10px;
                border-radius: 8px;
            }
            QMenu::item:selected {
                background: rgba(255, 255, 255, 0.09);
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
            QPushButton#ghostSmallButton {
                min-width: 42px;
                max-width: 42px;
                min-height: 42px;
                max-height: 42px;
                padding: 0px;
                background: rgba(255, 255, 255, 0.04);
                color: rgba(255, 255, 255, 0.66);
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
            QToolButton#reactionMenuButton {
                min-width: 112px;
                min-height: 52px;
                border-radius: 18px;
                padding: 0px 14px;
                text-align: left;
            }
            QPushButton#downloadButton {
                background: rgba(255, 255, 255, 0.08);
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: 800;
            }
            QPushButton#primaryButton {
                min-width: 56px;
                max-width: 70px;
                min-height: 42px;
                max-height: 42px;
                padding: 0px;
                background: rgba(255, 255, 255, 0.04);
                color: rgba(255, 255, 255, 0.35);
            }
            QPushButton#gifChoiceButton {
                background: rgba(255, 255, 255, 0.05);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 10px 12px;
                text-align: left;
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
                background: #232339;
                color: #ffffff;
                border: none;
                border-radius: 14px;
                padding: 16px 18px;
                font-size: 18px;
                font-weight: 600;
            }
            QTextEdit#messageInput {
                background: #232339;
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 14px;
                padding: 10px 14px;
                font-size: 15px;
                font-weight: 600;
            }
            QTextEdit#messageInput QScrollBar {
                width: 0px;
                height: 0px;
                background: transparent;
            }
            QLineEdit#movieSearchInput {
                background: #232339;
                color: #ffffff;
            }
            QLineEdit#roomIdInput,
            QLineEdit#roomNameInput {
                background: #232339;
                color: #ffffff;
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
