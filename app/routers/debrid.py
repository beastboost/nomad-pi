"""Real-Debrid integration router for Nomad Pi.

Provides endpoints for:
- Configuring RD API key
- Searching torrents via Torrentio
- Adding magnets to Real-Debrid
- Streaming directly from RD
- Downloading to Pi with auto-organization
- Download progress tracking
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import database
from app.routers.auth import get_current_user_id, get_current_admin
from app.services import debrid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/debrid", tags=["debrid"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RDKeyRequest(BaseModel):
    api_key: str

class MagnetRequest(BaseModel):
    info_hash: str
    file_idx: Optional[int] = None

class DownloadRequest(BaseModel):
    download_url: str
    filename: str
    category: str = "auto"
    is_show: bool = False

class SelectFilesRequest(BaseModel):
    torrent_id: str
    file_ids: str = "all"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.post("/settings/key")
def set_rd_key(req: RDKeyRequest, admin: dict = Depends(get_current_admin)):
    """Save Real-Debrid API key (admin only)."""
    try:
        user_info = debrid.get_rd_user(req.api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid API key: {e}")

    database.set_setting("rd_api_key", req.api_key)
    return {
        "status": "ok",
        "user": {
            "username": user_info.get("username"),
            "email": user_info.get("email"),
            "premium": user_info.get("premium", 0),
            "expiration": user_info.get("expiration"),
        }
    }


@router.get("/settings/key")
def get_rd_key_status(user_id: int = Depends(get_current_user_id)):
    """Check if RD API key is configured and valid."""
    api_key = database.get_setting("rd_api_key")
    if not api_key:
        return {"configured": False}

    try:
        user_info = debrid.get_rd_user(api_key)
        return {
            "configured": True,
            "user": {
                "username": user_info.get("username"),
                "premium": user_info.get("premium", 0),
                "expiration": user_info.get("expiration"),
            }
        }
    except Exception:
        return {"configured": True, "valid": False, "error": "API key is invalid or expired"}


@router.delete("/settings/key")
def remove_rd_key(admin: dict = Depends(get_current_admin)):
    """Remove stored RD API key."""
    database.set_setting("rd_api_key", "")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@router.get("/search")
def search_torrents(
    query: str = "",
    imdb_id: str = "",
    media_type: str = Query("movie", regex="^(movie|series)$"),
    season: Optional[int] = None,
    episode: Optional[int] = None,
    user_id: int = Depends(get_current_user_id),
):
    """Search for torrents via Torrentio.

    Requires either an IMDB ID for direct lookup or a text query
    (which will be searched via OMDb/TMDB first for the IMDB ID).
    """
    actual_imdb_id = imdb_id

    # If no IMDB ID but we have a text query, try to find via OMDb
    if not actual_imdb_id and query:
        omdb_key = database.get_setting("omdb_api_key")
        if omdb_key:
            try:
                import requests as req
                r = req.get(
                    "https://www.omdbapi.com/",
                    params={"apikey": omdb_key, "s": query, "type": media_type},
                    timeout=10,
                )
                data = r.json()
                if data.get("Response") == "True" and data.get("Search"):
                    # Return search results for user to pick
                    return {
                        "type": "search_results",
                        "results": [
                            {
                                "title": item.get("Title"),
                                "year": item.get("Year"),
                                "imdb_id": item.get("imdbID"),
                                "poster": item.get("Poster") if item.get("Poster") != "N/A" else None,
                                "type": item.get("Type"),
                            }
                            for item in data["Search"][:10]
                        ],
                    }
            except Exception as e:
                logger.warning(f"OMDb search failed: {e}")

        if not actual_imdb_id:
            return {"type": "search_results", "results": [], "message": "No results found. Try searching with an IMDB ID."}

    if not actual_imdb_id:
        raise HTTPException(status_code=400, detail="IMDB ID required for torrent search")

    results = debrid.search_torrentio(
        query=query,
        media_type=media_type,
        imdb_id=actual_imdb_id,
        season=season,
        episode=episode,
    )

    return {"type": "torrents", "results": results, "imdb_id": actual_imdb_id}


# ---------------------------------------------------------------------------
# Real-Debrid torrent operations
# ---------------------------------------------------------------------------

def _require_rd_key() -> str:
    api_key = database.get_setting("rd_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Real-Debrid API key not configured")
    return api_key


@router.post("/magnet")
def add_magnet(req: MagnetRequest, user_id: int = Depends(get_current_user_id)):
    """Add a magnet to Real-Debrid and select files."""
    api_key = _require_rd_key()

    try:
        result = debrid.add_magnet(api_key, req.info_hash)
        torrent_id = result.get("id")

        if not torrent_id:
            raise HTTPException(status_code=500, detail="Failed to get torrent ID from Real-Debrid")

        # Select files (all by default, or specific file index)
        file_ids = "all"
        if req.file_idx is not None:
            file_ids = str(req.file_idx)

        debrid.select_files(api_key, torrent_id, file_ids)

        # Get torrent info with links
        info = debrid.get_torrent_info(api_key, torrent_id)

        return {
            "status": "ok",
            "torrent_id": torrent_id,
            "filename": info.get("filename"),
            "filesize": info.get("bytes"),
            "progress": info.get("progress"),
            "torrent_status": info.get("status"),
            "links": info.get("links", []),
            "files": [
                {
                    "id": f.get("id"),
                    "path": f.get("path"),
                    "bytes": f.get("bytes"),
                    "selected": f.get("selected"),
                }
                for f in info.get("files", [])
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add magnet failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/select-files")
def select_torrent_files(req: SelectFilesRequest, user_id: int = Depends(get_current_user_id)):
    """Select specific files from a torrent."""
    api_key = _require_rd_key()
    try:
        debrid.select_files(api_key, req.torrent_id, req.file_ids)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/torrent/{torrent_id}")
def get_torrent_status(torrent_id: str, user_id: int = Depends(get_current_user_id)):
    """Get torrent status and download links."""
    api_key = _require_rd_key()
    try:
        info = debrid.get_torrent_info(api_key, torrent_id)
        return {
            "torrent_id": torrent_id,
            "filename": info.get("filename"),
            "bytes": info.get("bytes"),
            "progress": info.get("progress"),
            "status": info.get("status"),
            "links": info.get("links", []),
            "speed": info.get("speed"),
            "seeders": info.get("seeders"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/unrestrict")
def unrestrict(link: str = Query(...), user_id: int = Depends(get_current_user_id)):
    """Unrestrict a Real-Debrid link to get a direct download/stream URL."""
    api_key = _require_rd_key()
    try:
        result = debrid.unrestrict_link(api_key, link)
        return {
            "download": result.get("download"),
            "filename": result.get("filename"),
            "filesize": result.get("filesize"),
            "host": result.get("host"),
            "streaming": result.get("streaming"),
            "id": result.get("id"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Stream from RD (proxy for video player)
# ---------------------------------------------------------------------------

@router.get("/stream-url")
def get_stream_url(link: str = Query(...), user_id: int = Depends(get_current_user_id)):
    """Get a direct streaming URL from a Real-Debrid link.

    The frontend can use this URL directly in the video player.
    """
    api_key = _require_rd_key()
    try:
        result = debrid.unrestrict_link(api_key, link)
        return {
            "stream_url": result.get("download"),
            "filename": result.get("filename"),
            "filesize": result.get("filesize"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Download to Pi
# ---------------------------------------------------------------------------

@router.post("/download")
def start_download(req: DownloadRequest, user_id: int = Depends(get_current_user_id)):
    """Download a file from Real-Debrid to the Pi's media library."""
    try:
        download_id = debrid.download_to_pi(
            api_key=_require_rd_key(),
            download_url=req.download_url,
            filename=req.filename,
            category=req.category,
            is_show=req.is_show,
        )
        return {"status": "ok", "download_id": download_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/downloads")
def list_downloads(user_id: int = Depends(get_current_user_id)):
    """List all active/completed downloads to Pi."""
    return {"downloads": debrid.get_all_downloads()}


@router.get("/downloads/{download_id}")
def get_download(download_id: str, user_id: int = Depends(get_current_user_id)):
    """Get status of a specific download."""
    status = debrid.get_download_status(download_id)
    if not status:
        raise HTTPException(status_code=404, detail="Download not found")
    return status


@router.delete("/downloads/{download_id}")
def cancel_download(download_id: str, user_id: int = Depends(get_current_user_id)):
    """Cancel a download."""
    if debrid.cancel_download(download_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Download not found")


@router.post("/downloads/clear")
def clear_downloads(user_id: int = Depends(get_current_user_id)):
    """Clear completed/failed downloads from the list."""
    count = debrid.clear_completed()
    return {"status": "ok", "cleared": count}


# ---------------------------------------------------------------------------
# RD library (user's existing downloads/torrents on RD)
# ---------------------------------------------------------------------------

@router.get("/rd-downloads")
def list_rd_downloads(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
):
    """List user's download history on Real-Debrid."""
    api_key = _require_rd_key()
    try:
        downloads = debrid.get_rd_downloads(api_key, page, limit)
        return {"downloads": downloads}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rd-torrents")
def list_rd_torrents(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
):
    """List user's torrents on Real-Debrid."""
    api_key = _require_rd_key()
    try:
        torrents = debrid.get_rd_torrents(api_key, page, limit)
        return {"torrents": torrents}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/rd-torrents/{torrent_id}")
def delete_rd_torrent(torrent_id: str, user_id: int = Depends(get_current_user_id)):
    """Delete a torrent from Real-Debrid."""
    api_key = _require_rd_key()
    try:
        debrid.delete_rd_torrent(api_key, torrent_id)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
