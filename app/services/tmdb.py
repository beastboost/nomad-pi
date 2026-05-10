"""TMDB (The Movie Database) integration service.

Provides movie/show metadata, trailers, and search using the TMDB API.
"""

import logging
from typing import Optional

import httpx

from app import database

logger = logging.getLogger(__name__)

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p"


def _get_api_key() -> Optional[str]:
    return database.get_setting("tmdb_api_key")


def search_movies(query: str, page: int = 1) -> dict:
    api_key = _get_api_key()
    if not api_key:
        return {"results": [], "error": "TMDB API key not configured"}

    r = httpx.get(
        f"{TMDB_BASE}/search/movie",
        params={"api_key": api_key, "query": query, "page": page},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()

    return {
        "results": [
            {
                "id": m["id"],
                "title": m.get("title"),
                "overview": m.get("overview"),
                "release_date": m.get("release_date"),
                "poster": f"{TMDB_IMG_BASE}/w342{m['poster_path']}" if m.get("poster_path") else None,
                "backdrop": f"{TMDB_IMG_BASE}/w1280{m['backdrop_path']}" if m.get("backdrop_path") else None,
                "vote_average": m.get("vote_average"),
                "genre_ids": m.get("genre_ids", []),
            }
            for m in data.get("results", [])
        ],
        "total_pages": data.get("total_pages", 1),
        "page": data.get("page", 1),
    }


def search_shows(query: str, page: int = 1) -> dict:
    api_key = _get_api_key()
    if not api_key:
        return {"results": [], "error": "TMDB API key not configured"}

    r = httpx.get(
        f"{TMDB_BASE}/search/tv",
        params={"api_key": api_key, "query": query, "page": page},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()

    return {
        "results": [
            {
                "id": s["id"],
                "title": s.get("name"),
                "overview": s.get("overview"),
                "first_air_date": s.get("first_air_date"),
                "poster": f"{TMDB_IMG_BASE}/w342{s['poster_path']}" if s.get("poster_path") else None,
                "backdrop": f"{TMDB_IMG_BASE}/w1280{s['backdrop_path']}" if s.get("backdrop_path") else None,
                "vote_average": s.get("vote_average"),
                "genre_ids": s.get("genre_ids", []),
            }
            for s in data.get("results", [])
        ],
        "total_pages": data.get("total_pages", 1),
        "page": data.get("page", 1),
    }


def get_movie_details(tmdb_id: int) -> Optional[dict]:
    api_key = _get_api_key()
    if not api_key:
        return None

    r = httpx.get(
        f"{TMDB_BASE}/movie/{tmdb_id}",
        params={"api_key": api_key, "append_to_response": "videos,credits,external_ids"},
        timeout=10,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()

    trailers = []
    for v in data.get("videos", {}).get("results", []):
        if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser"):
            trailers.append({
                "name": v.get("name"),
                "key": v.get("key"),
                "url": f"https://www.youtube.com/watch?v={v['key']}",
                "type": v.get("type"),
            })

    cast = [
        {"name": c.get("name"), "character": c.get("character"), "profile": f"{TMDB_IMG_BASE}/w185{c['profile_path']}" if c.get("profile_path") else None}
        for c in data.get("credits", {}).get("cast", [])[:10]
    ]

    return {
        "id": data["id"],
        "title": data.get("title"),
        "overview": data.get("overview"),
        "release_date": data.get("release_date"),
        "runtime": data.get("runtime"),
        "genres": [g["name"] for g in data.get("genres", [])],
        "poster": f"{TMDB_IMG_BASE}/w342{data['poster_path']}" if data.get("poster_path") else None,
        "backdrop": f"{TMDB_IMG_BASE}/w1280{data['backdrop_path']}" if data.get("backdrop_path") else None,
        "vote_average": data.get("vote_average"),
        "vote_count": data.get("vote_count"),
        "imdb_id": data.get("external_ids", {}).get("imdb_id") or data.get("imdb_id"),
        "trailers": trailers,
        "cast": cast,
        "tagline": data.get("tagline"),
        "budget": data.get("budget"),
        "revenue": data.get("revenue"),
        "status": data.get("status"),
    }


def get_show_details(tmdb_id: int) -> Optional[dict]:
    api_key = _get_api_key()
    if not api_key:
        return None

    r = httpx.get(
        f"{TMDB_BASE}/tv/{tmdb_id}",
        params={"api_key": api_key, "append_to_response": "videos,credits,external_ids"},
        timeout=10,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()

    trailers = []
    for v in data.get("videos", {}).get("results", []):
        if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser"):
            trailers.append({
                "name": v.get("name"),
                "key": v.get("key"),
                "url": f"https://www.youtube.com/watch?v={v['key']}",
                "type": v.get("type"),
            })

    cast = [
        {"name": c.get("name"), "character": c.get("character"), "profile": f"{TMDB_IMG_BASE}/w185{c['profile_path']}" if c.get("profile_path") else None}
        for c in data.get("credits", {}).get("cast", [])[:10]
    ]

    return {
        "id": data["id"],
        "title": data.get("name"),
        "overview": data.get("overview"),
        "first_air_date": data.get("first_air_date"),
        "seasons": data.get("number_of_seasons"),
        "episodes": data.get("number_of_episodes"),
        "genres": [g["name"] for g in data.get("genres", [])],
        "poster": f"{TMDB_IMG_BASE}/w342{data['poster_path']}" if data.get("poster_path") else None,
        "backdrop": f"{TMDB_IMG_BASE}/w1280{data['backdrop_path']}" if data.get("backdrop_path") else None,
        "vote_average": data.get("vote_average"),
        "imdb_id": data.get("external_ids", {}).get("imdb_id"),
        "trailers": trailers,
        "cast": cast,
        "status": data.get("status"),
        "networks": [n.get("name") for n in data.get("networks", [])],
    }


def get_trending(media_type: str = "movie", time_window: str = "week") -> list:
    api_key = _get_api_key()
    if not api_key:
        return []

    r = httpx.get(
        f"{TMDB_BASE}/trending/{media_type}/{time_window}",
        params={"api_key": api_key},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()

    return [
        {
            "id": m["id"],
            "title": m.get("title") or m.get("name"),
            "overview": m.get("overview"),
            "poster": f"{TMDB_IMG_BASE}/w342{m['poster_path']}" if m.get("poster_path") else None,
            "vote_average": m.get("vote_average"),
            "media_type": m.get("media_type", media_type),
        }
        for m in data.get("results", [])[:20]
    ]


def find_by_imdb(imdb_id: str) -> Optional[dict]:
    """Find a TMDB entry by IMDB ID."""
    api_key = _get_api_key()
    if not api_key:
        return None

    r = httpx.get(
        f"{TMDB_BASE}/find/{imdb_id}",
        params={"api_key": api_key, "external_source": "imdb_id"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()

    movies = data.get("movie_results", [])
    if movies:
        m = movies[0]
        return {"id": m["id"], "type": "movie", "title": m.get("title")}

    shows = data.get("tv_results", [])
    if shows:
        s = shows[0]
        return {"id": s["id"], "type": "tv", "title": s.get("name")}

    return None
