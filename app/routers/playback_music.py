"""Authenticated Music 2.0 routes mounted below /api/playback/music."""

from fastapi import APIRouter, Depends, Query

from app.routers.auth import get_current_user_id
from app.routers import music2


router = APIRouter()


@router.get("/music/status")
def status(user_id: int = Depends(get_current_user_id)):
    return music2.music_status()


@router.post("/music/refresh")
def refresh(
    force: bool = Query(default=False),
    user_id: int = Depends(get_current_user_id),
):
    return music2.refresh_music_catalog(force=force)


@router.get("/music/catalog")
def catalog(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=250, ge=1, le=1000),
    q: str = Query(default="", max_length=200),
    artist: str = Query(default="", max_length=300),
    album: str = Query(default="", max_length=300),
    user_id: int = Depends(get_current_user_id),
):
    return music2.music_catalog(
        offset=offset,
        limit=limit,
        q=q,
        artist=artist,
        album=album,
    )


@router.get("/music/facets")
def facets(user_id: int = Depends(get_current_user_id)):
    return music2.music_facets()


@router.get("/music/artwork")
def artwork(
    path: str = Query(...),
    user_id: int = Depends(get_current_user_id),
):
    return music2.music_artwork(path=path)
