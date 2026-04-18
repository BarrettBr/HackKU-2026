from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
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

    Uses the local backend endpoint when available, then falls back to OMDb,
    which returns IMDb-sourced metadata with an API key.
    """

    def __init__(self, api_client: ApiClient) -> None:
        self._api_client = api_client

    async def search(self, query: str) -> MovieInfo:
        clean_query = query.strip()
        try:
            return await self._search_backend(clean_query)
        except Exception:
            pass

        try:
            return await self._search_omdb(clean_query)
        except Exception:
            return fallback_movie_info(clean_query)

    async def _search_backend(self, query: str) -> MovieInfo:
        response = await self._api_client.get(
            "/movies/search",
            params={"q": query},
        )
        payload = response.json()
        if isinstance(payload, list):
            payload = payload[0] if payload else {}

        return movie_info_from_payload(payload)

    async def _search_omdb(self, query: str) -> MovieInfo:
        api_key = get_settings().omdb_api_key
        if not api_key:
            raise RuntimeError("OMDB_API_KEY is not set")

        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                "https://www.omdbapi.com/",
                params={
                    "apikey": api_key,
                    "t": query,
                    "plot": "full",
                    "type": "movie",
                },
            )
            response.raise_for_status()
            payload = response.json()

        if payload.get("Response") == "False":
            raise RuntimeError(str(payload.get("Error") or "Movie not found"))

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
            "Movie selected for the room. Add OMDB_API_KEY to .env for live "
            "IMDb-sourced plot, cast, year, and rating details."
        ),
        actors="Cast details unavailable in local fallback mode.",
    )
