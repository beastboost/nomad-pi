"""Universal, appliance-friendly debrid search and direct remote playback.

This module deliberately keeps the expensive media work out of Nomad. Search
finds releases that the browser can consume directly, cached releases are
ranked first, and a small HTTP Range proxy provides Play without FFmpeg or a
local copy. Stream + Keep and Download continue to use the existing debrid
workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
import copy
import mimetypes
import os
import secrets
import threading
import time
from typing import Optional
from urllib.parse import quote, urljoin

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
import requests

from app.routers.auth import get_current_user_id
from app.routers import debrid as debrid_router
from app.services import debrid
from app.services.debrid_lite import _analyse_release


router = APIRouter(prefix="/universal", tags=["debrid-universal"])

_SEARCH_TTL_SECONDS = 45.0
_SEARCH_CACHE_MAX = 24
_search_cache: dict[tuple, tuple[float, dict]] = {}
_search_lock = threading.Lock()

_REMOTE_TTL_SECONDS = 6 * 60 * 60
_REMOTE_MAX = 32
_remote_lock = threading.Lock()


@dataclass
class RemotePlay:
    token: str
    user_id: int
    url: str
    filename: str
    mime_type: str
    created_at: float
    last_used_at: float


_remote_plays: dict[str, RemotePlay] = {}


class RemotePlayRequest(BaseModel):
    url: str = Field(min_length=8, max_length=8000)
    filename: str = Field(default="media.mp4", max_length=500)
    mime_type: Optional[str] = Field(default=None, max_length=120)


def _provider_cached(hashes: list[str]) -> tuple[str, dict[str, bool]]:
    provider = debrid_router._provider(None)
    key = debrid_router._key_for(provider)
    normalized = [str(h or "").lower() for h in hashes if h]
    if not key or not normalized:
        return provider, {h: False for h in normalized}
    try:
        if provider == "rd":
            result = debrid.check_instant_availability(key, normalized)
        elif provider == "ad":
            result = debrid.ad_check_instant(key, normalized)
        elif provider == "tb":
            result = debrid.tb_check_instant(key, normalized)
        else:
            result = {}
    except Exception:
        result = {}
    return provider, {h: bool(result.get(h) or result.get(h.lower())) for h in normalized}


def _release_payload(results: list[dict], media_type: str, *, include_heavy: bool, limit: int) -> dict:
    enriched: list[dict] = []
    for source in results:
        item = dict(source)
        if "lite_compatible" not in item:
            item.update(_analyse_release(item, media_type))
        enriched.append(item)

    # Keep instant-availability lookups bounded. Compatibility is determined
    # from the release name first, so we do not spend provider API calls on 4K,
    # HEVC, AV1 and remux releases that the default UI will hide anyway.
    candidates = [r for r in enriched if r.get("lite_compatible")]
    if include_heavy:
        candidates += [r for r in enriched if not r.get("lite_compatible")][:8]
    hashes = [str(r.get("info_hash") or "").lower() for r in candidates[:16] if r.get("info_hash")]
    provider, cached = _provider_cached(hashes)

    for item in enriched:
        h = str(item.get("info_hash") or "").lower()
        item["cached"] = bool(cached.get(h, False))

    enriched.sort(
        key=lambda item: (
            not bool(item.get("lite_compatible")),
            not bool(item.get("cached")),
            not bool(item.get("lite_direct_candidate")),
            -float(item.get("lite_score") or 0),
            -int(item.get("seeders") or 0),
            str(item.get("name") or "").lower(),
        )
    )

    safe = [item for item in enriched if item.get("lite_compatible")]
    visible = enriched if include_heavy else safe
    visible = visible[: max(1, min(int(limit), 30))]
    return {
        "provider": provider,
        "releases": visible,
        "safe_count": len(safe),
        "cached_count": sum(1 for item in safe if item.get("cached")),
        "direct_count": sum(1 for item in safe if item.get("lite_direct_candidate")),
        "heavy_count": max(0, len(enriched) - len(safe)),
        "total_count": len(enriched),
    }


def _cinemeta_titles(query: str, media_filter: str = "all", limit: int = 6) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    kinds = ("movie", "series") if media_filter not in {"movie", "series"} else (media_filter,)
    for media_type in kinds:
        try:
            url = f"https://v3-cinemeta.strem.io/catalog/{media_type}/top/search={quote(query)}.json"
            response = requests.get(url, headers={"User-Agent": "NomadPi/2.0"}, timeout=8)
            if response.status_code != 200:
                continue
            for meta in response.json().get("metas", []):
                imdb_id = meta.get("imdb_id") or meta.get("id")
                title = meta.get("name") or ""
                if not imdb_id or not title:
                    continue
                key = (str(imdb_id), media_type)
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "imdb_id": imdb_id,
                    "title": title,
                    "year": meta.get("releaseInfo", meta.get("year", "")),
                    "type": media_type,
                    "poster": meta.get("poster"),
                })
                if len(out) >= limit:
                    return out
        except Exception:
            continue
    return out


def _releases_for_title(
    imdb_id: str,
    media_type: str,
    season: Optional[int],
    episode: Optional[int],
    *,
    include_heavy: bool = False,
    limit: int = 8,
) -> dict:
    results = debrid.search_torrentio(
        "",
        media_type=media_type,
        imdb_id=imdb_id,
        season=season if media_type == "series" else None,
        episode=episode if media_type == "series" else None,
    )
    return _release_payload(results, media_type, include_heavy=include_heavy, limit=limit)


def _cache_get(key: tuple) -> Optional[dict]:
    now = time.monotonic()
    with _search_lock:
        item = _search_cache.get(key)
        if not item:
            return None
        expires, payload = item
        if expires <= now:
            _search_cache.pop(key, None)
            return None
        return copy.deepcopy(payload)


def _cache_put(key: tuple, payload: dict) -> None:
    now = time.monotonic()
    with _search_lock:
        expired = [k for k, (expires, _payload) in _search_cache.items() if expires <= now]
        for k in expired:
            _search_cache.pop(k, None)
        while len(_search_cache) >= _SEARCH_CACHE_MAX:
            oldest = next(iter(_search_cache), None)
            if oldest is None:
                break
            _search_cache.pop(oldest, None)
        _search_cache[key] = (now + _SEARCH_TTL_SECONDS, copy.deepcopy(payload))


@router.get("/search")
def universal_search(
    q: str = Query(..., min_length=1, max_length=160),
    media_type: str = Query(default="all", pattern="^(all|movie|series)$"),
    season: int = Query(default=1, ge=1, le=999),
    episode: int = Query(default=1, ge=1, le=9999),
    user_id: int = Depends(get_current_user_id),
):
    """Search titles and hydrate the first few with Pi-friendly releases."""
    normalized = " ".join(q.split())
    provider = debrid_router._provider(None)
    cache_key = (normalized.lower(), media_type, season, episode, provider)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    titles = _cinemeta_titles(normalized, media_type, limit=6)
    hydrated = []
    # Bounded by design: universal search must remain a small-appliance feature,
    # not fan out into dozens of provider calls for every keypress.
    for index, title in enumerate(titles):
        item = dict(title)
        if index < 4:
            try:
                item["release_set"] = _releases_for_title(
                    str(title["imdb_id"]),
                    str(title["type"]),
                    season,
                    episode,
                    include_heavy=False,
                    limit=6,
                )
            except Exception as exc:
                item["release_set"] = {
                    "provider": provider,
                    "releases": [],
                    "safe_count": 0,
                    "cached_count": 0,
                    "direct_count": 0,
                    "heavy_count": 0,
                    "total_count": 0,
                    "error": str(exc),
                }
        hydrated.append(item)

    payload = {
        "query": normalized,
        "season": season,
        "episode": episode,
        "provider": provider,
        "titles": hydrated,
    }
    _cache_put(cache_key, payload)
    return payload


@router.get("/releases")
def universal_releases(
    imdb_id: str = Query(..., min_length=3, max_length=40),
    media_type: str = Query(default="movie", pattern="^(movie|series)$"),
    season: int = Query(default=1, ge=1, le=999),
    episode: int = Query(default=1, ge=1, le=9999),
    include_heavy: bool = Query(default=False),
    limit: int = Query(default=12, ge=1, le=30),
    user_id: int = Depends(get_current_user_id),
):
    return _releases_for_title(
        imdb_id,
        media_type,
        season,
        episode,
        include_heavy=include_heavy,
        limit=limit,
    )


def _purge_remote_plays() -> None:
    now = time.monotonic()
    with _remote_lock:
        stale = [token for token, item in _remote_plays.items() if now - item.last_used_at > _REMOTE_TTL_SECONDS]
        for token in stale:
            _remote_plays.pop(token, None)
        while len(_remote_plays) > _REMOTE_MAX:
            oldest = min(_remote_plays.values(), key=lambda item: item.last_used_at, default=None)
            if oldest is None:
                break
            _remote_plays.pop(oldest.token, None)


def _safe_remote_get(url: str, range_header: Optional[str], max_redirects: int = 5):
    current = url
    headers = {"User-Agent": "NomadPi/2.0"}
    if range_header:
        headers["Range"] = range_header
    for _ in range(max_redirects + 1):
        if not debrid.is_safe_external_url(current):
            raise ValueError("Unsafe remote media URL")
        response = requests.get(
            current,
            headers=headers,
            stream=True,
            allow_redirects=False,
            timeout=(8, 45),
        )
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location") or response.headers.get("location")
            response.close()
            if not location:
                raise ValueError("Remote redirect had no destination")
            current = urljoin(current, location)
            continue
        return response
    raise ValueError("Too many remote media redirects")


@router.post("/play")
def create_remote_play(
    body: RemotePlayRequest,
    user_id: int = Depends(get_current_user_id),
):
    if not debrid.is_safe_external_url(body.url):
        raise HTTPException(status_code=400, detail="Refusing to proxy a non-public media URL")
    _purge_remote_plays()
    token = secrets.token_urlsafe(24)
    mime_type = body.mime_type or mimetypes.guess_type(body.filename)[0] or "video/mp4"
    now = time.monotonic()
    with _remote_lock:
        _remote_plays[token] = RemotePlay(
            token=token,
            user_id=user_id,
            url=body.url,
            filename=body.filename,
            mime_type=mime_type,
            created_at=now,
            last_used_at=now,
        )
    return {
        "token": token,
        "playback": {
            "type": "direct",
            "url": f"/api/debrid/universal/stream/{token}",
        },
        "expires_in": int(_REMOTE_TTL_SECONDS),
    }


@router.get("/stream/{token}")
def stream_remote_play(token: str, request: Request):
    _purge_remote_plays()
    with _remote_lock:
        item = _remote_plays.get(token)
        if item:
            item.last_used_at = time.monotonic()
    if not item:
        raise HTTPException(status_code=404, detail="Remote playback session expired")

    range_header = request.headers.get("range")
    try:
        upstream = _safe_remote_get(item.url, range_header)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Remote media connection failed: {exc}")

    if upstream.status_code == 416:
        headers = {}
        if upstream.headers.get("Content-Range"):
            headers["Content-Range"] = upstream.headers["Content-Range"]
        upstream.close()
        return Response(status_code=416, headers=headers)
    if upstream.status_code >= 400:
        code = upstream.status_code
        upstream.close()
        raise HTTPException(status_code=502, detail=f"Debrid media host returned HTTP {code}")
    if range_header and upstream.status_code != 206:
        upstream.close()
        raise HTTPException(
            status_code=502,
            detail="This debrid media host did not honor byte-range seeking",
        )

    response_headers = {
        "Accept-Ranges": upstream.headers.get("Accept-Ranges", "bytes"),
        "Cache-Control": "private, no-store",
    }
    for key in ("Content-Range", "Content-Length", "ETag", "Last-Modified"):
        value = upstream.headers.get(key)
        if value:
            response_headers[key] = value
    media_type = (upstream.headers.get("Content-Type") or item.mime_type or "video/mp4").split(";", 1)[0]

    def body_iter():
        try:
            for chunk in upstream.iter_content(chunk_size=256 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        body_iter(),
        status_code=206 if upstream.status_code == 206 else 200,
        media_type=media_type,
        headers=response_headers,
    )


@router.delete("/play/{token}")
def delete_remote_play(token: str, user_id: int = Depends(get_current_user_id)):
    with _remote_lock:
        item = _remote_plays.get(token)
        if item and item.user_id == user_id:
            _remote_plays.pop(token, None)
    return {"ok": True}
