from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"

load_dotenv(ROOT_DIR / ".env")
load_dotenv(FRONTEND_DIR / ".env")


class Settings(BaseModel):
    app_name: str = "Moovie Night"
    backend_http_url: str = "http://127.0.0.1:8080"
    backend_ws_url: str = "ws://127.0.0.1:8080/ws"
    omdb_api_key: str = ""
    opensubtitles_api_key: str = ""
    opensubtitles_user_agent: str = "MoovieNight v1"
    tenor_api_key: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        backend_http_url=os.getenv("BACKEND_HTTP_URL", "http://127.0.0.1:8080"),
        backend_ws_url=os.getenv("BACKEND_WS_URL", "ws://127.0.0.1:8080/ws"),
        omdb_api_key=os.getenv("OMDB_API_KEY", ""),
        opensubtitles_api_key=os.getenv("OPENSUBTITLES_API_KEY", ""),
        opensubtitles_user_agent=os.getenv(
            "OPENSUBTITLES_USER_AGENT", "MoovieNight v1"
        ),
        tenor_api_key=os.getenv("TENOR_API_KEY", ""),
    )
