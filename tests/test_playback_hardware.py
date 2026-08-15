from pathlib import Path

import pytest

from app.services.playback.encoders import (
    _parse_encoders,
    is_hardware_encoder,
    video_encoder_args,
    video_encoder_candidates,
)
from app.services.playback.hls import HLSJobError, build_hls_command


def _arg_after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def test_parse_ffmpeg_encoder_listing():
    text = """
 V..... libx264              libx264 H.264 / AVC
 V..... h264_v4l2m2m        V4L2 mem2mem H.264 encoder wrapper
 A..... aac                  AAC (Advanced Audio Coding)
"""
    found = _parse_encoders(text)
    assert {"libx264", "h264_v4l2m2m", "aac"} <= found


def test_auto_prefers_sbc_hardware_then_software():
    available = {"h264_v4l2m2m", "libx264"}
    assert video_encoder_candidates("h264", available=available, policy="auto") == [
        "h264_v4l2m2m",
        "libx264",
    ]


def test_auto_accepts_ffmpeg_openmax_then_software():
    available = {"h264_omx", "libx264"}
    assert video_encoder_candidates("h264", available=available, policy="auto") == [
        "h264_omx",
        "libx264",
    ]
    assert is_hardware_encoder("h264_omx") is True


def test_a733_prefers_openmax_over_generic_v4l2_then_software():
    available = {"h264_v4l2m2m", "h264_omx", "libx264"}
    assert video_encoder_candidates(
        "h264", available=available, policy="auto", model="Radxa Cubie A7Z A733"
    ) == ["h264_omx", "libx264"]


def test_hardware_policy_off_forces_software_candidate():
    available = {"h264_v4l2m2m", "libx264"}
    assert video_encoder_candidates("h264", available=available, policy="off") == ["libx264"]


def test_hardware_force_requires_detected_supported_encoder():
    assert video_encoder_candidates("h264", available={"libx264"}, policy="force") == []


def test_hardware_rate_control_uses_bitrate():
    args = video_encoder_args("h264_v4l2m2m", max_bitrate=4_000_000)
    assert _arg_after(args, "-b:v") == "4000000"
    assert _arg_after(args, "-maxrate") == "4000000"
    assert is_hardware_encoder("h264_v4l2m2m") is True


def test_openmax_rate_control_uses_bitrate():
    args = video_encoder_args("h264_omx", max_bitrate=4_000_000)
    assert _arg_after(args, "-b:v") == "4000000"


def test_pgs_burn_command_overlays_before_scaling(tmp_path):
    cmd = build_hls_command(
        source_path="movie.mkv",
        output_dir=Path(tmp_path),
        mode="transcode_video",
        target_video_codec="h264",
        target_audio_codec="aac",
        subtitle_stream_index=5,
        video_encoder_override="libx264",
        source_width=3840,
        source_height=2160,
        max_width=1280,
        max_height=720,
    )
    graph = _arg_after(cmd, "-filter_complex")
    assert "[0:v:0][0:5]overlay[vsub]" in graph
    assert "[vsub]scale=1280:720[vout]" in graph
    assert _arg_after(cmd, "-map") == "[vout]"
    assert _arg_after(cmd, "-c:v") == "libx264"
    assert _arg_after(cmd, "-pix_fmt") == "yuv420p"


def test_h264_transcode_forces_8bit_yuv420p(tmp_path):
    cmd = build_hls_command(
        source_path="main10.mkv",
        output_dir=Path(tmp_path),
        mode="transcode_video",
        target_video_codec="h264",
        target_audio_codec="aac",
        video_encoder_override="libx264",
    )
    assert _arg_after(cmd, "-pix_fmt") == "yuv420p"


def test_hevc_remux_uses_apple_hvc1_sample_entry(tmp_path):
    cmd = build_hls_command(
        source_path="movie.mkv",
        output_dir=Path(tmp_path),
        mode="remux",
        target_video_codec=None,
        target_audio_codec=None,
        source_video_codec="hevc",
    )
    assert _arg_after(cmd, "-tag:v") == "hvc1"
    assert _arg_after(cmd, "-c:v") == "copy"


def test_image_subtitle_cannot_be_burned_without_video_transcode(tmp_path):
    with pytest.raises(HLSJobError):
        build_hls_command(
            source_path="movie.mkv",
            output_dir=Path(tmp_path),
            mode="remux",
            target_video_codec=None,
            target_audio_codec=None,
            subtitle_stream_index=4,
        )
