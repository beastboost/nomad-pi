"""Audio/subtitle track APIs layered onto the Nomad 2.x playback core."""

from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.routers.media import safe_fs_path_from_web_path
from app.routers import playback_core as core
from app.services.playback.hls import HLSJobError
from app.services.playback.planner import PlaybackMode
from app.services.playback.probe import ProbeError
from app.services.playback.tracks import probe_tracks


router = APIRouter()
SUBTITLE_CACHE = Path("data/.nomad_cache/subtitles")


class AudioTrackSwitchRequest(BaseModel):
    stream_index: int = Field(ge=0)
    position: float = Field(default=0, ge=0)


def _resolve(path: str) -> str:
    try:
        fs_path = safe_fs_path_from_web_path(path)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media path")
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="Media file not found")
    return fs_path


def _tracks(fs_path: str) -> dict:
    try:
        return probe_tracks(fs_path)
    except ProbeError as exc:
        message = str(exc)
        raise HTTPException(status_code=503 if "not installed" in message else 422, detail=message)


def _ticketed_url(session_id: str, user_id: int) -> tuple[str, int]:
    ticket = core.ticket_signer.issue(session_id=session_id, user_id=user_id)
    return (
        f"/api/playback/hls/{session_id}/index.m3u8?ticket={quote(ticket, safe='')}",
        core.ticket_signer.ttl_seconds,
    )


def _subtitle_cache_path(fs_path: str, stream_index: int, offset: float = 0) -> Path:
    st = os.stat(fs_path)
    rounded_offset = round(max(0.0, float(offset or 0)), 3)
    identity = (
        f"{os.path.abspath(fs_path)}|{st.st_size}|{st.st_mtime_ns}|"
        f"{stream_index}|{rounded_offset:.3f}"
    )
    digest = hashlib.sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]
    SUBTITLE_CACHE.mkdir(parents=True, exist_ok=True)
    return SUBTITLE_CACHE / f"{digest}.vtt"


def _extract_webvtt(fs_path: str, stream_index: int, offset: float = 0) -> Path:
    offset = max(0.0, float(offset or 0))
    cached = _subtitle_cache_path(fs_path, stream_index, offset)
    if cached.is_file() and cached.stat().st_size > 0:
        return cached
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="ffmpeg is not installed")

    fd, temp_name = tempfile.mkstemp(prefix="nomad-sub-", suffix=".vtt", dir=str(SUBTITLE_CACHE))
    os.close(fd)
    try:
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        # HLS output is started at the session's absolute source position and
        # its media timeline resets to zero. Apply the same input seek here so
        # WebVTT cue times line up with that HLS timeline.
        if offset > 0:
            cmd += ["-ss", f"{offset:.3f}"]
        cmd += [
            "-i", fs_path,
            "-map", f"0:{int(stream_index)}",
            "-c:s", "webvtt",
            "-f", "webvtt",
            temp_name,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if result.returncode != 0 or not os.path.isfile(temp_name) or os.path.getsize(temp_name) == 0:
            detail = (result.stderr or result.stdout or "subtitle conversion failed").strip()
            raise HTTPException(status_code=422, detail=detail[:800])
        os.replace(temp_name, cached)
        return cached
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Subtitle conversion timed out")
    finally:
        if os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except OSError:
                pass


@router.get("/tracks")
def get_playback_tracks(
    path: str = Query(...),
    user_id: int = Depends(get_current_user_id),
):
    """Return ffprobe stream metadata suitable for player track menus."""
    fs_path = _resolve(path)
    tracks = _tracks(fs_path)
    return {
        "path": path,
        **tracks,
    }


@router.get("/sessions/{session_id}/subtitles/{stream_index}.vtt")
def embedded_subtitle_webvtt(
    session_id: str,
    stream_index: int,
    ticket: str = Query(...),
):
    """Expose a text-based embedded subtitle as ticket-protected WebVTT."""
    session = core._require_ticket_session(session_id, ticket)
    fs_path = _resolve(session.path)
    tracks = _tracks(fs_path)
    selected = next(
        (item for item in tracks.get("subtitles", []) if item.get("stream_index") == stream_index),
        None,
    )
    if not selected:
        raise HTTPException(status_code=404, detail="Subtitle stream not found")
    if not selected.get("text_supported"):
        raise HTTPException(
            status_code=422,
            detail="This subtitle is image-based and requires burn-in transcoding",
        )
    offset = session.position if session.mode != PlaybackMode.DIRECT_PLAY.value else 0.0
    vtt_path = _extract_webvtt(fs_path, stream_index, offset=offset)
    return FileResponse(
        vtt_path,
        media_type="text/vtt; charset=utf-8",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/sessions/{session_id}/audio")
def switch_audio_track(
    session_id: str,
    request: AudioTrackSwitchRequest,
    user_id: int = Depends(get_current_user_id),
):
    """Switch embedded audio while keeping the same absolute playback time.

    Browser native multi-audio handling is inconsistent. Nomad therefore
    creates a replacement HLS session mapped to the chosen ffprobe stream.
    H.264/AAC media is remuxed; other selected audio is converted to AAC while
    video is copied whenever the existing playback plan permits it.

    The current session is kept alive until the replacement HLS playlist is
    proven ready. A failed remux/transcode therefore cannot interrupt playback
    that was already working.
    """
    old = core.session_store.get(session_id, user_id=user_id)
    if not old or old.state == "stopped":
        raise HTTPException(status_code=404, detail="Active playback session not found")

    fs_path = _resolve(old.path)
    tracks = _tracks(fs_path)
    selected = next(
        (item for item in tracks.get("audio", []) if item.get("stream_index") == request.stream_index),
        None,
    )
    if not selected:
        raise HTTPException(status_code=404, detail="Audio stream not found")

    metadata = copy.deepcopy(old.metadata or {})
    caps = metadata.get("capabilities") or {}
    target = metadata.setdefault("target", {})
    source = metadata.get("source") or {}
    audio_codec = str(selected.get("codec") or "").lower()
    client_audio = {str(x).lower() for x in (caps.get("audio_codecs") or [])}

    if old.mode == PlaybackMode.TRANSCODE_VIDEO.value:
        mode = PlaybackMode.TRANSCODE_VIDEO.value
        if audio_codec == "aac":
            target["audio_codec"] = None
        elif "aac" in client_audio:
            target["audio_codec"] = "aac"
        else:
            raise HTTPException(status_code=422, detail="Client cannot accept a safe HLS audio format")
    else:
        if audio_codec == "aac":
            mode = PlaybackMode.REMUX.value
            target["audio_codec"] = None
        elif "aac" in client_audio:
            mode = PlaybackMode.TRANSCODE_AUDIO.value
            target["audio_codec"] = "aac"
        else:
            raise HTTPException(status_code=422, detail="Client cannot accept a safe HLS audio format")

    metadata["selected_audio"] = selected
    position = max(0.0, float(request.position or 0))

    replacement = core.session_store.create(
        user_id=user_id,
        path=old.path,
        mode=mode,
        position=position,
        audio_track=request.stream_index,
        subtitle_track=old.subtitle_track,
        quality=old.quality,
        device_id=old.device_id,
        metadata=metadata,
    )
    core.session_store.update(replacement.id, user_id=user_id, state="preparing")

    try:
        core.hls_manager.ensure_job(
            session_id=replacement.id,
            source_path=fs_path,
            mode=replacement.mode,
            target_video_codec=target.get("video_codec"),
            target_audio_codec=target.get("audio_codec"),
            audio_stream_index=request.stream_index,
            source_width=source.get("width"),
            source_height=source.get("height"),
            max_width=caps.get("max_width"),
            max_height=caps.get("max_height"),
            max_bitrate=caps.get("max_bitrate"),
            start_position=position,
        )
        core.hls_manager.wait_until_ready(replacement.id)
    except HLSJobError as exc:
        core.hls_manager.stop(replacement.id, remove_cache=True)
        core.session_store.update(replacement.id, user_id=user_id, state="failed")
        raise HTTPException(status_code=503, detail=f"Audio switch failed: {exc}")

    replacement = core.session_store.update(
        replacement.id, user_id=user_id, state="ready"
    ) or replacement

    # Only retire the old stream once the replacement is known to be playable.
    core.hls_manager.stop(old.id, remove_cache=True)
    core.session_store.update(old.id, user_id=user_id, state="stopped")

    url, expires = _ticketed_url(replacement.id, user_id)
    return {
        "replaced_session_id": old.id,
        "session": replacement.to_dict(),
        "track": selected,
        "source_offset": position,
        "playback": {"type": "hls", "url": url},
        "ticket_expires_in": expires,
    }
