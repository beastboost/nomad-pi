"""Regression coverage for the first Nomad 2 Radxa/iPhone field fixes."""

from pathlib import Path

from app.services.playback.compat import BrowserPlaybackPlanner
from app.services.playback.encoders import video_encoder_candidates
from app.services.playback.planner import ClientCapabilities, MediaProbe, PlaybackMode


def iphone_like_caps():
    return ClientCapabilities.from_values(
        containers=["mp4", "m4a", "mp3"],
        video_codecs=["h264", "hevc"],
        audio_codecs=["aac", "mp3"],
        subtitle_formats=["vtt"],
    )


def test_generated_fmp4_remux_keeps_safe_h264_aac():
    planner = BrowserPlaybackPlanner()
    plan = planner.plan(
        MediaProbe(container="matroska", video_codec="h264", audio_codec="aac"),
        iphone_like_caps(),
    )
    assert plan.mode == PlaybackMode.REMUX
    assert plan.target_container == "mp4"


def test_generated_fmp4_converts_mp3_audio_even_if_phone_supports_mp3_elsewhere():
    planner = BrowserPlaybackPlanner()
    plan = planner.plan(
        MediaProbe(container="matroska", video_codec="h264", audio_codec="mp3"),
        iphone_like_caps(),
    )
    assert plan.mode == PlaybackMode.TRANSCODE_AUDIO
    assert plan.target_audio_codec == "aac"
    assert plan.target_container == "mp4"


def test_generated_fmp4_converts_unsafe_video_codec_to_h264():
    caps = ClientCapabilities.from_values(
        containers=["mp4", "webm"],
        video_codecs=["vp9", "h264"],
        audio_codecs=["aac"],
    )
    planner = BrowserPlaybackPlanner()
    plan = planner.plan(
        MediaProbe(container="matroska", video_codec="vp9", audio_codec="aac"),
        caps,
    )
    assert plan.mode == PlaybackMode.TRANSCODE_VIDEO
    assert plan.target_video_codec == "h264"
    assert plan.target_container == "mp4"


def test_high10_h264_does_not_direct_play_on_iphone():
    planner = BrowserPlaybackPlanner()
    plan = planner.plan(
        MediaProbe(
            container="mp4",
            video_codec="h264",
            audio_codec="aac",
            video_profile="High 10",
            pixel_format="yuv420p10le",
            codec_tag="avc1",
        ),
        iphone_like_caps(),
    )
    assert plan.mode == PlaybackMode.TRANSCODE_VIDEO
    assert plan.target_video_codec == "h264"


def test_hev1_hevc_is_remuxed_to_hvc1_instead_of_direct_play():
    planner = BrowserPlaybackPlanner()
    plan = planner.plan(
        MediaProbe(
            container="mp4",
            video_codec="hevc",
            audio_codec="aac",
            pixel_format="yuv420p10le",
            codec_tag="hev1",
        ),
        iphone_like_caps(),
    )
    assert plan.mode == PlaybackMode.REMUX
    assert plan.target_container == "mp4"
    assert "hvc1" in " ".join(plan.reasons)


def test_ffmpeg_openmax_is_preferred_before_software_when_available():
    candidates = video_encoder_candidates(
        "h264",
        available={"h264_omx", "libx264"},
        policy="auto",
    )
    assert candidates == ["h264_omx", "libx264"]


def test_nomad_external_mount_is_stored_as_data_web_root(tmp_path, monkeypatch):
    from app.routers import system_storage_policy as policy

    data = tmp_path / "data"
    mount = data / "external" / "usb-media"
    mount.mkdir(parents=True)
    monkeypatch.setattr(policy, "_data_root", lambda: str(data))

    assert policy._web_root_for_mount(Path(mount).resolve()) == "/data/external/usb-media"
