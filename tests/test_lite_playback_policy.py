from types import SimpleNamespace

from app.services.playback.lite_browser_policy import LiteBrowserPlaybackPlanner
from app.services.playback.planner import ClientCapabilities, MediaProbe, PlaybackMode


def iphone_caps():
    return ClientCapabilities.from_values(
        containers=["mp4", "m4a", "mp3"],
        video_codecs=["h264", "hevc"],
        audio_codecs=["aac", "mp3"],
        subtitle_formats=["vtt"],
    )


def enable_lite(monkeypatch):
    monkeypatch.delenv("NOMAD_LITE_PLAYBACK", raising=False)
    monkeypatch.delenv("NOMAD_LIVE_VIDEO_TRANSCODE", raising=False)
    monkeypatch.setattr(
        "app.services.playback.lite_browser_policy.psutil.virtual_memory",
        lambda: SimpleNamespace(total=1024 * 1024 * 1024),
    )


def test_direct_h264_mp4_stays_direct(monkeypatch):
    enable_lite(monkeypatch)
    plan = LiteBrowserPlaybackPlanner().plan(
        MediaProbe(container="mp4", video_codec="h264", audio_codec="aac", pixel_format="yuv420p", codec_tag="avc1"),
        iphone_caps(),
    )
    assert plan.mode == PlaybackMode.DIRECT_PLAY


def test_h264_mkv_can_still_use_cheap_remux(monkeypatch):
    enable_lite(monkeypatch)
    plan = LiteBrowserPlaybackPlanner().plan(
        MediaProbe(container="mkv", video_codec="h264", audio_codec="aac", pixel_format="yuv420p"),
        iphone_caps(),
    )
    assert plan.mode == PlaybackMode.REMUX


def test_non_direct_hevc_is_rejected_in_lite_mode(monkeypatch):
    enable_lite(monkeypatch)
    plan = LiteBrowserPlaybackPlanner().plan(
        MediaProbe(container="mp4", video_codec="hevc", audio_codec="aac", pixel_format="yuv420p10le", codec_tag="hev1"),
        iphone_caps(),
    )
    assert plan.mode == PlaybackMode.UNSUPPORTED
    assert "Lite playback mode" in " ".join(plan.reasons)


def test_vp9_live_video_transcode_is_rejected_in_lite_mode(monkeypatch):
    enable_lite(monkeypatch)
    caps = ClientCapabilities.from_values(containers=["mp4"], video_codecs=["h264"], audio_codecs=["aac"])
    plan = LiteBrowserPlaybackPlanner().plan(
        MediaProbe(container="mkv", video_codec="vp9", audio_codec="aac"),
        caps,
    )
    assert plan.mode == PlaybackMode.UNSUPPORTED


def test_live_video_transcode_can_be_explicitly_enabled(monkeypatch):
    enable_lite(monkeypatch)
    monkeypatch.setenv("NOMAD_LIVE_VIDEO_TRANSCODE", "1")
    caps = ClientCapabilities.from_values(containers=["mp4"], video_codecs=["h264"], audio_codecs=["aac"])
    plan = LiteBrowserPlaybackPlanner().plan(
        MediaProbe(container="mkv", video_codec="vp9", audio_codec="aac"),
        caps,
    )
    assert plan.mode == PlaybackMode.TRANSCODE_VIDEO
