from __future__ import annotations

import base64
from dataclasses import dataclass
import re
from typing import Any

import httpx

from app.config import get_settings
from app.services.room_service import ChatAttachment


@dataclass(frozen=True)
class GifSearchResult:
    title: str
    gif_url: str
    preview_url: str
    provider: str = "Tenor"


async def search_tenor_gifs(query: str, limit: int = 12) -> list[GifSearchResult]:
    settings = get_settings()
    if not settings.tenor_api_key:
        raise RuntimeError("TENOR_API_KEY is not set.")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            "https://g.tenor.com/v1/search",
            params={
                "q": query,
                "key": settings.tenor_api_key,
                "limit": limit,
                "media_filter": "minimal",
                "contentfilter": "medium",
                "locale": "en_US",
            },
        )
        response.raise_for_status()

    return _parse_tenor_results(response.json())


async def gif_result_to_attachment(result: GifSearchResult) -> ChatAttachment:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        response = await client.get(result.gif_url or result.preview_url)
        response.raise_for_status()

    filename = f"{_slugify(result.title)}.gif"
    return ChatAttachment(
        filename=filename,
        mime_type="image/gif",
        data_base64=base64.b64encode(response.content).decode("ascii"),
    )


def _parse_tenor_results(payload: dict[str, Any]) -> list[GifSearchResult]:
    results: list[GifSearchResult] = []
    for item in payload.get("results", []):
        media = _first_media_item(item)
        if media is None:
            continue

        gif_url = _media_url(media, "gif")
        preview_url = _media_url(media, "tinygif") or gif_url
        if not gif_url and not preview_url:
            continue

        title = _title_from_item(item)
        results.append(
            GifSearchResult(
                title=title,
                gif_url=gif_url or preview_url,
                preview_url=preview_url,
            )
        )
    return results


def _first_media_item(item: dict[str, Any]) -> dict[str, Any] | None:
    media = item.get("media")
    if isinstance(media, list) and media and isinstance(media[0], dict):
        return media[0]

    media_formats = item.get("media_formats")
    if isinstance(media_formats, dict):
        return media_formats

    return None


def _media_url(media: dict[str, Any], key: str) -> str:
    value = media.get(key)
    if isinstance(value, dict):
        return str(value.get("url") or "")
    return ""


def _title_from_item(item: dict[str, Any]) -> str:
    content_description = str(item.get("content_description") or "").strip()
    if content_description:
        return content_description

    tags = item.get("tags")
    if isinstance(tags, list):
        clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        if clean_tags:
            return " ".join(clean_tags[:3])

    return "Tenor GIF"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "tenor-gif"
