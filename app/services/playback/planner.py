"""Capability-driven playback planning for Nomad Pi.

This module decides *what kind* of playback is required. Execution belongs in
the playback/transcoding layer. Keeping planning pure makes it cheap to test
and safe on low-power SBCs.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Tuple


class PlaybackMode(str, Enum):
    DIRECT_PLAY = "direct_play"
    REMUX = "remux"
    TRANSCODE_AUDIO = "transcode_audio"
    TRANSCODE_VIDEO = "transcode_video"
    UNSUPPORTED = "unsupported"


def _normalise(values: Iterable[str]) -> frozenset[str]:
    return frozenset(str(value).strip().lower() for value in values if str(value).strip())


@dataclass(frozen=True)
class ClientCapabilities:
    """Media formats and limits reported by a playback client."""

    containers: frozenset[str] = field(default_factory=frozenset)
    video_codecs: frozenset[str] = field(default_factory=frozenset)
    audio_codecs: frozenset[str] = field(default_factory=frozenset)
    subtitle_formats: frozenset[str] = field(default_factory=frozenset)
    max_width: Optional[int] = None
    max_height: Optional[int] = None
    max_bitrate: Optional[int] = None

    @classmethod
    def from_values(
        cls,
        *,
        containers: Iterable[str] = (),
        video_codecs: Iterable[str] = (),
        audio_codecs: Iterable[str] = (),
        subtitle_formats: Iterable[str] = (),
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        max_bitrate: Optional[int] = None,
    ) -> "ClientCapabilities":
        return cls(
            containers=_normalise(containers),
            video_codecs=_normalise(video_codecs),
            audio_codecs=_normalise(audio_codecs),
            subtitle_formats=_normalise(subtitle_formats),
            max_width=max_width,
            max_height=max_height,
            max_bitrate=max_bitrate,
        )


@dataclass(frozen=True)
class MediaProbe:
    """The subset of ffprobe information needed by the playback core."""

    container: str
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    bitrate: Optional[int] = None
    duration: Optional[float] = None
    video_profile: Optional[str] = None
    pixel_format: Optional[str] = None
    codec_tag: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "container", (self.container or "").strip().lower())
        object.__setattr__(self, "video_codec", _clean_optional(self.video_codec))
        object.__setattr__(self, "audio_codec", _clean_optional(self.audio_codec))
        object.__setattr__(self, "video_profile", _clean_optional(self.video_profile))
        object.__setattr__(self, "pixel_format", _clean_optional(self.pixel_format))
        object.__setattr__(self, "codec_tag", _clean_optional(self.codec_tag))

    @property
    def has_video(self) -> bool:
        return bool(self.video_codec)

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_codec)


@dataclass(frozen=True)
class PlaybackPlan:
    mode: PlaybackMode
    reasons: Tuple[str, ...] = ()
    target_container: Optional[str] = None
    target_video_codec: Optional[str] = None
    target_audio_codec: Optional[str] = None

    @property
    def requires_ffmpeg(self) -> bool:
        return self.mode in {
            PlaybackMode.REMUX,
            PlaybackMode.TRANSCODE_AUDIO,
            PlaybackMode.TRANSCODE_VIDEO,
        }


class PlaybackPlanner:
    """Choose the cheapest viable playback path for a client."""

    def plan(self, source: MediaProbe, client: ClientCapabilities) -> PlaybackPlan:
        reasons = []

        container_supported = bool(source.container and source.container in client.containers)
        video_supported = not source.has_video or source.video_codec in client.video_codecs
        audio_supported = not source.has_audio or source.audio_codec in client.audio_codecs

        if not container_supported:
            reasons.append(f"container '{source.container or 'unknown'}' is not supported")
        if source.has_video and not video_supported:
            reasons.append(f"video codec '{source.video_codec}' is not supported")
        if source.has_audio and not audio_supported:
            reasons.append(f"audio codec '{source.audio_codec}' is not supported")

        limit_reasons = self._video_limit_reasons(source, client)
        reasons.extend(limit_reasons)
        video_limits_ok = not limit_reasons

        if container_supported and video_supported and audio_supported and video_limits_ok:
            return PlaybackPlan(mode=PlaybackMode.DIRECT_PLAY)

        if source.has_video and (not video_supported or not video_limits_ok):
            target_video = self._choose_video_codec(client.video_codecs)
            if not target_video:
                return PlaybackPlan(
                    mode=PlaybackMode.UNSUPPORTED,
                    reasons=tuple(reasons + ["client reported no usable video codec"]),
                )

            target_audio = None
            if source.has_audio and not audio_supported:
                target_audio = self._choose_audio_codec(client.audio_codecs)
                if not target_audio:
                    return PlaybackPlan(
                        mode=PlaybackMode.UNSUPPORTED,
                        reasons=tuple(reasons + ["client reported no usable audio codec"]),
                    )

            return PlaybackPlan(
                mode=PlaybackMode.TRANSCODE_VIDEO,
                reasons=tuple(reasons),
                target_container=self._choose_container(client.containers),
                target_video_codec=target_video,
                target_audio_codec=target_audio,
            )

        if source.has_audio and not audio_supported:
            target_audio = self._choose_audio_codec(client.audio_codecs)
            if not target_audio:
                return PlaybackPlan(
                    mode=PlaybackMode.UNSUPPORTED,
                    reasons=tuple(reasons + ["client reported no usable audio codec"]),
                )
            return PlaybackPlan(
                mode=PlaybackMode.TRANSCODE_AUDIO,
                reasons=tuple(reasons),
                target_container=self._choose_container(client.containers),
                target_audio_codec=target_audio,
            )

        if not container_supported:
            target_container = self._choose_container(client.containers)
            if not target_container:
                return PlaybackPlan(
                    mode=PlaybackMode.UNSUPPORTED,
                    reasons=tuple(reasons + ["client reported no usable container"]),
                )
            return PlaybackPlan(
                mode=PlaybackMode.REMUX,
                reasons=tuple(reasons),
                target_container=target_container,
            )

        return PlaybackPlan(
            mode=PlaybackMode.UNSUPPORTED,
            reasons=tuple(reasons or ["no viable playback path"]),
        )

    @staticmethod
    def _video_limit_reasons(source: MediaProbe, client: ClientCapabilities) -> list[str]:
        reasons = []
        if not source.has_video:
            return reasons
        if client.max_width and source.width and source.width > client.max_width:
            reasons.append(f"video width {source.width} exceeds client limit {client.max_width}")
        if client.max_height and source.height and source.height > client.max_height:
            reasons.append(f"video height {source.height} exceeds client limit {client.max_height}")
        if client.max_bitrate and source.bitrate and source.bitrate > client.max_bitrate:
            reasons.append(f"bitrate {source.bitrate} exceeds client limit {client.max_bitrate}")
        return reasons

    @staticmethod
    def _choose_container(containers: frozenset[str]) -> Optional[str]:
        for preferred in ("mp4", "webm", "m4a", "ogg"):
            if preferred in containers:
                return preferred
        return sorted(containers)[0] if containers else None

    @staticmethod
    def _choose_video_codec(codecs: frozenset[str]) -> Optional[str]:
        for preferred in ("h264", "avc", "vp9", "av1", "hevc", "h265"):
            if preferred in codecs:
                return preferred
        return sorted(codecs)[0] if codecs else None

    @staticmethod
    def _choose_audio_codec(codecs: frozenset[str]) -> Optional[str]:
        for preferred in ("aac", "opus", "mp3", "vorbis"):
            if preferred in codecs:
                return preferred
        return sorted(codecs)[0] if codecs else None


def _clean_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip().lower()
    return cleaned or None
