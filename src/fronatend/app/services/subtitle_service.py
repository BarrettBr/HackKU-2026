from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
import re
import zipfile

import httpx

from app.config import get_settings


@dataclass(frozen=True)
class ParsedSubtitle:
    filename: str
    content: str
    cue_count: int


TIMECODE_PATTERN = re.compile(
    r"\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}"
)


def load_srt_file(file_path: str) -> ParsedSubtitle:
    path = Path(file_path)
    if path.suffix.lower() != ".srt":
        raise ValueError("Choose an .srt subtitle file.")

    raw = path.read_bytes()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")

    return parse_srt_content(path.name, content)


def parse_srt_content(filename: str, content: str) -> ParsedSubtitle:
    cue_count = len(TIMECODE_PATTERN.findall(content))
    if cue_count == 0:
        raise ValueError("That file does not look like a valid SRT subtitle file.")

    return ParsedSubtitle(
        filename=filename,
        content=content,
        cue_count=cue_count,
    )


async def search_opensubtitles_srt(
    movie_title: str, language: str = "en"
) -> ParsedSubtitle:
    settings = get_settings()
    if not settings.opensubtitles_api_key:
        raise RuntimeError("OPENSUBTITLES_API_KEY is not set.")

    headers = {
        "Api-Key": settings.opensubtitles_api_key,
        "User-Agent": settings.opensubtitles_user_agent,
    }
    async with httpx.AsyncClient(
        base_url="https://api.opensubtitles.com/api/v1",
        headers=headers,
        timeout=15.0,
    ) as client:
        search_response = await client.get(
            "/subtitles",
            params={
                "query": movie_title,
                "languages": language,
                "type": "movie",
                "order_by": "download_count",
                "order_direction": "desc",
            },
        )
        search_response.raise_for_status()
        file_id = _first_subtitle_file_id(search_response.json())

        download_response = await client.post("/download", json={"file_id": file_id})
        download_response.raise_for_status()
        link = str(download_response.json().get("link") or "")
        if not link:
            raise RuntimeError("OpenSubtitles did not return a download link.")

    async with httpx.AsyncClient(timeout=15.0) as client:
        subtitle_response = await client.get(link)
        subtitle_response.raise_for_status()
        filename, content = _subtitle_content_from_download(
            link, subtitle_response.content
        )

    return parse_srt_content(filename, content)


def _first_subtitle_file_id(payload: dict) -> int:
    for item in payload.get("data", []):
        attributes = item.get("attributes", {})
        for file_info in attributes.get("files", []):
            if file_info.get("file_id"):
                return int(file_info["file_id"])
    raise RuntimeError("No SRT subtitles were found for that movie.")


def _subtitle_content_from_download(link: str, data: bytes) -> tuple[str, str]:
    filename = Path(link.split("?", maxsplit=1)[0]).name or "subtitles.srt"
    if data.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".srt"):
                    return Path(name).name, archive.read(name).decode("utf-8-sig")
        raise RuntimeError("Downloaded subtitle archive did not include an SRT file.")

    if not filename.lower().endswith(".srt"):
        filename = f"{Path(filename).stem or 'subtitles'}.srt"
    try:
        return filename, data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return filename, data.decode("latin-1")
