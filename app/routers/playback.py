"""Compatibility facade for the Nomad 2.x playback routers."""

import sys
from urllib.parse import quote

from app.routers import playback_core as _core
from app.services.playback.cache_guard import install_playback_cache_guard
from app.services.playback.remux_stability import install_remux_stability
from app.services.playback.runtime_abr_policy import install_runtime_abr_policy

# Install runtime policy before feature routers instantiate their own managers
# or capture helper functions by name. playback_core has already created its
# HLS manager, but these overlays patch manager classes/module globals so that
# existing instance is covered too.
install_playback_cache_guard()
install_remux_stability()
install_runtime_abr_policy()

from app.routers.playback_tracks import router as _tracks_router
from app.routers.playback_quality import router as _quality_router
from app.routers.playback_health import router as _health_router
from app.routers.playback_subtitles import router as _subtitle_router
from app.routers.playback_devices import router as _devices_router
from app.routers.playback_music import router as _music_router
from app.routers.playback_stream_keep import (
    manager as _stream_keep_manager,
    router as _stream_keep_router,
)
from app.routers.playback_stream_keep_control import router as _stream_keep_control_router
from app.routers.playback_offline import router as _offline_router
from app.routers.playback_intelligence import router as _intelligence_router
from app.routers.playback_profile_policy import router as _profile_policy_router
from app.routers.playback_reader import router as _reader_router
from app.routers.playback_watch_party import router as _watch_party_router
from app.routers.playback_abr import (
    abr_manager as _abr_manager,
    ensure_adaptive_session as _ensure_adaptive_session,
    router as _abr_router,
)
from app.services.playback.a733_browser_policy import A733BrowserPlaybackPlanner
from app.services.playback.abr import ABRJobError
from app.services.playback.hls import HLSJobError


_original_playback_urls = _core._playback_urls
_original_hls_stop = _core.hls_manager.stop
_original_hls_status = _core.hls_manager.status

# The execution layer emits browser HLS for all non-direct playback. Use the
# compatibility-aware planner plus the A733 field policy: clean direct-play
# files stay untouched, while HEVC that would otherwise need fragile fMP4
# stream-copy HLS can use the validated vendor OMX -> H.264 path.
_core.planner = A733BrowserPlaybackPlanner()


def _ensure_hls_with_selected_streams(session, fs_path=None):
    """Rebuild the correct HLS engine while preserving selected streams."""
    metadata = session.metadata or {}
    if metadata.get("abr"):
        try:
            return _ensure_adaptive_session(session, fs_path=fs_path)
        except ABRJobError as exc:
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
        source_video_codec=source.get("video_codec"),
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

# Keep the core router stable while feature routers remain independently
# testable and small. All of these endpoints live below /api/playback.
for _router in (
    _tracks_router,
    _quality_router,
    _health_router,
    _subtitle_router,
    _abr_router,
    _devices_router,
    _music_router,
    _stream_keep_router,
    _stream_keep_control_router,
    _offline_router,
    _intelligence_router,
    _profile_policy_router,
    _reader_router,
    _watch_party_router,
):
    _core.router.include_router(_router)

# Reattach any interrupted Stream + Keep local copies after process startup.
# The worker keeps its stable .part file and resumes with HTTP Range where the
# debrid host supports it; this call is intentionally non-blocking.
_stream_keep_manager.schedule_recovery()

# Preserve imports such as ``from app.routers import playback`` while keeping
# the main playback implementation and optional controls modular.
sys.modules[__name__] = _core
