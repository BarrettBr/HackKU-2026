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
    provider: str = "GIPHY"


async def search_giphy_gifs(query: str, limit: int = 12) -> list[GifSearchResult]:
    settings = get_settings()
    if not settings.giphy_api_key:
        raise RuntimeError("GIPHY_API_KEY is not set.")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            "https://api.giphy.com/v1/gifs/search",
            params={
                "q": query,
                "api_key": settings.giphy_api_key,
                "limit": limit,
                "rating": "pg-13",
                "lang": "en",
                "bundle": "messaging_non_clips",
            },
        )
        response.raise_for_status()

    return _parse_giphy_results(response.json())


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


def _parse_giphy_results(payload: dict[str, Any]) -> list[GifSearchResult]:
    results: list[GifSearchResult] = []
    for item in payload.get("data", []):
        images = item.get("images", {})
        gif_url = _giphy_image_url(images, "downsized") or _giphy_image_url(
            images, "original"
        )
        preview_url = (
            _giphy_image_url(images, "fixed_width_small")
            or _giphy_image_url(images, "preview_gif")
            or gif_url
        )
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


def _giphy_image_url(images: dict[str, Any], key: str) -> str:
    value = images.get(key)
    if isinstance(value, dict):
        return str(value.get("url") or "")
    return ""


def _title_from_item(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "").strip()
    if title:
        return title

    slug = str(item.get("slug") or "").strip()
    if slug:
        return slug.rsplit("-", maxsplit=1)[0].replace("-", " ")

    return "GIPHY GIF"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "giphy-gif"
