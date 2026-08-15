"""Stream + Keep: play debrid media immediately while saving a local copy."""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urljoin

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
import requests

from app.routers.auth import get_current_user_id
from app.routers import playback_core as core
from app.services import debrid
from app.services.playback.hls import HLSJobError, HLSManager
from app.services.playback.planner import ClientCapabilities, MediaProbe, PlaybackMode
from app.services.playback.tickets import StreamTicketSigner, TicketError
from app.services.stream_keep import StreamKeepManager, StreamKeepStore


router = APIRouter()
store = StreamKeepStore()
manager = StreamKeepManager(store)
ticket_signer = StreamTicketSigner()
hls_manager = HLSManager(root="data/.nomad_cache/stream-keep-hls")


class StreamKeepCapabilities(BaseModel):
    containers: List[str] = Field(default_factory=list)
    video_codecs: List[str] = Field(default_factory=list)
    audio_codecs: List[str] = Field(default_factory=list)
    subtitle_formats: List[str] = Field(default_factory=list)
    max_width: Optional[int] = Field(default=None, gt=0)
    max_height: Optional[int] = Field(default=None, gt=0)
    max_bitrate: Optional[int] = Field(default=None, gt=0)


class StreamKeepStartRequest(BaseModel):
    url: str = Field(min_length=8, max_length=8000)
    filename: str = Field(default="debrid-media", max_length=500)
    provider: str = Field(default="debrid", max_length=20)
    category: str = Field(default="auto", max_length=30)
    is_show: bool = False
    position: float = Field(default=0, ge=0)
    capabilities: StreamKeepCapabilities
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StreamKeepSeekRequest(BaseModel):
    position: float = Field(ge=0)


def _caps(value: StreamKeepCapabilities) -> ClientCapabilities:
    return ClientCapabilities.from_values(
        containers=value.containers,
        video_codecs=value.video_codecs,
        audio_codecs=value.audio_codecs,
        subtitle_formats=value.subtitle_formats,
        max_width=value.max_width,
        max_height=value.max_height,
        max_bitrate=value.max_bitrate,
    )


def _positive_int(value) -> Optional[int]:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _positive_float(value) -> Optional[float]:
    try:
        parsed = float(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _container_name(filename: str, ffprobe_name: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    aliases = {"m4v": "mp4", "m4a": "m4a", "mkv": "mkv", "mp4": "mp4", "webm": "webm", "avi": "avi", "ts": "ts", "m2ts": "m2ts"}
    if ext in aliases:
        return aliases[ext]
    first = (ffprobe_name.split(",", 1)[0] if ffprobe_name else "").strip().lower()
    return {"matroska": "mkv", "mov": "mp4", "mpegts": "ts"}.get(first, first or ext)


def _probe_remote(url: str, filename: str, timeout: int = 25) -> MediaProbe:
    if not debrid.is_safe_external_url(url):
        raise HTTPException(status_code=400, detail="Refusing to probe a non-public remote URL")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise HTTPException(status_code=503, detail="ffprobe is not installed")
    cmd = [
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_entries", "format=format_name,bit_rate,duration",
        "-show_entries", "stream=codec_type,codec_name,width,height,bit_rate",
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Remote media probe timed out")
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Could not start ffprobe: {exc}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffprobe failed").strip()
        raise HTTPException(status_code=422, detail=detail[:800])
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="ffprobe returned invalid JSON")
    video = next((s for s in payload.get("streams") or [] if s.get("codec_type") == "video"), {})
    audio = next((s for s in payload.get("streams") or [] if s.get("codec_type") == "audio"), {})
    fmt = payload.get("format") or {}
    return MediaProbe(
        container=_container_name(filename, str(fmt.get("format_name") or "")),
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name"),
        width=_positive_int(video.get("width")),
        height=_positive_int(video.get("height")),
        bitrate=_positive_int(fmt.get("bit_rate")) or _positive_int(video.get("bit_rate")) or _positive_int(audio.get("bit_rate")),
        duration=_positive_float(fmt.get("duration")),
    )


def _plan_metadata(source: MediaProbe, plan, request: StreamKeepStartRequest) -> dict:
    metadata = dict(request.metadata or {})
    metadata["remote_playback"] = {
        "mode": plan.mode.value,
        "position": float(request.position or 0),
        "source": {
            "container": source.container,
            "video_codec": source.video_codec,
            "audio_codec": source.audio_codec,
            "width": source.width,
            "height": source.height,
            "bitrate": source.bitrate,
            "duration": source.duration,
        },
        "target": {
            "container": plan.target_container,
            "video_codec": plan.target_video_codec,
            "audio_codec": plan.target_audio_codec,
        },
        "capabilities": request.capabilities.dict(),
        "reasons": list(plan.reasons),
    }
    return metadata


def _save_metadata(job, metadata: dict, **extra):
    return store.update(
        job.id,
        user_id=job.user_id,
        metadata_json=json.dumps(metadata, separators=(",", ":")),
        **extra,
    ) or job


def _issue_url(job, mode: str, user_id: int) -> dict:
    ticket = ticket_signer.issue(session_id=f"stream-keep:{job.id}", user_id=user_id)
    escaped = quote(ticket, safe="")
    if mode == PlaybackMode.DIRECT_PLAY.value:
        return {
            "type": "direct",
            "url": f"/api/playback/stream-keep/{job.id}/stream?ticket={escaped}",
            "ticket_expires_in": ticket_signer.ttl_seconds,
        }
    return {
        "type": "hls",
        "url": f"/api/playback/stream-keep/{job.id}/hls/index.m3u8?ticket={escaped}",
        "ticket_expires_in": ticket_signer.ttl_seconds,
    }


def _require_ticket_job(job_id: str, ticket: str):
    try:
        payload = ticket_signer.verify(ticket, session_id=f"stream-keep:{job_id}")
    except TicketError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    job = store.get(job_id, user_id=int(payload["uid"]))
    if not job:
        raise HTTPException(status_code=404, detail="Stream + Keep job not found")
    if job.status == "cancelled":
        raise HTTPException(status_code=410, detail="Stream + Keep job was cancelled")
    return job


def _remote_config(job):
    playback = (job.metadata or {}).get("remote_playback") or {}
    source = playback.get("source") or {}
    target = playback.get("target") or {}
    caps = playback.get("capabilities") or {}
    return playback, source, target, caps


def _ensure_remote_hls(job):
    playback, source, target, caps = _remote_config(job)
    mode = str(playback.get("mode") or "")
    if mode == PlaybackMode.DIRECT_PLAY.value:
        raise HLSJobError("Remote job uses direct playback")
    hls_manager.ensure_job(
        session_id=job.id,
        source_path=job.remote_url,
        mode=mode,
        target_video_codec=target.get("video_codec"),
        target_audio_codec=target.get("audio_codec"),
        source_video_codec=source.get("video_codec"),
        source_width=source.get("width"),
        source_height=source.get("height"),
        max_width=caps.get("max_width"),
        max_height=caps.get("max_height"),
        max_bitrate=caps.get("max_bitrate"),
        start_position=float(playback.get("position") or 0),
    )
    return hls_manager.wait_until_ready(job.id)


def _public_job(job) -> dict:
    reconciled = manager.reconcile(job)
    data = reconciled.to_dict(include_remote=False)
    playback = (reconciled.metadata or {}).get("remote_playback") or {}
    data["remote_playback"] = {
        "mode": playback.get("mode"),
        "position": playback.get("position", 0),
        "source": playback.get("source", {}),
        "target": playback.get("target", {}),
        "reasons": playback.get("reasons", []),
    }
    return data


def _safe_remote_get(url: str, *, range_header: Optional[str] = None, timeout=(10, 45), max_redirects: int = 5):
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
            timeout=timeout,
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


@router.post("/stream-keep/start")
def start_stream_keep(
    request: StreamKeepStartRequest,
    user_id: int = Depends(get_current_user_id),
):
    if not debrid.is_safe_external_url(request.url):
        raise HTTPException(status_code=400, detail="Refusing to stream from a non-public URL")
    source = _probe_remote(request.url, request.filename)
    plan = core.planner.plan(source, _caps(request.capabilities))
    if plan.mode == PlaybackMode.UNSUPPORTED:
        raise HTTPException(status_code=422, detail={
            "message": "No viable remote playback path for this client",
            "reasons": list(plan.reasons),
        })

    job = store.create(
        user_id=user_id,
        provider=request.provider,
        remote_url=request.url,
        filename=request.filename,
        category=request.category,
        is_show=request.is_show,
        metadata=_plan_metadata(source, plan, request),
    )
    # Start the local copy before waiting on any FFmpeg remote-HLS preparation.
    job = manager.start_download(job)

    if plan.mode != PlaybackMode.DIRECT_PLAY:
        try:
            _ensure_remote_hls(job)
        except HLSJobError as exc:
            # Keeping the local copy is still useful if remote playback prep
            # fails, so do not cancel the download job.
            raise HTTPException(status_code=503, detail=f"Remote playback preparation failed while local download continues: {exc}")

    return {
        "job": _public_job(job),
        "playback": _issue_url(job, plan.mode.value, user_id),
        "plan": {
            "mode": plan.mode.value,
            "reasons": list(plan.reasons),
            "source": (job.metadata.get("remote_playback") or {}).get("source", {}),
            "target": (job.metadata.get("remote_playback") or {}).get("target", {}),
        },
    }


@router.get("/stream-keep/jobs")
def list_stream_keep_jobs(
    limit: int = Query(default=100, ge=1, le=500),
    user_id: int = Depends(get_current_user_id),
):
    return {"jobs": [_public_job(job) for job in store.list_for_user(user_id, limit)]}


@router.get("/stream-keep/{job_id}")
def stream_keep_status(job_id: str, user_id: int = Depends(get_current_user_id)):
    job = store.get(job_id, user_id=user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Stream + Keep job not found")
    return {"job": _public_job(job)}


@router.post("/stream-keep/{job_id}/ticket")
def refresh_stream_keep_ticket(job_id: str, user_id: int = Depends(get_current_user_id)):
    job = store.get(job_id, user_id=user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Stream + Keep job not found")
    mode = str(((job.metadata or {}).get("remote_playback") or {}).get("mode") or PlaybackMode.DIRECT_PLAY.value)
    return _issue_url(job, mode, user_id)


@router.post("/stream-keep/{job_id}/seek")
def seek_stream_keep(
    job_id: str,
    request: StreamKeepSeekRequest,
    user_id: int = Depends(get_current_user_id),
):
    job = store.get(job_id, user_id=user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Stream + Keep job not found")
    playback = dict((job.metadata or {}).get("remote_playback") or {})
    mode = str(playback.get("mode") or PlaybackMode.DIRECT_PLAY.value)
    playback["position"] = float(request.position)
    metadata = dict(job.metadata or {})
    metadata["remote_playback"] = playback
    job = _save_metadata(job, metadata)
    if mode != PlaybackMode.DIRECT_PLAY.value:
        hls_manager.stop(job.id, remove_cache=True)
        try:
            _ensure_remote_hls(job)
        except HLSJobError as exc:
            raise HTTPException(status_code=503, detail=f"Remote seek failed: {exc}")
    return {
        "job": _public_job(job),
        "playback": _issue_url(job, mode, user_id),
        "source_offset": float(request.position) if mode != PlaybackMode.DIRECT_PLAY.value else 0,
    }


@router.delete("/stream-keep/{job_id}")
def cancel_stream_keep(job_id: str, user_id: int = Depends(get_current_user_id)):
    job = store.get(job_id, user_id=user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Stream + Keep job not found")
    hls_manager.stop(job.id, remove_cache=True)
    job = manager.cancel(job)
    return {"job": _public_job(job)}


@router.get("/stream-keep/{job_id}/stream")
def proxy_stream_keep(
    job_id: str,
    request: Request,
    ticket: str = Query(...),
):
    job = _require_ticket_job(job_id, ticket)
    mode = str(((job.metadata or {}).get("remote_playback") or {}).get("mode") or "")
    if mode != PlaybackMode.DIRECT_PLAY.value:
        raise HTTPException(status_code=409, detail="This remote job uses HLS playback")
    try:
        upstream = _safe_remote_get(job.remote_url, range_header=request.headers.get("range"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Remote media request failed: {exc}")
    if upstream.status_code >= 400:
        status = upstream.status_code
        upstream.close()
        raise HTTPException(status_code=502, detail=f"Remote media server returned HTTP {status}")

    headers = {"Accept-Ranges": upstream.headers.get("Accept-Ranges", "bytes"), "Cache-Control": "private, no-store"}
    for name in ("Content-Length", "Content-Range", "ETag", "Last-Modified"):
        value = upstream.headers.get(name)
        if value:
            headers[name] = value
    media_type = upstream.headers.get("Content-Type") or mimetypes.guess_type(job.filename)[0] or "application/octet-stream"

    def body():
        try:
            for chunk in upstream.iter_content(chunk_size=1024 * 512):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(body(), status_code=upstream.status_code, media_type=media_type, headers=headers)


@router.get("/stream-keep/{job_id}/hls/index.m3u8")
def stream_keep_hls_playlist(job_id: str, ticket: str = Query(...)):
    job = _require_ticket_job(job_id, ticket)
    try:
        playlist = _ensure_remote_hls(job)
        text = playlist.read_text(encoding="utf-8")
    except (HLSJobError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"Remote HLS unavailable: {exc}")
    return Response(
        content=core._ticketed_playlist(text, ticket),
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/stream-keep/{job_id}/hls/{filename}")
def stream_keep_hls_asset(job_id: str, filename: str, ticket: str = Query(...)):
    _require_ticket_job(job_id, ticket)
    if filename != "init.mp4" and not re.fullmatch(r"segment_\d{5}\.m4s", filename):
        raise HTTPException(status_code=404, detail="Remote HLS asset not found")
    path = hls_manager.session_dir(job_id) / filename
    if not path.is_file():
        job = _require_ticket_job(job_id, ticket)
        try:
            _ensure_remote_hls(job)
        except HLSJobError:
            pass
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Remote HLS asset not ready")
    media_type = "video/mp4" if filename == "init.mp4" else "video/iso.segment"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})
