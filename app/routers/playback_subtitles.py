"""Image-subtitle burn-in controls for Nomad Pi playback sessions."""

from __future__ import annotations

import copy
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.auth import get_current_user_id
from app.routers import playback_core as core
from app.routers.playback_tracks import _resolve, _tracks
from app.services.playback.hls import HLSJobError
from app.services.playback.planner import ClientCapabilities, MediaProbe, PlaybackMode


router = APIRouter()


class SubtitleBurnRequest(BaseModel):
    stream_index: Optional[int] = Field(default=None, ge=0)
    position: float = Field(default=0, ge=0)


def _capabilities(metadata: dict) -> ClientCapabilities:
    raw = metadata.get("capabilities") or {}
    return ClientCapabilities.from_values(
        containers=raw.get("containers") or [],
        video_codecs=raw.get("video_codecs") or [],
        audio_codecs=raw.get("audio_codecs") or [],
        subtitle_formats=raw.get("subtitle_formats") or [],
        max_width=raw.get("max_width"),
        max_height=raw.get("max_height"),
        max_bitrate=raw.get("max_bitrate"),
    )


def _source_probe(metadata: dict, audio_codec: Optional[str] = None) -> MediaProbe:
    source = metadata.get("source") or {}
    return MediaProbe(
        container=str(source.get("container") or ""),
        video_codec=source.get("video_codec"),
        audio_codec=audio_codec if audio_codec is not None else source.get("audio_codec"),
        width=source.get("width"),
        height=source.get("height"),
        bitrate=source.get("bitrate"),
        duration=source.get("duration"),
    )


def _hls_video_codec(caps: ClientCapabilities, source_codec: Optional[str]) -> str:
    for codec in ("h264", "avc", "hevc", "h265"):
        if codec in caps.video_codecs:
            return "h264" if codec == "avc" else "hevc" if codec == "h265" else codec
    if source_codec in {"h264", "hevc"} and source_codec in caps.video_codecs:
        return source_codec
    raise HTTPException(status_code=422, detail="Client reported no HLS-compatible video codec for subtitle burn-in")


def _selected_audio(tracks: dict, stream_index: Optional[int]) -> Optional[dict]:
    audio = tracks.get("audio") or []
    if stream_index is not None:
        return next((item for item in audio if item.get("stream_index") == stream_index), None)
    return next((item for item in audio if item.get("default")), None) or (audio[0] if audio else None)


def _prepare_replacement(replacement, fs_path: str, user_id: int):
    if replacement.mode == PlaybackMode.DIRECT_PLAY.value and not (replacement.metadata or {}).get("abr"):
        return core.session_store.update(
            replacement.id, user_id=user_id, state="ready"
        ) or replacement

    core.session_store.update(replacement.id, user_id=user_id, state="preparing")
    try:
        core._ensure_hls(replacement, fs_path=fs_path)
    except HLSJobError as exc:
        core.hls_manager.stop(replacement.id, remove_cache=True)
        core.session_store.update(replacement.id, user_id=user_id, state="failed")
        raise HTTPException(status_code=503, detail=f"Subtitle playback preparation failed: {exc}")
    return core.session_store.update(
        replacement.id, user_id=user_id, state="ready"
    ) or replacement


def _retire(old, user_id: int) -> None:
    core.hls_manager.stop(old.id, remove_cache=True)
    core.session_store.update(old.id, user_id=user_id, state="stopped")


@router.post("/sessions/{session_id}/subtitles/burn")
def switch_burned_subtitle(
    session_id: str,
    request: SubtitleBurnRequest,
    user_id: int = Depends(get_current_user_id),
):
    """Enable/disable bitmap subtitle burn-in without losing playback position."""
    old = core.session_store.get(session_id, user_id=user_id)
    if not old or old.state == "stopped":
        raise HTTPException(status_code=404, detail="Active playback session not found")

    fs_path = _resolve(old.path)
    tracks = _tracks(fs_path)
    metadata = copy.deepcopy(old.metadata or {})
    caps = _capabilities(metadata)
    position = max(0.0, float(request.position or 0))
    selected_audio = _selected_audio(tracks, old.audio_track)
    selected_audio_codec = str((selected_audio or {}).get("codec") or "").lower() or None
    adaptive = bool(metadata.get("abr"))

    selected_subtitle = None
    if request.stream_index is not None:
        selected_subtitle = next(
            (item for item in tracks.get("subtitles", []) if item.get("stream_index") == request.stream_index),
            None,
        )
        if not selected_subtitle:
            raise HTTPException(status_code=404, detail="Subtitle stream not found")
        if selected_subtitle.get("text_supported"):
            raise HTTPException(status_code=422, detail="Text subtitles should use WebVTT rather than burn-in")

        source = _source_probe(metadata, selected_audio_codec)
        target_video = "h264" if adaptive else _hls_video_codec(caps, source.video_codec)
        if adaptive:
            if "h264" not in caps.video_codecs and "avc" not in caps.video_codecs:
                raise HTTPException(status_code=422, detail="Adaptive subtitle burn-in requires H.264 client support")
            if source.has_audio and "aac" not in caps.audio_codecs:
                raise HTTPException(status_code=422, detail="Adaptive subtitle burn-in requires AAC client support")
            target_audio = "aac"
        elif source.has_audio and selected_audio_codec and selected_audio_codec not in caps.audio_codecs:
            if "aac" not in caps.audio_codecs:
                raise HTTPException(status_code=422, detail="Selected audio cannot be represented during subtitle burn-in")
            target_audio = "aac"
        else:
            target_audio = None

        metadata["burn_subtitle"] = selected_subtitle
        metadata["target"] = {
            "container": "hls" if adaptive else "mp4",
            "video_codec": target_video,
            "audio_codec": target_audio,
        }
        metadata.setdefault("reasons", []).append("image subtitle requires burn-in transcoding")
        mode = PlaybackMode.TRANSCODE_VIDEO
        subtitle_track = int(request.stream_index)
    else:
        metadata.pop("burn_subtitle", None)
        source = _source_probe(metadata, selected_audio_codec)

        if adaptive:
            # Removing PGS from an adaptive session should regenerate the same
            # master ladder without the overlay, not accidentally direct-play a
            # session whose metadata still advertises ABR.
            if "h264" not in caps.video_codecs and "avc" not in caps.video_codecs:
                raise HTTPException(status_code=422, detail="Adaptive playback requires H.264 client support")
            if source.has_audio and "aac" not in caps.audio_codecs:
                raise HTTPException(status_code=422, detail="Adaptive playback requires AAC client support")
            mode = PlaybackMode.TRANSCODE_VIDEO
            metadata["target"] = {
                "container": "hls",
                "video_codec": "h264",
                "audio_codec": "aac",
            }
            subtitle_track = None
        else:
            plan = core.planner.plan(source, caps)
            if plan.mode == PlaybackMode.UNSUPPORTED:
                raise HTTPException(status_code=422, detail={
                    "message": "No viable playback path after disabling subtitle burn-in",
                    "reasons": list(plan.reasons),
                })
            mode = plan.mode
            target_audio = plan.target_audio_codec
            if old.audio_track is not None and mode == PlaybackMode.DIRECT_PLAY:
                if not selected_audio_codec or selected_audio_codec in caps.audio_codecs:
                    mode = PlaybackMode.REMUX
                    target_audio = None
                elif "aac" in caps.audio_codecs:
                    mode = PlaybackMode.TRANSCODE_AUDIO
                    target_audio = "aac"
                else:
                    raise HTTPException(status_code=422, detail="Selected audio cannot be preserved after disabling subtitles")
            metadata["target"] = {
                "container": plan.target_container,
                "video_codec": plan.target_video_codec,
                "audio_codec": target_audio,
            }
            metadata["reasons"] = list(plan.reasons)
            subtitle_track = None

    replacement = core.session_store.create(
        user_id=user_id,
        path=old.path,
        mode=mode.value,
        duration=old.duration,
        position=position,
        audio_track=old.audio_track,
        subtitle_track=subtitle_track,
        quality=old.quality,
        device_id=old.device_id,
        metadata=metadata,
    )
    replacement = _prepare_replacement(replacement, fs_path, user_id)
    _retire(old, user_id)

    ticket = core.ticket_signer.issue(session_id=replacement.id, user_id=user_id)
    return {
        "replaced_session_id": old.id,
        "session": replacement.to_dict(),
        "track": selected_subtitle,
        "burned": selected_subtitle is not None,
        "source_offset": position if replacement.mode != PlaybackMode.DIRECT_PLAY.value else 0,
        "playback": core._playback_urls(replacement, ticket),
        "ticket_expires_in": core.ticket_signer.ttl_seconds,
    }
