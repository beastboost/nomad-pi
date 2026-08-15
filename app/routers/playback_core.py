"""Nomad Pi 2.x playback API: planning, sessions, tickets and HLS."""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.routers.media import safe_fs_path_from_web_path
from app.services.playback import ClientCapabilities, PlaybackMode, PlaybackPlanner
from app.services.playback.hls import HLSJobError, HLSManager
from app.services.playback.probe import ProbeError, probe_media
from app.services.playback.store import PlaybackSession, PlaybackSessionStore
from app.services.playback.tickets import StreamTicketSigner, TicketError


router = APIRouter(prefix="/api/playback", tags=["playback"])
planner = PlaybackPlanner()
session_store = PlaybackSessionStore()
ticket_signer = StreamTicketSigner()
hls_manager = HLSManager()


class ClientCapabilitiesRequest(BaseModel):
    containers: List[str] = Field(default_factory=list)
    video_codecs: List[str] = Field(default_factory=list)
    audio_codecs: List[str] = Field(default_factory=list)
    subtitle_formats: List[str] = Field(default_factory=list)
    max_width: Optional[int] = Field(default=None, gt=0)
    max_height: Optional[int] = Field(default=None, gt=0)
    max_bitrate: Optional[int] = Field(default=None, gt=0)


class PlaybackPlanRequest(BaseModel):
    path: str
    capabilities: ClientCapabilitiesRequest


class PlaybackStartRequest(PlaybackPlanRequest):
    device_id: Optional[str] = Field(default=None, max_length=200)
    quality: Optional[str] = Field(default="auto", max_length=32)
    position: float = Field(default=0, ge=0)
    audio_track: Optional[int] = Field(default=None, ge=0)
    subtitle_track: Optional[int] = Field(default=None, ge=0)


class PlaybackHeartbeatRequest(BaseModel):
    position: Optional[float] = Field(default=None, ge=0)
    duration: Optional[float] = Field(default=None, ge=0)
    state: Optional[str] = Field(default=None, max_length=32)


class PlaybackSeekRequest(BaseModel):
    position: float = Field(ge=0)


def _client_capabilities(caps: ClientCapabilitiesRequest) -> ClientCapabilities:
    return ClientCapabilities.from_values(
        containers=caps.containers,
        video_codecs=caps.video_codecs,
        audio_codecs=caps.audio_codecs,
        subtitle_formats=caps.subtitle_formats,
        max_width=caps.max_width,
        max_height=caps.max_height,
        max_bitrate=caps.max_bitrate,
    )


def _resolve_and_probe(web_path: str):
    try:
        fs_path = safe_fs_path_from_web_path(web_path)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media path")
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="Media file not found")
    try:
        source = probe_media(fs_path)
    except ProbeError as exc:
        message = str(exc)
        status_code = 503 if "not installed" in message else 422
        raise HTTPException(status_code=status_code, detail=message)
    return fs_path, source


def _plan_dict(source, plan) -> dict:
    return {
        "mode": plan.mode.value,
        "requires_ffmpeg": plan.requires_ffmpeg,
        "reasons": list(plan.reasons),
        "source": {
            "container": source.container,
            "video_codec": source.video_codec,
            "audio_codec": source.audio_codec,
            "width": source.width,
            "height": source.height,
            "bitrate": source.bitrate,
        },
        "target": {
            "container": plan.target_container,
            "video_codec": plan.target_video_codec,
            "audio_codec": plan.target_audio_codec,
        },
    }


def _metadata_for_session(source, plan, caps: ClientCapabilitiesRequest) -> dict:
    return {
        "source": {
            "container": source.container,
            "video_codec": source.video_codec,
            "audio_codec": source.audio_codec,
            "width": source.width,
            "height": source.height,
            "bitrate": source.bitrate,
        },
        "target": {
            "container": plan.target_container,
            "video_codec": plan.target_video_codec,
            "audio_codec": plan.target_audio_codec,
        },
        "capabilities": caps.dict(),
        "reasons": list(plan.reasons),
    }


def _playback_urls(session: PlaybackSession, ticket: str) -> dict:
    escaped = quote(ticket, safe="")
    if session.mode == PlaybackMode.DIRECT_PLAY.value:
        return {
            "type": "direct",
            "url": f"/api/playback/stream/{session.id}?ticket={escaped}",
        }
    return {
        "type": "hls",
        "url": f"/api/playback/hls/{session.id}/index.m3u8?ticket={escaped}",
    }


def _require_ticket_session(session_id: str, ticket: str) -> PlaybackSession:
    if not ticket:
        raise HTTPException(status_code=401, detail="Stream ticket required")
    try:
        payload = ticket_signer.verify(ticket, session_id=session_id)
    except TicketError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    session = session_store.get(session_id, user_id=int(payload["uid"]))
    if not session:
        raise HTTPException(status_code=404, detail="Playback session not found")
    if session.state == "stopped":
        raise HTTPException(status_code=410, detail="Playback session has stopped")
    session_store.update(session.id, user_id=session.user_id, touch=True)
    return session


def _ensure_hls(session: PlaybackSession, fs_path: Optional[str] = None) -> Path:
    metadata = session.metadata or {}
    source = metadata.get("source") or {}
    target = metadata.get("target") or {}
    caps = metadata.get("capabilities") or {}
    if fs_path is None:
        try:
            fs_path = safe_fs_path_from_web_path(session.path)
        except Exception as exc:
            raise HLSJobError("Playback source is no longer available") from exc
    if not os.path.isfile(fs_path):
        raise HLSJobError("Playback source is no longer available")

    hls_manager.ensure_job(
        session_id=session.id,
        source_path=fs_path,
        mode=session.mode,
        target_video_codec=target.get("video_codec"),
        target_audio_codec=target.get("audio_codec"),
        source_width=source.get("width"),
        source_height=source.get("height"),
        max_width=caps.get("max_width"),
        max_height=caps.get("max_height"),
        max_bitrate=caps.get("max_bitrate"),
        start_position=session.position,
    )
    return hls_manager.wait_until_ready(session.id)


@router.post("/plan")
def create_playback_plan(
    request: PlaybackPlanRequest,
    user_id: int = Depends(get_current_user_id),
):
    """Inspect a local source and return the cheapest viable playback mode."""
    _, source = _resolve_and_probe(request.path)
    plan = planner.plan(source, _client_capabilities(request.capabilities))
    return _plan_dict(source, plan)


@router.post("/start")
def start_playback(
    request: PlaybackStartRequest,
    user_id: int = Depends(get_current_user_id),
):
    """Create a persistent playback session and return a playable URL."""
    fs_path, source = _resolve_and_probe(request.path)
    plan = planner.plan(source, _client_capabilities(request.capabilities))
    if plan.mode == PlaybackMode.UNSUPPORTED:
        raise HTTPException(status_code=422, detail={
            "message": "No viable playback path for this client",
            "reasons": list(plan.reasons),
        })

    session = session_store.create(
        user_id=user_id,
        path=request.path,
        mode=plan.mode.value,
        position=request.position,
        audio_track=request.audio_track,
        subtitle_track=request.subtitle_track,
        quality=request.quality or "auto",
        device_id=request.device_id,
        metadata=_metadata_for_session(source, plan, request.capabilities),
    )

    try:
        if plan.mode == PlaybackMode.DIRECT_PLAY:
            session = session_store.update(session.id, user_id=user_id, state="ready") or session
        else:
            session_store.update(session.id, user_id=user_id, state="preparing")
            _ensure_hls(session, fs_path=fs_path)
            session = session_store.update(session.id, user_id=user_id, state="ready") or session
    except HLSJobError as exc:
        session_store.update(session.id, user_id=user_id, state="failed")
        raise HTTPException(status_code=503, detail=f"Playback preparation failed: {exc}")

    ticket = ticket_signer.issue(session_id=session.id, user_id=user_id)
    return {
        "session": session.to_dict(),
        "plan": _plan_dict(source, plan),
        "playback": _playback_urls(session, ticket),
        "ticket_expires_in": ticket_signer.ttl_seconds,
    }


@router.get("/sessions")
def list_playback_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    user_id: int = Depends(get_current_user_id),
):
    return {"sessions": [item.to_dict() for item in session_store.list_for_user(user_id, limit)]}


@router.get("/sessions/{session_id}")
def get_playback_session(session_id: str, user_id: int = Depends(get_current_user_id)):
    session = session_store.get(session_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Playback session not found")
    data = session.to_dict()
    if session.mode != PlaybackMode.DIRECT_PLAY.value:
        data["hls"] = hls_manager.status(session.id)
    return data


@router.post("/sessions/{session_id}/heartbeat")
def playback_heartbeat(
    session_id: str,
    request: PlaybackHeartbeatRequest,
    user_id: int = Depends(get_current_user_id),
):
    session = session_store.get(session_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Playback session not found")
    updated = session_store.update(
        session_id,
        user_id=user_id,
        state=request.state,
        position=request.position,
        duration=request.duration,
        touch=True,
    )
    ticket = ticket_signer.issue(session_id=session_id, user_id=user_id)
    return {
        "session": updated.to_dict() if updated else session.to_dict(),
        "ticket": ticket,
        "ticket_expires_in": ticket_signer.ttl_seconds,
    }


@router.post("/sessions/{session_id}/seek")
def seek_playback_session(
    session_id: str,
    request: PlaybackSeekRequest,
    user_id: int = Depends(get_current_user_id),
):
    """Seek to an absolute source timestamp.

    Direct-play clients can seek the original file themselves. HLS sessions
    restart ffmpeg at the requested timestamp, avoiding a long transcode from
    the beginning on low-power SBCs.
    """
    session = session_store.get(session_id, user_id=user_id)
    if not session or session.state == "stopped":
        raise HTTPException(status_code=404, detail="Active playback session not found")

    target = float(request.position)
    if session.mode == PlaybackMode.DIRECT_PLAY.value:
        updated = session_store.update(
            session_id, user_id=user_id, position=target, state="ready"
        ) or session
    else:
        hls_manager.stop(session_id, remove_cache=True)
        updated = session_store.update(
            session_id, user_id=user_id, position=target, state="preparing"
        ) or session
        try:
            _ensure_hls(updated)
        except HLSJobError as exc:
            session_store.update(session_id, user_id=user_id, state="failed")
            raise HTTPException(status_code=503, detail=f"Seek failed: {exc}")
        updated = session_store.update(
            session_id, user_id=user_id, state="ready"
        ) or updated

    ticket = ticket_signer.issue(session_id=session_id, user_id=user_id)
    return {
        "session": updated.to_dict(),
        "playback": _playback_urls(updated, ticket),
        "source_offset": target if updated.mode != PlaybackMode.DIRECT_PLAY.value else 0,
        "ticket_expires_in": ticket_signer.ttl_seconds,
    }


@router.post("/sessions/{session_id}/ticket")
def refresh_stream_ticket(session_id: str, user_id: int = Depends(get_current_user_id)):
    session = session_store.get(session_id, user_id=user_id)
    if not session or session.state == "stopped":
        raise HTTPException(status_code=404, detail="Active playback session not found")
    return {
        "ticket": ticket_signer.issue(session_id=session_id, user_id=user_id),
        "expires_in": ticket_signer.ttl_seconds,
    }


@router.delete("/sessions/{session_id}")
def stop_playback_session(session_id: str, user_id: int = Depends(get_current_user_id)):
    session = session_store.get(session_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Playback session not found")
    hls_manager.stop(session_id, remove_cache=True)
    updated = session_store.update(session_id, user_id=user_id, state="stopped")
    return {"status": "stopped", "session": updated.to_dict() if updated else session.to_dict()}


def parse_byte_range(value: Optional[str], size: int) -> Optional[Tuple[int, int]]:
    """Parse one RFC 7233 byte range. Multiple ranges are intentionally rejected."""
    if not value:
        return None
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
        start = max(0, size - suffix)
        end = size - 1
    else:
        start = int(start_raw)
        end = int(end_raw) if end_raw else size - 1
        if start >= size or end < start:
            raise ValueError("Range not satisfiable")
        end = min(end, size - 1)
    return start, end


def _file_chunks(path: str, start: int, length: int, chunk_size: int = 1024 * 1024):
    remaining = length
    with open(path, "rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/stream/{session_id}")
def stream_direct_media(session_id: str, request: Request, ticket: str = Query(...)):
    session = _require_ticket_session(session_id, ticket)
    if session.mode != PlaybackMode.DIRECT_PLAY.value:
        raise HTTPException(status_code=409, detail="This session uses HLS playback")
    try:
        fs_path = safe_fs_path_from_web_path(session.path)
    except Exception:
        raise HTTPException(status_code=404, detail="Playback source not found")
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="Playback source not found")

    size = os.path.getsize(fs_path)
    media_type = mimetypes.guess_type(fs_path)[0] or "application/octet-stream"
    try:
        byte_range = parse_byte_range(request.headers.get("range"), size)
    except ValueError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})

    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
    }
    if byte_range is None:
        headers["Content-Length"] = str(size)
        return StreamingResponse(
            _file_chunks(fs_path, 0, size),
            status_code=200,
            media_type=media_type,
            headers=headers,
        )

    start, end = byte_range
    length = end - start + 1
    headers.update({
        "Content-Length": str(length),
        "Content-Range": f"bytes {start}-{end}/{size}",
    })
    return StreamingResponse(
        _file_chunks(fs_path, start, length),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )


def _append_ticket(uri: str, ticket: str) -> str:
    separator = "&" if "?" in uri else "?"
    return f"{uri}{separator}ticket={quote(ticket, safe='')}"


def _ticketed_playlist(text: str, ticket: str) -> str:
    output = []
    map_pattern = re.compile(r'URI="([^"]+)"')
    for line in text.splitlines():
        if line.startswith("#EXT-X-MAP:"):
            line = map_pattern.sub(lambda m: f'URI="{_append_ticket(m.group(1), ticket)}"', line)
        elif line and not line.startswith("#"):
            line = _append_ticket(line, ticket)
        output.append(line)
    return "\n".join(output) + "\n"


@router.get("/hls/{session_id}/index.m3u8")
def get_hls_playlist(session_id: str, ticket: str = Query(...)):
    session = _require_ticket_session(session_id, ticket)
    if session.mode == PlaybackMode.DIRECT_PLAY.value:
        raise HTTPException(status_code=409, detail="This session uses direct playback")
    try:
        playlist = _ensure_hls(session)
    except HLSJobError as exc:
        session_store.update(session.id, user_id=session.user_id, state="failed")
        raise HTTPException(status_code=503, detail=f"HLS playback failed: {exc}")
    try:
        text = playlist.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(status_code=503, detail="HLS playlist is not ready")
    return Response(
        content=_ticketed_playlist(text, ticket),
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/hls/{session_id}/{filename}")
def get_hls_segment(session_id: str, filename: str, ticket: str = Query(...)):
    session = _require_ticket_session(session_id, ticket)
    if session.mode == PlaybackMode.DIRECT_PLAY.value:
        raise HTTPException(status_code=409, detail="This session uses direct playback")
    if filename != "init.mp4" and not re.fullmatch(r"segment_\d{5}\.m4s", filename):
        raise HTTPException(status_code=404, detail="HLS segment not found")
    path = hls_manager.session_dir(session_id) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="HLS segment not ready")
    media_type = "video/mp4" if filename == "init.mp4" else "video/iso.segment"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})
