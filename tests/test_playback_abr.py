from pathlib import Path

from app.services.playback.abr import (
    ABRRendition,
    abr_available,
    build_abr_command,
    choose_renditions,
)


def _arg_after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def test_4k_source_gets_full_adaptive_ladder():
    ladder = choose_renditions(3840, 2160)
    assert [r.name for r in ladder] == ["1080p", "720p", "480p"]


def test_client_limit_reduces_adaptive_ladder():
    ladder = choose_renditions(3840, 2160, max_width=1280, max_height=720, max_bitrate=4_000_000)
    assert [r.name for r in ladder] == ["720p", "480p"]
    assert max(r.bitrate for r in ladder) <= 4_000_000


def test_adaptive_never_upscales_source():
    ladder = choose_renditions(1280, 720)
    assert [r.name for r in ladder] == ["720p", "480p"]


def test_auto_adaptive_requires_hardware_without_software_opt_in(monkeypatch):
    monkeypatch.setenv("NOMAD_HW_ACCEL", "auto")
    monkeypatch.delenv("NOMAD_ABR_SOFTWARE", raising=False)
    allowed, _, candidates = abr_available(
        available_encoders={"libx264"},
        policy="auto",
    )
    assert candidates == ["libx264"]
    assert allowed is False


def test_auto_adaptive_accepts_sbc_hardware(monkeypatch):
    monkeypatch.setenv("NOMAD_HW_ACCEL", "auto")
    allowed, reason, candidates = abr_available(
        available_encoders={"h264_v4l2m2m", "libx264"},
        policy="auto",
    )
    assert allowed is True
    assert candidates[0] == "h264_v4l2m2m"
    assert "h264_v4l2m2m" in reason


def test_abr_command_builds_named_fmp4_master_and_variants(tmp_path):
    renditions = [
        ABRRendition("720p", 1280, 720, 4_000_000),
        ABRRendition("480p", 854, 480, 2_000_000),
    ]
    cmd = build_abr_command(
        source_path="movie.mkv",
        output_dir=Path(tmp_path),
        renditions=renditions,
        video_encoder="libx264",
        audio_stream_index=2,
        start_position=120.5,
    )
    assert _arg_after(cmd, "-ss") == "120.500"
    graph = _arg_after(cmd, "-filter_complex")
    assert "split=2" in graph
    assert "scale=1280:720" in graph
    assert "scale=854:480" in graph
    stream_map = _arg_after(cmd, "-var_stream_map")
    assert "name:720p" in stream_map
    assert "name:480p" in stream_map
    assert _arg_after(cmd, "-master_pl_name") == "master.m3u8"
    assert _arg_after(cmd, "-hls_fmp4_init_filename") == "init_%v.mp4"
    assert str(Path(tmp_path) / "segment_%v_%05d.m4s") in cmd
    assert "0:2?" in cmd


def test_abr_command_can_burn_bitmap_subtitle_before_split(tmp_path):
    cmd = build_abr_command(
        source_path="movie.mkv",
        output_dir=Path(tmp_path),
        renditions=[
            ABRRendition("720p", 1280, 720, 4_000_000),
            ABRRendition("480p", 854, 480, 2_000_000),
        ],
        video_encoder="h264_v4l2m2m",
        subtitle_stream_index=5,
    )
    graph = _arg_after(cmd, "-filter_complex")
    assert "[0:v:0][0:5]overlay[base]" in graph
    assert "[base]split=2" in graph
