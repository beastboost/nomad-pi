"""Compatibility adjustments for browser/fMP4 playback."""

from __future__ import annotations

from .planner import ClientCapabilities, MediaProbe, PlaybackMode, PlaybackPlan, PlaybackPlanner


FMP4_VIDEO_COPY = {"h264", "avc", "hevc", "h265"}
FMP4_AUDIO_COPY = {"aac", "alac"}
SAFE_H264_PIXEL_FORMATS = {"yuv420p", "yuvj420p", "nv12"}


class BrowserPlaybackPlanner(PlaybackPlanner):
    """Prefer Apple-safe direct play and generated fMP4 HLS."""

    def plan(self, source: MediaProbe, client: ClientCapabilities) -> PlaybackPlan:
        base = super().plan(source, client)
        if base.mode == PlaybackMode.UNSUPPORTED:
            return base

        # Codec-family support is not enough for Safari. High-10/10-bit H.264
        # is a frequent example: canPlayType(H.264) is true but this stream is
        # not a normal iPhone hardware-decode target. Convert it to 8-bit H.264.
        if source.video_codec in {"h264", "avc"} and self._unsafe_h264(source):
            target_video = self._choose_hls_video(client.video_codecs)
            if not target_video:
                return PlaybackPlan(
                    mode=PlaybackMode.UNSUPPORTED,
                    reasons=("H.264 profile/pixel format is not browser-safe and no compatible video target is available",),
                )
            target_audio = None
            if source.has_audio and source.audio_codec not in FMP4_AUDIO_COPY:
                target_audio = self._choose_hls_audio(client.audio_codecs)
            return PlaybackPlan(
                mode=PlaybackMode.TRANSCODE_VIDEO,
                reasons=(f"H.264 {source.video_profile or ''} {source.pixel_format or ''} requires 8-bit browser-compatible output".strip(),),
                target_container="mp4",
                target_video_codec="h264" if "h264" in client.video_codecs or "avc" in client.video_codecs else target_video,
                target_audio_codec=target_audio,
            )

        # HEVC in MP4 can be decodable but signalled with the hev1 sample entry,
        # which is less reliable on Apple clients. A cheap remux lets FFmpeg
        # retag it as hvc1 without touching the video bitstream.
        if (
            base.mode == PlaybackMode.DIRECT_PLAY
            and source.video_codec in {"hevc", "h265"}
            and source.container in {"mp4", "mov"}
            and source.codec_tag
            and source.codec_tag != "hvc1"
        ):
            return PlaybackPlan(
                mode=PlaybackMode.REMUX,
                reasons=(f"HEVC sample entry '{source.codec_tag}' will be retagged as hvc1 for Apple playback",),
                target_container="mp4",
            )

        if base.mode == PlaybackMode.DIRECT_PLAY:
            return base

        reasons = list(base.reasons)
        video_copy_safe = not source.has_video or source.video_codec in FMP4_VIDEO_COPY
        audio_copy_safe = not source.has_audio or source.audio_codec in FMP4_AUDIO_COPY

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

        if base.mode == PlaybackMode.REMUX:
            return PlaybackPlan(
                mode=PlaybackMode.REMUX,
                reasons=base.reasons,
                target_container="mp4",
            )

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
    def _unsafe_h264(source: MediaProbe) -> bool:
        profile = str(source.video_profile or "").lower()
        pix = str(source.pixel_format or "").lower()
        if "high 10" in profile or "high10" in profile or "10 bit" in profile:
            return True
        if pix and pix not in SAFE_H264_PIXEL_FORMATS:
            return True
        return False

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
