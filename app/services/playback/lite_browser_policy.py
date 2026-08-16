"""Direct-first browser playback policy for low-memory Nomad hosts.

Nomad is intended to remain useful on Pi Zero-class hardware.  On sub-2 GiB
systems the server should not automatically turn every incompatible source into
a live video-transcode workload.  Direct play remains preferred, cheap
container/audio fixes remain available, and live video transcode can still be
explicitly enabled with ``NOMAD_LIVE_VIDEO_TRANSCODE=1``.
"""

from __future__ import annotations

import os

import psutil

from app.services.playback.compat import BrowserPlaybackPlanner
from app.services.playback.planner import (
    ClientCapabilities,
    MediaProbe,
    PlaybackMode,
    PlaybackPlan,
)


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "force"}


def lite_playback_enabled() -> bool:
    policy = str(os.environ.get("NOMAD_LITE_PLAYBACK", "auto")).strip().lower()
    if policy in {"off", "0", "false", "no"}:
        return False
    if policy in {"on", "1", "true", "yes", "force"}:
        return True
    try:
        return int(psutil.virtual_memory().total) < 2 * 1024 ** 3
    except Exception:
        return True


def live_video_transcode_enabled() -> bool:
    return _truthy(os.environ.get("NOMAD_LIVE_VIDEO_TRANSCODE", ""))


class LiteBrowserPlaybackPlanner(BrowserPlaybackPlanner):
    """Avoid expensive/fragile live video conversion on low-memory hardware."""

    def plan(self, source: MediaProbe, client: ClientCapabilities) -> PlaybackPlan:
        plan = super().plan(source, client)
        if not lite_playback_enabled() or live_video_transcode_enabled():
            return plan

        if plan.mode in {PlaybackMode.DIRECT_PLAY, PlaybackMode.UNSUPPORTED}:
            return plan

        # HEVC that is already a browser-safe direct-play file has already
        # returned above.  If it needs sample-entry/container repair, do not turn
        # a tiny appliance into a live HEVC conversion box.  Acquire/convert a
        # compatible H.264 MP4 once instead.
        if source.video_codec in {"hevc", "h265"}:
            return PlaybackPlan(
                mode=PlaybackMode.UNSUPPORTED,
                reasons=tuple(plan.reasons) + (
                    "Lite playback mode avoids live HEVC remux/transcode on sub-2 GiB hardware; use an H.264 MP4 source or Convert to MP4 once",
                ),
            )

        if plan.mode == PlaybackMode.TRANSCODE_VIDEO:
            return PlaybackPlan(
                mode=PlaybackMode.UNSUPPORTED,
                reasons=tuple(plan.reasons) + (
                    "Lite playback mode disables automatic live video transcoding on sub-2 GiB hardware; choose a direct-play H.264 source or set NOMAD_LIVE_VIDEO_TRANSCODE=1",
                ),
            )

        # H.264 container remux and audio-only conversion are intentionally kept:
        # they avoid decoding/encoding video and are the only live conversion
        # paths cheap enough to make sense on the smallest supported systems.
        return plan
