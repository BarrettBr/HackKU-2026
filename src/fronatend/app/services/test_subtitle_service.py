from __future__ import annotations

import pytest

from app.services.subtitle_service import load_srt_file


def test_load_srt_file_counts_cues(tmp_path) -> None:
    subtitle_path = tmp_path / "movie.srt"
    subtitle_path.write_text(
        "1\n"
        "00:00:01,000 --> 00:00:03,000\n"
        "Hello there.\n\n"
        "2\n"
        "00:00:04,500 --> 00:00:06,000\n"
        "Welcome to movie night.\n",
        encoding="utf-8",
    )

    parsed = load_srt_file(str(subtitle_path))

    assert parsed.filename == "movie.srt"
    assert parsed.cue_count == 2
    assert "Welcome to movie night." in parsed.content


def test_load_srt_file_rejects_invalid_file(tmp_path) -> None:
    subtitle_path = tmp_path / "bad.srt"
    subtitle_path.write_text("not really subtitles", encoding="utf-8")

    with pytest.raises(ValueError):
        load_srt_file(str(subtitle_path))
