"""Compatibility facade for the Nomad 2.x playback routers."""

import sys

from app.routers import playback_core as _core
from app.routers.playback_tracks import router as _tracks_router
from app.routers.playback_quality import router as _quality_router
from app.routers.playback_health import router as _health_router
from app.routers.playback_subtitles import router as _subtitle_router
from app.services.playback.hls import HLSJobError


def _ensure_hls_with_selected_streams(session, fs_path=None):
    """Rebuild HLS while preserving alternate audio and burned subtitles.

    The original core helper predates track switching. Keeping this override in
    the facade avoids rewriting the large core router while ensuring seeks,
    restart recovery and playlist regeneration retain the selected streams.
    """
    metadata = session.metadata or {}
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


_core._ensure_hls = _ensure_hls_with_selected_streams
_core.router.include_router(_tracks_router)
_core.router.include_router(_quality_router)
_core.router.include_router(_health_router)
_core.router.include_router(_subtitle_router)

# Preserve imports such as ``from app.routers import playback`` while keeping
# the main playback implementation and optional controls modular.
sys.modules[__name__] = _core
