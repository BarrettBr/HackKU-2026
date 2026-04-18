from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.api_client import ApiClient


@dataclass(frozen=True)
class MovieInfo:
    title: str
    year: str
    plot: str
    actors: str
    rating: str = ""


class MovieInfoService:
    """Frontend-facing movie lookup boundary.

    The backend can wire `/movies/search` to IMDb or another provider without
    changing the desktop UI.
    """

    def __init__(self, api_client: ApiClient) -> None:
        self._api_client = api_client

    async def search(self, query: str) -> MovieInfo:
        clean_query = query.strip()
        try:
            response = await self._api_client.get(
                "/movies/search",
                params={"q": clean_query},
            )
            payload = response.json()
            if isinstance(payload, list):
                payload = payload[0] if payload else {}
        except Exception:
            return fallback_movie_info(clean_query)

        return movie_info_from_payload(payload)


def movie_info_from_payload(payload: dict[str, Any]) -> MovieInfo:
    return MovieInfo(
        title=str(payload.get("title") or payload.get("Title") or "Unknown title"),
        year=str(payload.get("year") or payload.get("Year") or ""),
        plot=str(payload.get("plot") or payload.get("Plot") or "No description yet."),
        actors=str(payload.get("actors") or payload.get("Actors") or "Unknown cast"),
        rating=str(payload.get("rating") or payload.get("imdbRating") or ""),
    )


def fallback_movie_info(query: str) -> MovieInfo:
    title = query.title() if query else "Selected Movie"
    return MovieInfo(
        title=title,
        year="",
        plot=(
            "Movie selected for the room. Detailed IMDb metadata will appear here "
            "once the backend movie provider is connected."
        ),
        actors="Cast details unavailable in local fallback mode.",
    )
