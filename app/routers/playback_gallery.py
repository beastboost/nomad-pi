"""Profile-scoped gallery library and lightweight photo/video streaming.

The generic media index is intentionally not used here. Household profiles get
separate gallery roots so changing profile changes the photo library as well as
watch history/content policy. Existing files directly below data/gallery remain
visible to the account's default profile for backwards compatibility.

New private photos live outside ``data/`` entirely. Nomad mounts ``data/`` at
``/data`` for legacy media streaming, so storing private profile photos there
would make a guessed raw URL an account-level bypass. The private gallery is
only exposed through the profile-aware endpoints in this router.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import mimetypes
import os
from pathlib import Path
import threading
from typing import Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse

from app import database
from app.routers.auth import _extract_auth_token, get_current_user_id
from app.services.household_profiles import HouseholdProfile, HouseholdProfileStore


router = APIRouter()
store = HouseholdProfileStore(database.DB_PATH)

_GALLERY_ROOT = Path("data/gallery").resolve()
_PRIVATE_ROOT = Path("private/gallery").resolve()
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif"}
_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
_ALLOWED_EXT = _IMAGE_EXT | _VIDEO_EXT
_CACHE: Dict[Tuple[int, int, str], str] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 6000


def _requested_profile_id(request: Request) -> Optional[int]:
    raw = request.headers.get("X-Nomad-Profile-ID") or request.query_params.get("profile_id")
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid profile context")
    return value if value > 0 else None


def _active_profile(request: Request, user_id: int) -> HouseholdProfile:
    """Resolve the session-bound household profile and reject profile spoofing."""
    token = _extract_auth_token(request)
    requested = _requested_profile_id(request)
    bound = None
    if token:
        try:
            bound = store.binding(user_id=int(user_id), token=token)
        except Exception:
            bound = None

    if bound and requested is not None and int(bound.id) != int(requested):
        raise HTTPException(status_code=409, detail="Gallery belongs to the active profile; switch profiles first")

    if bound:
        return bound

    if requested is not None:
        profile = store.get(int(user_id), int(requested))
        if not profile:
            raise HTTPException(status_code=403, detail="Profile does not belong to this account")
        if profile.pin_required:
            raise HTTPException(status_code=423, detail="This profile requires its PIN; switch profiles first")
        if token:
            try:
                store.bind(user_id=int(user_id), token=token, profile_id=profile.id)
            except Exception:
                pass
        return profile

    profile = store.default(int(user_id))
    if token:
        try:
            store.bind(user_id=int(user_id), token=token, profile_id=profile.id)
        except Exception:
            pass
    return profile


def _private_root(user_id: int, profile_id: int) -> Path:
    root = (_PRIVATE_ROOT / f"u{int(user_id)}" / f"p{int(profile_id)}").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _legacy_allowed(profile: HouseholdProfile) -> bool:
    return bool(profile.is_default)


def _roots(user_id: int, profile: HouseholdProfile) -> List[Path]:
    roots = [_private_root(user_id, profile.id)]
    if _legacy_allowed(profile):
        _GALLERY_ROOT.mkdir(parents=True, exist_ok=True)
        roots.append(_GALLERY_ROOT)
    return roots


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _iter_root(root: Path, *, legacy: bool = False) -> Iterable[Path]:
    if not root.is_dir():
        return
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"profiles", ".nomad_gallery"}]
        for name in files:
            if name.startswith("."):
                continue
            path = current_path / name
            if path.suffix.lower() in _ALLOWED_EXT and path.is_file():
                yield path


def _item_id(user_id: int, profile_id: int, path: Path) -> str:
    raw = f"{int(user_id)}:{int(profile_id)}:{path.resolve()}".encode("utf-8", errors="surrogatepass")
    return hashlib.sha256(raw).hexdigest()[:28]


def _remember(user_id: int, profile_id: int, item_id: str, path: Path) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[(int(user_id), int(profile_id), item_id)] = str(path.resolve())


def _media_kind(path: Path) -> str:
    return "video" if path.suffix.lower() in _VIDEO_EXT else "image"


def _scan(user_id: int, profile: HouseholdProfile, limit: int = 1200) -> List[dict]:
    rows: List[dict] = []
    seen = set()
    for root in _roots(user_id, profile):
        legacy = root == _GALLERY_ROOT
        for path in _iter_root(root, legacy=legacy):
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                stat = path.stat()
            except OSError:
                continue
            iid = _item_id(user_id, profile.id, path)
            _remember(user_id, profile.id, iid, path)
            rows.append({
                "id": iid,
                "name": path.name,
                "kind": _media_kind(path),
                "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "size": int(stat.st_size),
                "mtime": float(stat.st_mtime),
                "taken_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "legacy": bool(legacy),
            })
    rows.sort(key=lambda row: (-float(row.get("mtime") or 0), str(row.get("name") or "").lower()))
    return rows[: max(1, min(int(limit or 1200), 3000))]


def _resolve_item(user_id: int, profile: HouseholdProfile, item_id: str) -> Path:
    key = (int(user_id), int(profile.id), str(item_id))
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached:
        path = Path(cached).resolve()
        if path.is_file() and path.suffix.lower() in _ALLOWED_EXT and any(_within(path, root) for root in _roots(user_id, profile)):
            return path

    _scan(user_id, profile, limit=3000)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if not cached:
        raise HTTPException(status_code=404, detail="Gallery item not found")
    path = Path(cached).resolve()
    if not path.is_file() or not any(_within(path, root) for root in _roots(user_id, profile)):
        raise HTTPException(status_code=404, detail="Gallery item not found")
    return path


def _parse_range(value: Optional[str], size: int) -> Optional[Tuple[int, int]]:
    if not value:
        return None
    import re
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match:
        raise ValueError("Invalid Range header")
    start_raw, end_raw = match.groups()
    if not start_raw and not end_raw:
        raise ValueError("Invalid Range header")
    if not start_raw:
        suffix = int(end_raw)
        if suffix <= 0:
            raise ValueError("Invalid Range header")
        return max(0, size - suffix), size - 1
    start = int(start_raw)
    end = int(end_raw) if end_raw else size - 1
    if start >= size or end < start:
        raise ValueError("Range not satisfiable")
    return start, min(end, size - 1)


def _chunks(path: Path, start: int, length: int, chunk_size: int = 512 * 1024):
    remaining = length
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            block = handle.read(min(chunk_size, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def _unique_destination(root: Path, name: str) -> Path:
    clean = os.path.basename(str(name or "photo"))[:240] or "photo"
    stem = Path(clean).stem or "photo"
    suffix = Path(clean).suffix.lower()
    candidate = root / f"{stem}{suffix}"
    i = 2
    while candidate.exists() and i < 10000:
        candidate = root / f"{stem} ({i}){suffix}"
        i += 1
    return candidate


@router.get("/gallery")
def gallery_library(
    request: Request,
    limit: int = Query(default=1200, ge=1, le=3000),
    user_id: int = Depends(get_current_user_id),
):
    profile = _active_profile(request, int(user_id))
    items = _scan(int(user_id), profile, limit=limit)
    return {
        "items": items,
        "count": len(items),
        "profile": {
            "id": profile.id,
            "name": profile.name,
            "is_default": profile.is_default,
        },
        "private": True,
        "legacy_visible": bool(profile.is_default),
    }


@router.get("/gallery/item/{item_id}")
def gallery_item(
    item_id: str,
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    profile = _active_profile(request, int(user_id))
    path = _resolve_item(int(user_id), profile, item_id)
    size = path.stat().st_size
    try:
        byte_range = _parse_range(request.headers.get("range"), size)
    except ValueError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=300"}
    if byte_range is None:
        return FileResponse(path, media_type=media_type, headers=headers)

    start, end = byte_range
    length = end - start + 1
    headers.update({
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(length),
    })
    return StreamingResponse(
        _chunks(path, start, length),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )


@router.post("/gallery/upload")
async def gallery_upload(
    request: Request,
    files: List[UploadFile] = File(...),
    user_id: int = Depends(get_current_user_id),
):
    profile = _active_profile(request, int(user_id))
    base = _private_root(int(user_id), profile.id)
    now = datetime.now(timezone.utc)
    destination_root = base / f"{now.year:04d}" / f"{now.month:02d}"
    destination_root.mkdir(parents=True, exist_ok=True)

    uploaded = []
    for upload in files[:200]:
        name = os.path.basename(upload.filename or "photo")
        suffix = Path(name).suffix.lower()
        if suffix not in _ALLOWED_EXT:
            continue
        destination = _unique_destination(destination_root, name)
        total = 0
        try:
            with destination.open("wb") as out:
                while True:
                    chunk = await upload.read(512 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 2 * 1024 * 1024 * 1024:
                        raise HTTPException(status_code=413, detail=f"{name} is too large")
                    out.write(chunk)
        except Exception:
            try:
                destination.unlink(missing_ok=True)
            except Exception:
                pass
            raise
        uploaded.append({"name": destination.name, "size": total})

    with _CACHE_LOCK:
        stale = [key for key in _CACHE if key[0] == int(user_id) and key[1] == int(profile.id)]
        for key in stale:
            _CACHE.pop(key, None)
    return {"uploaded": uploaded, "count": len(uploaded), "profile_id": profile.id}


@router.delete("/gallery/item/{item_id}")
def delete_gallery_item(
    item_id: str,
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    profile = _active_profile(request, int(user_id))
    path = _resolve_item(int(user_id), profile, item_id)
    private = _private_root(int(user_id), profile.id)
    if not _within(path, private):
        raise HTTPException(status_code=409, detail="Legacy gallery items must be managed from Files")
    try:
        path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not delete gallery item: {exc}")
    with _CACHE_LOCK:
        _CACHE.pop((int(user_id), int(profile.id), item_id), None)
    return {"deleted": True}
