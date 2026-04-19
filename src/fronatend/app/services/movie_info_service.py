from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib
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

    Uses the local backend endpoint when available, then falls back to no-key
    public sources. OMDb remains optional for teams that already have a key.
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
            return await self._search_wikipedia(clean_query)
        except Exception:
            pass

        try:
            return await self._search_cinemagoer(clean_query)
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

    async def _search_cinemagoer(self, query: str) -> MovieInfo:
        return await asyncio.to_thread(_search_cinemagoer_sync, query)

    async def _search_wikipedia(self, query: str) -> MovieInfo:
        headers = {"User-Agent": "MoovieNight/1.0 (HackKU demo app)"}
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            search_response = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": f"{query} film",
                    "srlimit": 1,
                    "format": "json",
                    "origin": "*",
                },
            )
            search_response.raise_for_status()
            search_results = search_response.json()["query"]["search"]
            if not search_results:
                raise RuntimeError("Movie not found")

            page_title = str(search_results[0]["title"])
            summary_response = await client.get(
                "https://en.wikipedia.org/api/rest_v1/page/summary/" + page_title,
            )
            summary_response.raise_for_status()
            payload = summary_response.json()

        title = str(payload.get("title") or page_title)
        plot = str(payload.get("extract") or "No description yet.")
        year = _year_from_title(title) or _year_from_text(plot)
        return MovieInfo(
            title=title,
            year=year,
            plot=plot,
            actors="Cast details unavailable from Wikipedia summary.",
            rating="",
        )

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


def _search_cinemagoer_sync(query: str) -> MovieInfo:
    imdb_module = importlib.import_module("imdb")
    ia = imdb_module.Cinemagoer()
    results = ia.search_movie(query)
    if not results:
        raise RuntimeError("Movie not found")

    movie = results[0]
    ia.update(movie)

    plot_value = movie.get("plot outline") or movie.get("plot") or ""
    if isinstance(plot_value, list):
        plot = str(plot_value[0]) if plot_value else ""
    else:
        plot = str(plot_value)

    cast_value = movie.get("cast") or []
    actors = ", ".join(str(actor.get("name") or actor) for actor in cast_value[:4])

    return MovieInfo(
        title=str(movie.get("title") or query.title()),
        year=str(movie.get("year") or ""),
        plot=plot or "No description yet.",
        actors=actors or "Unknown cast",
        rating=str(movie.get("rating") or ""),
    )


def _year_from_title(title: str) -> str:
    if "(" not in title:
        return ""

    suffix = title.rsplit("(", maxsplit=1)[-1].split(")", maxsplit=1)[0]
    year = suffix.split()[0]
    return year if year.isdigit() and len(year) == 4 else ""


def _year_from_text(text: str) -> str:
    for token in text.replace(",", " ").split():
        clean_token = token.strip("().")
        if clean_token.isdigit() and len(clean_token) == 4:
            return clean_token
    return ""


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
            "Movie selected for the room. No-key lookup could not find details; "
            "OMDB_API_KEY is still available as an optional richer metadata "
            "fallback."
        ),
        actors="Cast details unavailable in local fallback mode.",
    )
