"""A733-specific browser playback policy.

The generic browser planner deliberately prefers remuxing when codecs are
already supported by the client.  On the Radxa/Allwinner A733, however, field
testing with iPhone Safari has shown that HEVC which needs container/sample-
entry repair can remain fragile when stream-copied into fMP4 HLS: playback may
start but present irregular cadence, while the same source is smooth in VLC.

When the validated vendor OpenMAX path is available, use it for those HEVC
non-direct cases instead.  Clean hvc1 MP4 that Safari can direct-play is left
untouched, and H.264 remux/audio-only paths remain cheap stream-copy jobs.
"""

from __future__ import annotations

from app.services.platform_info import platform_info
from app.services.playback.compat import BrowserPlaybackPlanner, FMP4_AUDIO_COPY
from app.services.playback.gstreamer_a733 import a733_gstreamer_status
from app.services.playback.planner import (
    ClientCapabilities,
    MediaProbe,
    PlaybackMode,
    PlaybackPlan,
)


class A733BrowserPlaybackPlanner(BrowserPlaybackPlanner):
    """Escalate fragile HEVC non-direct playback to validated A733 H.264 OMX."""

    def plan(self, source: MediaProbe, client: ClientCapabilities) -> PlaybackPlan:
        plan = super().plan(source, client)
        if plan.mode in {PlaybackMode.DIRECT_PLAY, PlaybackMode.UNSUPPORTED}:
            return plan
        if source.video_codec not in {"hevc", "h265"}:
            return plan
        if not platform_info().get("is_allwinner_a733"):
            return plan
        if not a733_gstreamer_status().get("usable"):
            return plan
        if not ({"h264", "avc"} & set(client.video_codecs)):
            return plan

        target_audio = None
        if source.has_audio and source.audio_codec not in FMP4_AUDIO_COPY:
            if "aac" not in client.audio_codecs:
                return plan
            target_audio = "aac"

        return PlaybackPlan(
            mode=PlaybackMode.TRANSCODE_VIDEO,
            reasons=tuple(plan.reasons) + (
                "A733 Safari compatibility: non-direct HEVC uses validated OMX H.264 instead of fragile stream-copy HLS",
            ),
            target_container="mp4",
            target_video_codec="h264",
            target_audio_codec=target_audio,
        )
