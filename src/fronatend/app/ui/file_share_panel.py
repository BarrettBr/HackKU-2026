from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QPushButton, QVBoxLayout


class FileSharePanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("File Sharing")
        title.setObjectName("sectionTitle")
        hint = QLabel("Drop future subtitle files, posters, or room notes here.")
        hint.setObjectName("mutedLabel")

        shared_files = QListWidget()
        shared_files.addItems(
            [
                "No files uploaded yet",
            ]
        )

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(shared_files, 1)
        layout.addWidget(QPushButton("Upload Placeholder"))
