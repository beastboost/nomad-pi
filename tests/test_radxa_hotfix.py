"""Regression coverage for the first Nomad 2 Radxa/iPhone field fixes."""

from pathlib import Path
from types import SimpleNamespace

from app.services.platform_info import _classify
from app.services.playback.compat import BrowserPlaybackPlanner
from app.services.playback.encoders import video_encoder_candidates
from app.services.playback.gstreamer_a733 import a733_backend_allowed, build_a733_hls_command
from app.services.playback.hls import build_hls_command, streaming_input_readrate
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


def test_sun60iw2_is_classified_as_allwinner_a733():
    family, vendor, soc = _classify("sun60iw2", "allwinner,sun60iw2", "")
    assert family == "allwinner-a733"
    assert soc == "allwinner-a733"
    assert vendor in {"Allwinner", "Radxa"}


def test_sun60iw2_prefers_omx_over_generic_v4l2_when_both_exist():
    candidates = video_encoder_candidates(
        "h264",
        available={"h264_v4l2m2m", "h264_omx", "libx264"},
        policy="auto",
        model="sun60iw2",
    )
    assert candidates == ["h264_omx", "libx264"]


def test_a733_gstreamer_worker_command_sets_vendor_decoder_rank(tmp_path):
    cmd = build_a733_hls_command(
        source_path="/media/movie.mkv",
        output_dir=tmp_path,
        start_position=12.5,
        width=1280,
        height=720,
        max_bitrate=4_000_000,
    )
    joined = " ".join(cmd)
    assert "GST_PLUGIN_FEATURE_RANK=omxh264dec:MAX,omxhevcvideodec:MAX,omxvp9videodec:MAX" in cmd
    assert "gst-a733-hls.py" in joined
    assert "--source /media/movie.mkv" in joined
    assert "--start 12.500" in joined
    assert "--width 1280 --height 720" in joined
    assert "--bitrate 4000000" in joined


def test_a733_backend_requires_validated_omx_and_default_tracks(monkeypatch):
    monkeypatch.delenv("NOMAD_A733_GSTREAMER", raising=False)
    monkeypatch.setattr(
        "app.services.playback.gstreamer_a733.a733_gstreamer_status",
        lambda: {"usable": True},
    )
    assert a733_backend_allowed(
        target_video_codec="h264",
        audio_stream_index=None,
        subtitle_stream_index=None,
    ) is True
    assert a733_backend_allowed(
        target_video_codec="hevc",
        audio_stream_index=None,
        subtitle_stream_index=None,
    ) is False
    assert a733_backend_allowed(
        target_video_codec="h264",
        audio_stream_index=2,
        subtitle_stream_index=None,
    ) is False
    assert a733_backend_allowed(
        target_video_codec="h264",
        audio_stream_index=None,
        subtitle_stream_index=4,
    ) is False


def test_a733_backend_can_be_disabled(monkeypatch):
    monkeypatch.setenv("NOMAD_A733_GSTREAMER", "off")
    monkeypatch.setattr(
        "app.services.playback.gstreamer_a733.a733_gstreamer_status",
        lambda: {"usable": True},
    )
    assert a733_backend_allowed(
        target_video_codec="h264",
        audio_stream_index=None,
        subtitle_stream_index=None,
    ) is False


def test_nomad_external_mount_is_stored_as_data_web_root(tmp_path, monkeypatch):
    from app.routers import system_storage_policy as policy

    data = tmp_path / "data"
    mount = data / "external" / "usb-media"
    mount.mkdir(parents=True)
    monkeypatch.setattr(policy, "_data_root", lambda: str(data))

    assert policy._web_root_for_mount(Path(mount).resolve()) == "/data/external/usb-media"


def test_low_memory_remux_defaults_to_two_x_readrate(monkeypatch):
    monkeypatch.delenv("NOMAD_HLS_READRATE", raising=False)
    monkeypatch.setattr(
        "app.services.playback.hls.psutil.virtual_memory",
        lambda: SimpleNamespace(total=1024 * 1024 * 1024),
    )
    assert streaming_input_readrate(PlaybackMode.REMUX) == 2.0
    assert streaming_input_readrate(PlaybackMode.TRANSCODE_AUDIO) == 2.0
    assert streaming_input_readrate(PlaybackMode.TRANSCODE_VIDEO) is None


def test_remux_hls_command_uses_event_playlist_and_readrate(tmp_path):
    cmd = build_hls_command(
        source_path="movie.mkv",
        output_dir=Path(tmp_path),
        mode="remux",
        target_video_codec=None,
        target_audio_codec=None,
        source_video_codec="h264",
        input_readrate=2.0,
        readrate_supported=True,
    )
    assert cmd[cmd.index("-readrate") + 1] == "2.000"
    assert "-re" not in cmd
    assert cmd[cmd.index("-hls_playlist_type") + 1] == "event"
    assert cmd[cmd.index("-avoid_negative_ts") + 1] == "make_zero"


def test_legacy_ffmpeg_falls_back_to_re_instead_of_readrate(tmp_path):
    cmd = build_hls_command(
        source_path="movie.mkv",
        output_dir=Path(tmp_path),
        mode="remux",
        target_video_codec=None,
        target_audio_codec=None,
        source_video_codec="h264",
        input_readrate=2.0,
        readrate_supported=False,
    )
    assert "-readrate" not in cmd
    assert "-re" in cmd
    assert cmd.index("-re") < cmd.index("-i")


def test_one_gib_device_uses_sequential_quality_handover(monkeypatch):
    from app.routers import playback_quality

    monkeypatch.delenv("NOMAD_PLAYBACK_HANDOVER", raising=False)
    monkeypatch.setattr(
        "app.routers.playback_quality.psutil.virtual_memory",
        lambda: SimpleNamespace(total=1024 * 1024 * 1024),
    )
    assert playback_quality._sequential_handover_required() is True
