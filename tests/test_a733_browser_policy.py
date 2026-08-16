from app.services.playback import a733_browser_policy as policy_module
from app.services.playback.a733_browser_policy import A733BrowserPlaybackPlanner
from app.services.playback.planner import ClientCapabilities, MediaProbe, PlaybackMode


def iphone_caps():
    return ClientCapabilities.from_values(
        containers=["mp4"],
        video_codecs=["h264", "hevc"],
        audio_codecs=["aac"],
        subtitle_formats=["vtt"],
    )


def enable_a733_omx(monkeypatch):
    monkeypatch.setattr(policy_module, "platform_info", lambda: {"is_allwinner_a733": True})
    monkeypatch.setattr(policy_module, "a733_gstreamer_status", lambda: {"usable": True})


def test_clean_hvc1_hevc_direct_play_stays_direct(monkeypatch):
    enable_a733_omx(monkeypatch)
    planner = A733BrowserPlaybackPlanner()
    plan = planner.plan(
        MediaProbe(container="mp4", video_codec="hevc", audio_codec="aac", codec_tag="hvc1"),
        iphone_caps(),
    )
    assert plan.mode == PlaybackMode.DIRECT_PLAY


def test_hev1_hevc_is_escalated_from_remux_to_h264_omx_target(monkeypatch):
    enable_a733_omx(monkeypatch)
    planner = A733BrowserPlaybackPlanner()
    plan = planner.plan(
        MediaProbe(container="mp4", video_codec="hevc", audio_codec="aac", codec_tag="hev1"),
        iphone_caps(),
    )
    assert plan.mode == PlaybackMode.TRANSCODE_VIDEO
    assert plan.target_video_codec == "h264"
    assert plan.target_container == "mp4"
    assert "A733 Safari compatibility" in " ".join(plan.reasons)


def test_hevc_mkv_non_direct_path_uses_h264_on_validated_a733(monkeypatch):
    enable_a733_omx(monkeypatch)
    planner = A733BrowserPlaybackPlanner()
    plan = planner.plan(
        MediaProbe(container="matroska", video_codec="hevc", audio_codec="aac"),
        iphone_caps(),
    )
    assert plan.mode == PlaybackMode.TRANSCODE_VIDEO
    assert plan.target_video_codec == "h264"


def test_hevc_keeps_generic_remux_when_a733_backend_is_unavailable(monkeypatch):
    monkeypatch.setattr(policy_module, "platform_info", lambda: {"is_allwinner_a733": True})
    monkeypatch.setattr(policy_module, "a733_gstreamer_status", lambda: {"usable": False})
    planner = A733BrowserPlaybackPlanner()
    plan = planner.plan(
        MediaProbe(container="mp4", video_codec="hevc", audio_codec="aac", codec_tag="hev1"),
        iphone_caps(),
    )
    assert plan.mode == PlaybackMode.REMUX


def test_h264_mkv_remains_cheap_remux(monkeypatch):
    enable_a733_omx(monkeypatch)
    planner = A733BrowserPlaybackPlanner()
    plan = planner.plan(
        MediaProbe(container="matroska", video_codec="h264", audio_codec="aac"),
        iphone_caps(),
    )
    assert plan.mode == PlaybackMode.REMUX
