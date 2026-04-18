from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QVBoxLayout


class UserListDialog(QDialog):
    def __init__(self, participants: list[str]) -> None:
        super().__init__()
        self.setWindowTitle("Participants")
        self.setModal(False)
        self.setMinimumWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("People in the room")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        users = QListWidget()
        users.addItems(participants)
        layout.addWidget(users)
