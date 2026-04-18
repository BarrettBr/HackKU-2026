from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.api_client import ApiClient
from app.services.ws_client import WsClient
from app.state.app_state import AppState
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Moovie Night")

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    settings = get_settings()
    state = AppState()
    api_client = ApiClient(settings=settings)
    ws_client = WsClient(settings=settings)

    window = MainWindow(state=state, api_client=api_client, ws_client=ws_client)
    window.resize(1400, 860)
    window.show()

    with loop:
        return loop.run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
