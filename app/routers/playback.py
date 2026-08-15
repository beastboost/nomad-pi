"""Compatibility facade for the Nomad 2.x playback routers."""

import sys
from urllib.parse import quote

from app.routers import playback_core as _core
from app.routers.playback_tracks import router as _tracks_router
from app.routers.playback_quality import router as _quality_router
from app.routers.playback_health import router as _health_router
from app.routers.playback_subtitles import router as _subtitle_router
from app.routers.playback_abr import (
    abr_manager as _abr_manager,
    ensure_adaptive_session as _ensure_adaptive_session,
    router as _abr_router,
)
from app.services.playback.abr import ABRJobError
from app.services.playback.hls import HLSJobError


_original_playback_urls = _core._playback_urls
_original_hls_stop = _core.hls_manager.stop
_original_hls_status = _core.hls_manager.status


def _ensure_hls_with_selected_streams(session, fs_path=None):
    """Rebuild the correct HLS engine while preserving selected streams."""
    metadata = session.metadata or {}
    if metadata.get("abr"):
        try:
            return _ensure_adaptive_session(session, fs_path=fs_path)
        except ABRJobError as exc:
            # Core seek/recovery paths already understand HLSJobError, so keep
            # the public failure semantics identical for adaptive sessions.
            raise HLSJobError(str(exc)) from exc

    source = metadata.get("source") or {}
    target = metadata.get("target") or {}
    caps = metadata.get("capabilities") or {}
    if fs_path is None:
        try:
            fs_path = _core.safe_fs_path_from_web_path(session.path)
        except Exception as exc:
            raise HLSJobError("Playback source is no longer available") from exc
    if not _core.os.path.isfile(fs_path):
        raise HLSJobError("Playback source is no longer available")

    burn_subtitle = metadata.get("burn_subtitle")
    _core.hls_manager.ensure_job(
        session_id=session.id,
        source_path=fs_path,
        mode=session.mode,
        target_video_codec=target.get("video_codec"),
        target_audio_codec=target.get("audio_codec"),
        audio_stream_index=session.audio_track,
        subtitle_stream_index=(session.subtitle_track if burn_subtitle else None),
        source_width=source.get("width"),
        source_height=source.get("height"),
        max_width=caps.get("max_width"),
        max_height=caps.get("max_height"),
        max_bitrate=caps.get("max_bitrate"),
        start_position=session.position,
    )
    return _core.hls_manager.wait_until_ready(session.id)


def _playback_urls_with_adaptive(session, ticket: str) -> dict:
    if (session.metadata or {}).get("abr"):
        return {
            "type": "hls",
            "adaptive": True,
            "url": f"/api/playback/abr/{session.id}/master.m3u8?ticket={quote(ticket, safe='')}",
        }
    return _original_playback_urls(session, ticket)


def _stop_all_hls(session_id: str, *, remove_cache: bool = False) -> None:
    _original_hls_stop(session_id, remove_cache=remove_cache)
    _abr_manager.stop(session_id, remove_cache=remove_cache)


def _status_all_hls(session_id: str) -> dict:
    session = _core.session_store.get(session_id)
    if session and (session.metadata or {}).get("abr"):
        return {"adaptive": True, **_abr_manager.status(session_id)}
    return _original_hls_status(session_id)


_core._ensure_hls = _ensure_hls_with_selected_streams
_core._playback_urls = _playback_urls_with_adaptive
_core.hls_manager.stop = _stop_all_hls
_core.hls_manager.status = _status_all_hls

_core.router.include_router(_tracks_router)
_core.router.include_router(_quality_router)
_core.router.include_router(_health_router)
_core.router.include_router(_subtitle_router)
_core.router.include_router(_abr_router)

# Preserve imports such as ``from app.routers import playback`` while keeping
# the main playback implementation and optional controls modular.
sys.modules[__name__] = _core
