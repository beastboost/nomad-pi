"""Playback quality profiles for Nomad Pi 2.x."""

from __future__ import annotations

import copy
import os
from typing import Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.routers.media import safe_fs_path_from_web_path
from app.routers import playback_core as core
from app.services.playback.hls import HLSJobError
from app.services.playback.planner import ClientCapabilities, MediaProbe, PlaybackMode
from app.services.playback.probe import ProbeError, probe_media


router = APIRouter()

QUALITY_PROFILES = {
    "auto": {"label": "Auto", "max_width": None, "max_height": None, "max_bitrate": None},
    "original": {"label": "Original", "max_width": None, "max_height": None, "max_bitrate": None},
    "1080p": {"label": "1080p", "max_width": 1920, "max_height": 1080, "max_bitrate": 8_000_000},
    "720p": {"label": "720p", "max_width": 1280, "max_height": 720, "max_bitrate": 4_000_000},
    "480p": {"label": "480p", "max_width": 854, "max_height": 480, "max_bitrate": 2_000_000},
}


class QualitySwitchRequest(BaseModel):
    quality: str = Field(min_length=1, max_length=32)
    position: float = Field(default=0, ge=0)


def _min_limit(current: Optional[int], requested: Optional[int]) -> Optional[int]:
    if current and requested:
        return min(int(current), int(requested))
    return int(current or requested) if (current or requested) else None


def _capabilities(metadata: dict, profile: dict) -> ClientCapabilities:
    raw = metadata.get("capabilities") or {}
    return ClientCapabilities.from_values(
        containers=raw.get("containers") or [],
        video_codecs=raw.get("video_codecs") or [],
        audio_codecs=raw.get("audio_codecs") or [],
        subtitle_formats=raw.get("subtitle_formats") or [],
        max_width=_min_limit(raw.get("max_width"), profile.get("max_width")),
        max_height=_min_limit(raw.get("max_height"), profile.get("max_height")),
        max_bitrate=_min_limit(raw.get("max_bitrate"), profile.get("max_bitrate")),
    )


def _media_probe(metadata: dict) -> MediaProbe:
    """Reconstruct a probe from persisted metadata as a fallback only."""
    source = metadata.get("source") or {}
    selected_audio = metadata.get("selected_audio") or {}
    return MediaProbe(
        container=str(source.get("container") or ""),
        video_codec=source.get("video_codec"),
        audio_codec=selected_audio.get("codec") or source.get("audio_codec"),
        width=source.get("width"),
        height=source.get("height"),
        bitrate=source.get("bitrate"),
        duration=source.get("duration"),
        video_profile=source.get("video_profile"),
        pixel_format=source.get("pixel_format"),
        codec_tag=source.get("codec_tag"),
    )


def _probe_for_switch(fs_path: str, metadata: dict) -> MediaProbe:
    """Re-probe on a quality switch so browser compatibility never goes stale."""
    try:
        fresh = probe_media(fs_path)
    except ProbeError:
        fresh = _media_probe(metadata)

    selected_audio = metadata.get("selected_audio") or {}
    if selected_audio.get("codec"):
        fresh = MediaProbe(
            container=fresh.container,
            video_codec=fresh.video_codec,
            audio_codec=selected_audio.get("codec"),
            width=fresh.width,
            height=fresh.height,
            bitrate=fresh.bitrate,
            duration=fresh.duration,
            video_profile=fresh.video_profile,
            pixel_format=fresh.pixel_format,
            codec_tag=fresh.codec_tag,
        )
    return fresh


def _persist_source_probe(metadata: dict, source: MediaProbe) -> None:
    raw = metadata.setdefault("source", {})
    raw.update({
        "container": source.container,
        "video_codec": source.video_codec,
        "audio_codec": source.audio_codec,
        "width": source.width,
        "height": source.height,
        "bitrate": source.bitrate,
        "duration": source.duration,
        "video_profile": source.video_profile,
        "pixel_format": source.pixel_format,
        "codec_tag": source.codec_tag,
    })


def _cap_dict(caps: ClientCapabilities) -> dict:
    return {
        "containers": sorted(caps.containers),
        "video_codecs": sorted(caps.video_codecs),
        "audio_codecs": sorted(caps.audio_codecs),
        "subtitle_formats": sorted(caps.subtitle_formats),
        "max_width": caps.max_width,
        "max_height": caps.max_height,
        "max_bitrate": caps.max_bitrate,
    }


def _burn_video_codec(caps: ClientCapabilities, planned: Optional[str], source: MediaProbe) -> str:
    if planned in {"h264", "hevc"}:
        return planned
    if "h264" in caps.video_codecs or "avc" in caps.video_codecs:
        return "h264"
    if "hevc" in caps.video_codecs or "h265" in caps.video_codecs:
        return "hevc"
    if source.video_codec in {"h264", "hevc"} and source.video_codec in caps.video_codecs:
        return source.video_codec
    raise HTTPException(status_code=422, detail="No HLS-compatible video codec is available for burned subtitles")


def _sequential_handover_required() -> bool:
    """Avoid two simultaneous FFmpeg jobs on memory-constrained appliances.

    ``NOMAD_PLAYBACK_HANDOVER=overlap`` can force the old prepare-first
    behaviour on larger systems; ``sequential`` forces low-memory behaviour.
    Auto defaults to sequential below 2 GiB RAM, covering the 1 GiB A7Z class.
    """
    policy = str(os.environ.get("NOMAD_PLAYBACK_HANDOVER", "auto")).strip().lower()
    if policy == "overlap":
        return False
    if policy == "sequential":
        return True
    try:
        return int(psutil.virtual_memory().total) < 2 * 1024 * 1024 * 1024
    except Exception:
        return False


def _restore_old_hls(old, fs_path: str, user_id: int, position: float) -> bool:
    """Best-effort rollback when a sequential replacement cannot be prepared."""
    try:
        restored = core.session_store.update(
            old.id,
            user_id=user_id,
            position=position,
            state="preparing",
        ) or old
        core._ensure_hls(restored, fs_path=fs_path)
        core.session_store.update(old.id, user_id=user_id, state="ready")
        return True
    except Exception:
        core.session_store.update(old.id, user_id=user_id, state="failed")
        return False


@router.get("/quality-profiles")
def quality_profiles(user_id: int = Depends(get_current_user_id)):
    return {"profiles": [{"id": key, **value} for key, value in QUALITY_PROFILES.items()]}


@router.post("/sessions/{session_id}/quality")
def switch_quality(
    session_id: str,
    request: QualitySwitchRequest,
    user_id: int = Depends(get_current_user_id),
):
    old = core.session_store.get(session_id, user_id=user_id)
    if not old or old.state == "stopped":
        raise HTTPException(status_code=404, detail="Active playback session not found")

    quality = request.quality.strip().lower()
    profile = QUALITY_PROFILES.get(quality)
    if not profile:
        raise HTTPException(status_code=400, detail="Unknown quality profile")

    try:
        fs_path = safe_fs_path_from_web_path(old.path)
    except Exception:
        raise HTTPException(status_code=404, detail="Playback source not found")
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="Playback source not found")

    metadata = copy.deepcopy(old.metadata or {})
    # A manual profile intentionally exits multi-rendition ABR. Clear the
    # adaptive markers before planning/starting the replacement, otherwise the
    # compatibility facade would correctly route the new session back into ABR.
    metadata.pop("abr", None)
    metadata.pop("abr_policy_reason", None)
    metadata.pop("abr_encoder_candidates", None)
    metadata.pop("abr_renditions", None)

    caps = _capabilities(metadata, profile)
    source = _probe_for_switch(fs_path, metadata)
    _persist_source_probe(metadata, source)
    plan = core.planner.plan(source, caps)
    if plan.mode == PlaybackMode.UNSUPPORTED:
        raise HTTPException(status_code=422, detail={
            "message": "No viable playback path for this quality",
            "reasons": list(plan.reasons),
        })

    mode = plan.mode
    target_video = plan.target_video_codec
    target_audio = plan.target_audio_codec
    selected_audio = metadata.get("selected_audio") or {}
    if old.audio_track is not None and mode == PlaybackMode.DIRECT_PLAY:
        selected_codec = str(selected_audio.get("codec") or "").lower()
        if selected_codec == "aac" or selected_codec in caps.audio_codecs:
            mode = PlaybackMode.REMUX
            target_audio = None
        elif "aac" in caps.audio_codecs:
            mode = PlaybackMode.TRANSCODE_AUDIO
            target_audio = "aac"
        else:
            raise HTTPException(status_code=422, detail="Selected audio cannot be represented at this quality")

    burn_subtitle = metadata.get("burn_subtitle")
    if burn_subtitle:
        mode = PlaybackMode.TRANSCODE_VIDEO
        target_video = _burn_video_codec(caps, target_video, source)
        selected_codec = str(selected_audio.get("codec") or source.audio_codec or "").lower()
        if selected_codec and selected_codec not in caps.audio_codecs:
            if "aac" not in caps.audio_codecs:
                raise HTTPException(status_code=422, detail="Selected audio cannot be represented with burned subtitles")
            target_audio = "aac"

    metadata["capabilities"] = _cap_dict(caps)
    metadata["target"] = {
        "container": plan.target_container or "mp4",
        "video_codec": target_video,
        "audio_codec": target_audio,
    }
    metadata["reasons"] = list(plan.reasons)
    metadata["quality_profile"] = quality
    position = max(0.0, float(request.position or 0))

    replacement = core.session_store.create(
        user_id=user_id,
        path=old.path,
        mode=mode.value,
        duration=old.duration,
        position=position,
        audio_track=old.audio_track,
        subtitle_track=old.subtitle_track,
        quality=quality,
        device_id=old.device_id,
        metadata=metadata,
    )

    # Prepare-first handover is pleasant on a normal server, but on a 1 GiB
    # SBC it can overlap two FFmpeg pipelines and starve or OOM the web UI.
    # Stop the old HLS first on low-memory appliances and roll it back if the
    # replacement cannot start.
    stopped_old_first = (
        _sequential_handover_required()
        and old.mode != PlaybackMode.DIRECT_PLAY.value
    )
    if stopped_old_first:
        core.hls_manager.stop(old.id, remove_cache=True)
        core.session_store.update(old.id, user_id=user_id, state="handover")

    try:
        if mode == PlaybackMode.DIRECT_PLAY:
            replacement = core.session_store.update(
                replacement.id, user_id=user_id, state="ready"
            ) or replacement
        else:
            core.session_store.update(replacement.id, user_id=user_id, state="preparing")
            core._ensure_hls(replacement, fs_path=fs_path)
            replacement = core.session_store.update(
                replacement.id, user_id=user_id, state="ready"
            ) or replacement
    except HLSJobError as exc:
        core.hls_manager.stop(replacement.id, remove_cache=True)
        core.session_store.update(replacement.id, user_id=user_id, state="failed")
        restored = _restore_old_hls(old, fs_path, user_id, position) if stopped_old_first else False
        suffix = "; original stream restored" if restored else ""
        raise HTTPException(status_code=503, detail=f"Quality switch failed: {exc}{suffix}")

    if not stopped_old_first:
        core.hls_manager.stop(old.id, remove_cache=True)
    core.session_store.update(old.id, user_id=user_id, state="stopped")

    ticket = core.ticket_signer.issue(session_id=replacement.id, user_id=user_id)
    return {
        "replaced_session_id": old.id,
        "session": replacement.to_dict(),
        "source_offset": position if mode != PlaybackMode.DIRECT_PLAY else 0,
        "playback": core._playback_urls(replacement, ticket),
        "plan": {
            "mode": mode.value,
            "reasons": list(plan.reasons),
            "target": metadata["target"],
        },
        "ticket_expires_in": core.ticket_signer.ttl_seconds,
    }
