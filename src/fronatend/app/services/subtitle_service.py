from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


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

    cue_count = len(TIMECODE_PATTERN.findall(content))
    if cue_count == 0:
        raise ValueError("That file does not look like a valid SRT subtitle file.")

    return ParsedSubtitle(
        filename=path.name,
        content=content,
        cue_count=cue_count,
    )
