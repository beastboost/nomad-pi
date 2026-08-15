"""Compatibility adjustments for browser/fMP4 playback.

The base planner reasons about codecs and containers independently. Nomad's
non-direct browser path, however, currently emits fragmented-MP4 HLS. A codec
that a browser can play somewhere (for example MP3/Opus in another container)
is not automatically a safe codec to stream-copy into Apple-style fMP4 HLS.
"""

from __future__ import annotations

from .planner import ClientCapabilities, MediaProbe, PlaybackMode, PlaybackPlan, PlaybackPlanner


FMP4_VIDEO_COPY = {"h264", "avc", "hevc", "h265"}
FMP4_AUDIO_COPY = {"aac", "alac"}


class BrowserPlaybackPlanner(PlaybackPlanner):
    """Prefer Apple-safe H.264/HEVC + AAC/ALAC for generated fMP4 HLS."""

    def plan(self, source: MediaProbe, client: ClientCapabilities) -> PlaybackPlan:
        base = super().plan(source, client)
        if base.mode in {PlaybackMode.DIRECT_PLAY, PlaybackMode.UNSUPPORTED}:
            return base

        reasons = list(base.reasons)
        video_copy_safe = not source.has_video or source.video_codec in FMP4_VIDEO_COPY
        audio_copy_safe = not source.has_audio or source.audio_codec in FMP4_AUDIO_COPY

        # Every generated HLS path currently uses fMP4, regardless of which
        # generic container the browser reported elsewhere. Do not stream-copy
        # VP9/AV1/MPEG4 or MP3/Opus/Vorbis into that output merely because the
        # browser can decode those codecs in WebM/Ogg/MP3.
        if not video_copy_safe:
            target_video = self._choose_hls_video(client.video_codecs)
            if not target_video:
                return PlaybackPlan(
                    mode=PlaybackMode.UNSUPPORTED,
                    reasons=tuple(reasons + ["generated fMP4 HLS requires H.264/HEVC-compatible video"]),
                )
            target_audio = None
            if source.has_audio and not audio_copy_safe:
                target_audio = self._choose_hls_audio(client.audio_codecs)
                if not target_audio:
                    return PlaybackPlan(
                        mode=PlaybackMode.UNSUPPORTED,
                        reasons=tuple(reasons + ["generated fMP4 HLS requires AAC/ALAC-compatible audio"]),
                    )
            return PlaybackPlan(
                mode=PlaybackMode.TRANSCODE_VIDEO,
                reasons=tuple(reasons + [f"video codec '{source.video_codec}' is unsafe for generated fMP4 HLS"]),
                target_container="mp4",
                target_video_codec=target_video,
                target_audio_codec=target_audio,
            )

        if not audio_copy_safe:
            target_audio = self._choose_hls_audio(client.audio_codecs)
            if not target_audio:
                return PlaybackPlan(
                    mode=PlaybackMode.UNSUPPORTED,
                    reasons=tuple(reasons + ["generated fMP4 HLS requires AAC/ALAC-compatible audio"]),
                )
            return PlaybackPlan(
                mode=PlaybackMode.TRANSCODE_AUDIO,
                reasons=tuple(reasons + [f"audio codec '{source.audio_codec}' is unsafe for generated fMP4 HLS"]),
                target_container="mp4",
                target_audio_codec=target_audio,
            )

        # Safe stream-copy/remux path. Report the actual generated container.
        if base.mode == PlaybackMode.REMUX:
            return PlaybackPlan(
                mode=PlaybackMode.REMUX,
                reasons=base.reasons,
                target_container="mp4",
            )

        # If a video transcode was already required for resolution/bitrate/etc,
        # make sure a globally-supported but fMP4-unsafe source audio codec is
        # not accidentally copied into the output.
        if base.mode == PlaybackMode.TRANSCODE_VIDEO and source.has_audio and not audio_copy_safe:
            audio = self._choose_hls_audio(client.audio_codecs)
            if not audio:
                return PlaybackPlan(
                    mode=PlaybackMode.UNSUPPORTED,
                    reasons=tuple(reasons + ["generated fMP4 HLS requires AAC/ALAC-compatible audio"]),
                )
            return PlaybackPlan(
                mode=base.mode,
                reasons=tuple(reasons + [f"audio codec '{source.audio_codec}' will be converted for fMP4 HLS"]),
                target_container="mp4",
                target_video_codec=base.target_video_codec,
                target_audio_codec=audio,
            )

        return base

    @staticmethod
    def _choose_hls_video(codecs: frozenset[str]):
        for codec in ("h264", "avc", "hevc", "h265"):
            if codec in codecs:
                return "h264" if codec == "avc" else "hevc" if codec == "h265" else codec
        return None

    @staticmethod
    def _choose_hls_audio(codecs: frozenset[str]):
        if "aac" in codecs:
            return "aac"
        if "alac" in codecs:
            return "alac"
        return None
