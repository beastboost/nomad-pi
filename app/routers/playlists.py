"""Playlist management router."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app import database
from app.routers.auth import get_current_user_id

router = APIRouter(prefix="/api/playlists", tags=["playlists"])


class CreatePlaylist(BaseModel):
    name: str
    description: str = ""

class AddItem(BaseModel):
    path: str
    title: str = ""

class RateRequest(BaseModel):
    path: str
    rating: int
    review: str = ""


@router.get("")
def list_playlists(user_id: int = Depends(get_current_user_id)):
    return {"playlists": database.get_playlists(user_id)}


@router.post("")
def create_playlist(req: CreatePlaylist, user_id: int = Depends(get_current_user_id)):
    pid = database.create_playlist(user_id, req.name, req.description)
    return {"id": pid, "status": "ok"}


@router.get("/{playlist_id}")
def get_playlist(playlist_id: int, user_id: int = Depends(get_current_user_id)):
    pl = database.get_playlist(playlist_id, user_id)
    if not pl:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return pl


@router.post("/{playlist_id}/items")
def add_item(playlist_id: int, req: AddItem, user_id: int = Depends(get_current_user_id)):
    pl = database.get_playlist(playlist_id, user_id)
    if not pl:
        raise HTTPException(status_code=404, detail="Playlist not found")
    item_id = database.add_to_playlist(playlist_id, req.path, req.title)
    return {"id": item_id, "status": "ok"}


@router.delete("/{playlist_id}/items/{item_id}")
def remove_item(playlist_id: int, item_id: int, user_id: int = Depends(get_current_user_id)):
    pl = database.get_playlist(playlist_id, user_id)
    if not pl:
        raise HTTPException(status_code=404, detail="Playlist not found")
    database.remove_from_playlist(playlist_id, item_id)
    return {"status": "ok"}


@router.delete("/{playlist_id}")
def delete_playlist(playlist_id: int, user_id: int = Depends(get_current_user_id)):
    database.delete_playlist(playlist_id, user_id)
    return {"status": "ok"}


# ── Ratings & Reviews ─────────────────────────────────────────────────────────

ratings_router = APIRouter(prefix="/api/ratings", tags=["ratings"])


@ratings_router.post("")
def rate_media(req: RateRequest, user_id: int = Depends(get_current_user_id)):
    if not 1 <= req.rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be 1-5")
    database.set_rating(user_id, req.path, req.rating, req.review)
    return {"status": "ok"}


@ratings_router.get("")
def get_my_rating(path: str, user_id: int = Depends(get_current_user_id)):
    r = database.get_rating(user_id, path)
    return r or {"rating": None}


@ratings_router.get("/all")
def get_all_ratings(path: str, user_id: int = Depends(get_current_user_id)):
    return database.get_ratings_for_path(path)


@ratings_router.delete("")
def delete_my_rating(path: str, user_id: int = Depends(get_current_user_id)):
    database.delete_rating(user_id, path)
    return {"status": "ok"}
