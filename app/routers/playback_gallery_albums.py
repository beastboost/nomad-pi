"""Albums and bulk organization for profile-private Nomad Photos."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
import shutil
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.routers import playback_gallery as gallery


router = APIRouter()


class AlbumBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class AlbumRenameBody(BaseModel):
    old_name: str = Field(min_length=1, max_length=120)
    new_name: str = Field(min_length=1, max_length=120)


class MoveBody(BaseModel):
    item_ids: List[str] = Field(default_factory=list)
    album: str = Field(default="", max_length=120)


class BulkDeleteBody(BaseModel):
    item_ids: List[str] = Field(default_factory=list)


def _clean_album(value: str, *, allow_empty: bool = False) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    if not raw:
        if allow_empty:
            return ""
        raise HTTPException(status_code=400, detail="Album name is required")
    if raw in {".", ".."} or raw.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid album name")
    if any(ch in raw for ch in ("/", "\\", "\x00")):
        raise HTTPException(status_code=400, detail="Album names cannot contain path separators")
    if any(ord(ch) < 32 for ch in raw):
        raise HTTPException(status_code=400, detail="Invalid album name")
    if len(raw) > 120:
        raise HTTPException(status_code=400, detail="Album name is too long")
    return raw


def _albums_root(user_id: int, profile_id: int) -> Path:
    root = gallery._private_root(int(user_id), int(profile_id)) / "Albums"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _album_for_path(path: Path, albums_root: Path) -> str:
    try:
        rel = path.resolve().relative_to(albums_root.resolve())
    except ValueError:
        return ""
    if len(rel.parts) < 2:
        return ""
    return rel.parts[0]


def _cached_path(user_id: int, profile_id: int, item_id: str):
    with gallery._CACHE_LOCK:
        raw = gallery._CACHE.get((int(user_id), int(profile_id), str(item_id)))
    return Path(raw).resolve() if raw else None


def _clear_profile_cache(user_id: int, profile_id: int) -> None:
    with gallery._CACHE_LOCK:
        stale = [key for key in gallery._CACHE if key[0] == int(user_id) and key[1] == int(profile_id)]
        for key in stale:
            gallery._CACHE.pop(key, None)


def _unique_destination(root: Path, source: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / source.name
    if not candidate.exists():
        return candidate
    stem, suffix = source.stem, source.suffix
    for index in range(2, 10000):
        candidate = root / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise HTTPException(status_code=409, detail=f"Could not choose a unique name for {source.name}")


def _library_destination(base: Path, path: Path) -> Path:
    try:
        dt = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        dt = datetime.now()
    return base / "Library" / f"{dt.year:04d}" / f"{dt.month:02d}"


def _remove_empty_parents(path: Path, stop: Path) -> None:
    current = path.resolve()
    stop = stop.resolve()
    while current != stop:
        try:
            current.relative_to(stop)
        except ValueError:
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


@router.get("/gallery/albums")
def list_albums(request: Request, user_id: int = Depends(get_current_user_id)):
    profile = gallery._active_profile(request, int(user_id))
    items = gallery._scan(int(user_id), profile, limit=3000)
    albums_root = _albums_root(int(user_id), profile.id)
    counts = {}
    item_albums = {}
    for item in items:
        path = _cached_path(int(user_id), profile.id, item["id"])
        album = _album_for_path(path, albums_root) if path else ""
        item_albums[item["id"]] = album
        if album:
            counts[album] = counts.get(album, 0) + 1

    # Include deliberately-created empty albums as well.
    try:
        for child in albums_root.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                counts.setdefault(child.name, 0)
    except OSError:
        pass

    return {
        "albums": [{"name": name, "count": counts[name]} for name in sorted(counts, key=str.casefold)],
        "item_albums": item_albums,
        "profile_id": profile.id,
    }


@router.post("/gallery/albums")
def create_album(body: AlbumBody, request: Request, user_id: int = Depends(get_current_user_id)):
    profile = gallery._active_profile(request, int(user_id))
    name = _clean_album(body.name)
    root = _albums_root(int(user_id), profile.id)
    destination = (root / name).resolve()
    if not gallery._within(destination, root):
        raise HTTPException(status_code=400, detail="Invalid album path")
    destination.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "name": name}


@router.post("/gallery/albums/rename")
def rename_album(body: AlbumRenameBody, request: Request, user_id: int = Depends(get_current_user_id)):
    profile = gallery._active_profile(request, int(user_id))
    old_name = _clean_album(body.old_name)
    new_name = _clean_album(body.new_name)
    root = _albums_root(int(user_id), profile.id)
    source = (root / old_name).resolve()
    destination = (root / new_name).resolve()
    if not gallery._within(source, root) or not gallery._within(destination, root):
        raise HTTPException(status_code=400, detail="Invalid album path")
    if not source.is_dir():
        raise HTTPException(status_code=404, detail="Album not found")
    if destination.exists():
        raise HTTPException(status_code=409, detail="An album with that name already exists")
    source.rename(destination)
    _clear_profile_cache(int(user_id), profile.id)
    return {"ok": True, "name": new_name}


@router.post("/gallery/move")
def move_items(body: MoveBody, request: Request, user_id: int = Depends(get_current_user_id)):
    profile = gallery._active_profile(request, int(user_id))
    ids = [str(item).strip() for item in body.item_ids if str(item).strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="Select at least one photo")
    if len(ids) > 500:
        raise HTTPException(status_code=400, detail="Move at most 500 items at once")

    album = _clean_album(body.album, allow_empty=True)
    base = gallery._private_root(int(user_id), profile.id).resolve()
    albums_root = _albums_root(int(user_id), profile.id)
    destination_root = (albums_root / album).resolve() if album else None
    if destination_root is not None:
        if not gallery._within(destination_root, albums_root):
            raise HTTPException(status_code=400, detail="Invalid album path")
        destination_root.mkdir(parents=True, exist_ok=True)

    moved = 0
    skipped = 0
    for item_id in ids:
        try:
            source = gallery._resolve_item(int(user_id), profile, item_id).resolve()
            target_root = destination_root or _library_destination(base, source)
            target = _unique_destination(target_root, source).resolve()
            if not gallery._within(target, base):
                raise HTTPException(status_code=400, detail="Invalid gallery destination")
            if source == target:
                skipped += 1
                continue
            old_parent = source.parent
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            if gallery._within(old_parent, base):
                _remove_empty_parents(old_parent, base)
            moved += 1
        except HTTPException:
            raise
        except OSError:
            skipped += 1

    _clear_profile_cache(int(user_id), profile.id)
    return {"ok": True, "moved": moved, "skipped": skipped, "album": album}


@router.post("/gallery/bulk-delete")
def bulk_delete(body: BulkDeleteBody, request: Request, user_id: int = Depends(get_current_user_id)):
    profile = gallery._active_profile(request, int(user_id))
    ids = [str(item).strip() for item in body.item_ids if str(item).strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="Select at least one photo")
    if len(ids) > 500:
        raise HTTPException(status_code=400, detail="Delete at most 500 items at once")

    base = gallery._private_root(int(user_id), profile.id).resolve()
    deleted = 0
    skipped = 0
    for item_id in ids:
        try:
            path = gallery._resolve_item(int(user_id), profile, item_id).resolve()
            if not gallery._within(path, base):
                skipped += 1
                continue
            parent = path.parent
            path.unlink()
            _remove_empty_parents(parent, base)
            deleted += 1
        except HTTPException:
            skipped += 1
        except OSError:
            skipped += 1

    _clear_profile_cache(int(user_id), profile.id)
    return {"ok": True, "deleted": deleted, "skipped": skipped}
