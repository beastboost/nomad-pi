"""TMDB integration router - movie/show metadata, trailers, trending."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import database
from app.routers.auth import get_current_user_id, get_current_admin
from app.services import tmdb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tmdb", tags=["tmdb"])


class TMDBKeyRequest(BaseModel):
    api_key: str


@router.post("/settings/key")
def set_tmdb_key(req: TMDBKeyRequest, admin: dict = Depends(get_current_admin)):
    """Save TMDB API key (admin only)."""
    try:
        # Validate key by making a test request
        import httpx
        r = httpx.get(
            f"{tmdb.TMDB_BASE}/configuration",
            params={"api_key": req.api_key},
            timeout=10,
        )
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid TMDB API key: {e}")

    database.set_setting("tmdb_api_key", req.api_key)
    return {"status": "ok"}


@router.get("/settings/key")
def get_tmdb_key_status(user_id: int = Depends(get_current_user_id)):
    """Check if TMDB key is configured."""
    key = database.get_setting("tmdb_api_key")
    return {"configured": bool(key)}


@router.get("/search/movie")
def search_movies(
    query: str,
    page: int = Query(1, ge=1),
    user_id: int = Depends(get_current_user_id),
):
    try:
        return tmdb.search_movies(query, page)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search/tv")
def search_shows(
    query: str,
    page: int = Query(1, ge=1),
    user_id: int = Depends(get_current_user_id),
):
    try:
        return tmdb.search_shows(query, page)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/movie/{tmdb_id}")
def get_movie(tmdb_id: int, user_id: int = Depends(get_current_user_id)):
    result = tmdb.get_movie_details(tmdb_id)
    if not result:
        raise HTTPException(status_code=404, detail="Movie not found")
    return result


@router.get("/tv/{tmdb_id}")
def get_show(tmdb_id: int, user_id: int = Depends(get_current_user_id)):
    result = tmdb.get_show_details(tmdb_id)
    if not result:
        raise HTTPException(status_code=404, detail="Show not found")
    return result


@router.get("/trending")
def get_trending(
    media_type: str = Query("movie", pattern="^(movie|tv|all)$"),
    time_window: str = Query("week", pattern="^(day|week)$"),
    user_id: int = Depends(get_current_user_id),
):
    try:
        return {"results": tmdb.get_trending(media_type, time_window)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/find/{imdb_id}")
def find_by_imdb(imdb_id: str, user_id: int = Depends(get_current_user_id)):
    result = tmdb.find_by_imdb(imdb_id)
    if not result:
        raise HTTPException(status_code=404, detail="Not found on TMDB")
    return result
