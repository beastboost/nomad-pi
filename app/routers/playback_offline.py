"""Persistent prepared-offline-copy API for Nomad Pi."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.routers import media
from app.services.offline_sync import OfflineSyncManager, OfflineSyncStore, QUALITY
from app.services.playback.tickets import StreamTicketSigner, TicketError


router = APIRouter()
store = OfflineSyncStore()
manager = OfflineSyncManager(store)
ticket_signer = StreamTicketSigner()
manager.start_dispatcher()


class OfflineCreateRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4000)
    quality: str = Field(default="720p", max_length=32)


def _public(job) -> dict:
    data = job.to_dict(include_fs=False)
    data["ready"] = bool(job.status == "ready" and job.output_path and os.path.isfile(job.output_path))
    if data["ready"]:
        data["download"] = {"ticket_required": True, "filename": job.output_name}
    return data


def _resolve_local(path: str) -> str:
    try:
        fs_path = media.safe_fs_path_from_web_path(path)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media path")
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="Media file not found")
    return fs_path


@router.get("/offline/profiles")
def offline_profiles(user_id: int = Depends(get_current_user_id)):
    return {
        "profiles": [
            {"id": key, **value} for key, value in QUALITY.items()
        ]
    }


@router.post("/offline")
def create_offline_copy(
    request: OfflineCreateRequest,
    user_id: int = Depends(get_current_user_id),
):
    quality = request.quality.strip().lower()
    if quality not in QUALITY:
        raise HTTPException(status_code=400, detail="Unknown offline quality profile")
    fs_path = _resolve_local(request.path)

    existing = store.find_existing(
        user_id=user_id,
        source_path=request.path,
        quality=quality,
    )
    if existing:
        if existing.status == "ready" and existing.output_path and os.path.isfile(existing.output_path):
            return {"created": False, "job": _public(existing)}
        if existing.status in {"queued", "preparing", "running"}:
            manager.start(existing)
            return {"created": False, "job": _public(existing)}

    job = store.create(
        user_id=user_id,
        source_path=request.path,
        source_fs_path=fs_path,
        quality=quality,
        metadata={"source_name": os.path.basename(fs_path)},
    )
    manager.start(job)
    return {"created": True, "job": _public(job)}


@router.get("/offline")
def list_offline_copies(
    limit: int = Query(default=200, ge=1, le=1000),
    user_id: int = Depends(get_current_user_id),
):
    jobs = store.list_for_user(user_id, limit)
    for job in jobs:
        if job.status == "queued":
            manager.start(job)
    return {"jobs": [_public(job) for job in jobs]}


@router.get("/offline/{job_id}")
def offline_copy_status(
    job_id: str,
    user_id: int = Depends(get_current_user_id),
):
    job = store.get(job_id, user_id=user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Offline copy job not found")
    if job.status == "queued":
        manager.start(job)
    return {"job": _public(job)}


@router.post("/offline/{job_id}/retry")
def retry_offline_copy(
    job_id: str,
    user_id: int = Depends(get_current_user_id),
):
    job = store.get(job_id, user_id=user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Offline copy job not found")
    return {"job": _public(manager.retry(job))}


@router.post("/offline/{job_id}/ticket")
def offline_download_ticket(
    job_id: str,
    user_id: int = Depends(get_current_user_id),
):
    job = store.get(job_id, user_id=user_id)
    if not job or job.status != "ready" or not job.output_path or not os.path.isfile(job.output_path):
        raise HTTPException(status_code=404, detail="Prepared offline copy is not ready")
    ticket = ticket_signer.issue(session_id=f"offline:{job.id}", user_id=user_id)
    return {
        "url": f"/api/playback/offline/{job.id}/download?ticket={quote(ticket, safe='')}",
        "expires_in": ticket_signer.ttl_seconds,
        "filename": job.output_name,
    }


@router.get("/offline/{job_id}/download")
def download_offline_copy(
    job_id: str,
    ticket: str = Query(...),
):
    try:
        payload = ticket_signer.verify(ticket, session_id=f"offline:{job_id}")
    except TicketError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    job = store.get(job_id, user_id=int(payload["uid"]))
    if not job or job.status != "ready" or not job.output_path:
        raise HTTPException(status_code=404, detail="Prepared offline copy is not ready")
    path = Path(job.output_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Prepared file no longer exists")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=job.output_name or path.name,
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete("/offline/{job_id}")
def delete_offline_copy(
    job_id: str,
    user_id: int = Depends(get_current_user_id),
):
    job = store.get(job_id, user_id=user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Offline copy job not found")
    return {"job": _public(manager.delete(job))}
