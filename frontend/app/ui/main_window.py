from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.services.api_client import ApiClient
from app.services.ws_client import WsClient
from app.state.app_state import AppState
from app.ui.chat_panel import ChatPanel
from app.ui.file_share_panel import FileSharePanel
from app.ui.sidebar import Sidebar
from app.ui.user_list import UserList


class MainWindow(QMainWindow):
    def __init__(
        self, state: AppState, api_client: ApiClient, ws_client: WsClient
    ) -> None:
        super().__init__()
        self.state = state
        self.api_client = api_client
        self.ws_client = ws_client

        self.setWindowTitle("Moovie Night")
        self.setMinimumSize(1180, 720)
        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        sidebar = Sidebar()
        layout.addWidget(sidebar, 0)

        content = QVBoxLayout()
        content.setSpacing(16)
        layout.addLayout(content, 1)

        video_panel = self._build_video_placeholder()
        content.addWidget(video_panel, 3)

        lower = QHBoxLayout()
        lower.setSpacing(16)
        content.addLayout(lower, 2)

        chat_panel = ChatPanel()
        lower.addWidget(chat_panel, 2)

        right_column = QVBoxLayout()
        right_column.setSpacing(16)
        lower.addLayout(right_column, 1)

        participant_list = UserList()
        file_share_panel = FileSharePanel()
        right_column.addWidget(participant_list, 1)
        right_column.addWidget(file_share_panel, 1)

    def _build_video_placeholder(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("videoPanel")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)
        layout.addStretch()

        title = QLabel("Shared Movie Screen")
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel(
            "This area is reserved for the host video stream and playback controls."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setObjectName("mutedLabel")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch()
        return frame

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #101522;
                color: #ecf1ff;
                font-family: "SF Pro Display", "Helvetica Neue", sans-serif;
                font-size: 14px;
            }
            QFrame#panel, QFrame#videoPanel {
                background: #182033;
                border: 1px solid #28324b;
                border-radius: 16px;
            }
            QFrame#videoPanel {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #152238, stop: 1 #25375b
                );
            }
            QLabel#sectionTitle {
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#mutedLabel {
                color: #9ba8c7;
            }
            QListWidget, QTextEdit, QLineEdit {
                background: #0d1320;
                border: 1px solid #28324b;
                border-radius: 12px;
                padding: 8px;
            }
            QPushButton {
                background: #6ea8fe;
                color: #08101d;
                border: none;
                border-radius: 10px;
                padding: 10px 14px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #8bbbff;
            }
            """
        )
