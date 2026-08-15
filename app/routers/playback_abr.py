"""Adaptive bitrate session API and ticket-protected ABR HLS serving."""

from __future__ import annotations

import copy
import os
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.routers.media import safe_fs_path_from_web_path
from app.routers import playback_core as core
from app.services.playback.abr import (
    ABRJobError,
    ABRManager,
    ABRRendition,
    abr_available,
    abr_policy,
    choose_renditions,
)
from app.services.playback.planner import PlaybackMode


router = APIRouter()
abr_manager = ABRManager()


class AdaptiveSwitchRequest(BaseModel):
    position: float = Field(default=0, ge=0)


def _source(metadata: dict) -> dict:
    return metadata.get("source") or {}


def _caps(metadata: dict) -> dict:
    return metadata.get("capabilities") or {}


def _renditions_from_metadata(metadata: dict) -> list[ABRRendition]:
    values = metadata.get("abr_renditions") or []
    result = []
    for item in values:
        try:
            result.append(ABRRendition(
                str(item["name"]),
                int(item["width"]),
                int(item["height"]),
                int(item["bitrate"]),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _resolve(path: str) -> str:
    try:
        fs_path = safe_fs_path_from_web_path(path)
    except Exception:
        raise HTTPException(status_code=404, detail="Playback source not found")
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="Playback source not found")
    return fs_path


def ensure_adaptive_session(session, fs_path: str | None = None):
    metadata = session.metadata or {}
    if not metadata.get("abr"):
        raise ABRJobError("Playback session is not adaptive")
    renditions = _renditions_from_metadata(metadata)
    if len(renditions) < 2:
        raise ABRJobError("Adaptive session has no valid rendition ladder")
    if fs_path is None:
        try:
            fs_path = safe_fs_path_from_web_path(session.path)
        except Exception as exc:
            raise ABRJobError("Playback source is no longer available") from exc
    if not os.path.isfile(fs_path):
        raise ABRJobError("Playback source is no longer available")

    burn = metadata.get("burn_subtitle")
    abr_manager.ensure_job(
        session_id=session.id,
        source_path=fs_path,
        renditions=renditions,
        audio_stream_index=session.audio_track,
        subtitle_stream_index=(session.subtitle_track if burn else None),
        start_position=session.position,
    )
    return abr_manager.wait_until_ready(session.id)


def adaptive_playback_url(session_id: str, user_id: int) -> tuple[str, int]:
    ticket = core.ticket_signer.issue(session_id=session_id, user_id=user_id)
    return (
        f"/api/playback/abr/{session_id}/master.m3u8?ticket={quote(ticket, safe='')}",
        core.ticket_signer.ttl_seconds,
    )


def _retire(session, user_id: int):
    # The playback facade wraps hls_manager.stop so this also terminates ABR
    # jobs when the old session itself was adaptive.
    core.hls_manager.stop(session.id, remove_cache=True)
    core.session_store.update(session.id, user_id=user_id, state="stopped")


@router.get("/adaptive/status")
def adaptive_status(user_id: int = Depends(get_current_user_id)):
    allowed, reason, candidates = abr_available()
    return {
        "policy": abr_policy(),
        "available": allowed,
        "reason": reason,
        "encoder_candidates": candidates,
        "ladder": [
            {"name": "1080p", "width": 1920, "height": 1080, "bitrate": 8_000_000},
            {"name": "720p", "width": 1280, "height": 720, "bitrate": 4_000_000},
            {"name": "480p", "width": 854, "height": 480, "bitrate": 2_000_000},
        ],
    }


@router.post("/sessions/{session_id}/adaptive")
def switch_to_adaptive(
    session_id: str,
    request: AdaptiveSwitchRequest,
    user_id: int = Depends(get_current_user_id),
):
    old = core.session_store.get(session_id, user_id=user_id)
    if not old or old.state == "stopped":
        raise HTTPException(status_code=404, detail="Active playback session not found")

    metadata = copy.deepcopy(old.metadata or {})
    source = _source(metadata)
    caps = _caps(metadata)
    allowed, reason, candidates = abr_available()
    if not allowed:
        raise HTTPException(status_code=422, detail=reason)
    if "h264" not in {str(x).lower() for x in (caps.get("video_codecs") or [])} and "avc" not in {
        str(x).lower() for x in (caps.get("video_codecs") or [])
    }:
        raise HTTPException(status_code=422, detail="Client did not report H.264 support required by the adaptive ladder")
    if source.get("audio_codec") and "aac" not in {str(x).lower() for x in (caps.get("audio_codecs") or [])}:
        raise HTTPException(status_code=422, detail="Client did not report AAC support required by adaptive HLS")

    renditions = choose_renditions(
        source.get("width"),
        source.get("height"),
        max_width=caps.get("max_width"),
        max_height=caps.get("max_height"),
        max_bitrate=caps.get("max_bitrate"),
    )
    if len(renditions) < 2:
        raise HTTPException(
            status_code=422,
            detail="Source/client limits do not permit at least two useful adaptive renditions",
        )

    fs_path = _resolve(old.path)
    metadata["abr"] = True
    metadata["abr_policy_reason"] = reason
    metadata["abr_encoder_candidates"] = candidates
    metadata["abr_renditions"] = [r.to_dict() for r in renditions]
    metadata["target"] = {
        "container": "hls",
        "video_codec": "h264",
        "audio_codec": "aac",
    }
    metadata["quality_profile"] = "adaptive"
    position = max(0.0, float(request.position or 0))

    replacement = core.session_store.create(
        user_id=user_id,
        path=old.path,
        mode=PlaybackMode.TRANSCODE_VIDEO.value,
        duration=old.duration,
        position=position,
        audio_track=old.audio_track,
        subtitle_track=old.subtitle_track,
        quality="adaptive",
        device_id=old.device_id,
        metadata=metadata,
    )
    core.session_store.update(replacement.id, user_id=user_id, state="preparing")

    try:
        ensure_adaptive_session(replacement, fs_path=fs_path)
    except ABRJobError as exc:
        abr_manager.stop(replacement.id, remove_cache=True)
        core.session_store.update(replacement.id, user_id=user_id, state="failed")
        raise HTTPException(status_code=503, detail=f"Adaptive playback preparation failed: {exc}")

    replacement = core.session_store.update(
        replacement.id, user_id=user_id, state="ready"
    ) or replacement
    _retire(old, user_id)

    url, expires = adaptive_playback_url(replacement.id, user_id)
    return {
        "replaced_session_id": old.id,
        "session": replacement.to_dict(),
        "source_offset": position,
        "playback": {"type": "hls", "url": url, "adaptive": True},
        "adaptive": {
            "renditions": [r.to_dict() for r in renditions],
            "reason": reason,
        },
        "ticket_expires_in": expires,
    }


@router.get("/abr/{session_id}/master.m3u8")
def adaptive_master(session_id: str, ticket: str = Query(...)):
    session = core._require_ticket_session(session_id, ticket)
    if not (session.metadata or {}).get("abr"):
        raise HTTPException(status_code=409, detail="This session is not adaptive")
    try:
        master = ensure_adaptive_session(session)
        text = master.read_text(encoding="utf-8")
    except (ABRJobError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"Adaptive playlist unavailable: {exc}")
    return Response(
        content=core._ticketed_playlist(text, ticket),
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/abr/{session_id}/{filename}")
def adaptive_asset(session_id: str, filename: str, ticket: str = Query(...)):
    session = core._require_ticket_session(session_id, ticket)
    if not (session.metadata or {}).get("abr"):
        raise HTTPException(status_code=409, detail="This session is not adaptive")

    allowed = (
        re.fullmatch(r"variant_[A-Za-z0-9_-]+\.m3u8", filename)
        or re.fullmatch(r"init_[A-Za-z0-9_-]+\.mp4", filename)
        or re.fullmatch(r"segment_[A-Za-z0-9_-]+_\d{5}\.m4s", filename)
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="Adaptive HLS asset not found")

    path = abr_manager.session_dir(session_id) / filename
    if not path.is_file():
        try:
            ensure_adaptive_session(session)
        except ABRJobError:
            pass
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Adaptive HLS asset not ready")

    if filename.endswith(".m3u8"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            raise HTTPException(status_code=503, detail="Adaptive variant playlist unavailable")
        return Response(
            content=core._ticketed_playlist(text, ticket),
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )
    media_type = "video/mp4" if filename.endswith(".mp4") else "video/iso.segment"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})
