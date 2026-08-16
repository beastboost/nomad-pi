from types import SimpleNamespace

from app.services.playback import remux_stability
from app.services.playback.planner import PlaybackMode


def _fake_command(**kwargs):
    return [
        "ffmpeg", "-i", "input.mp4",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        "output.m3u8",
    ]


def test_tiny_memory_audio_fallback_downmixes_to_stereo(monkeypatch):
    monkeypatch.delenv("NOMAD_HLS_AUDIO_CHANNELS", raising=False)
    monkeypatch.setattr(remux_stability, "_ORIGINAL_BUILD", _fake_command)
    monkeypatch.setattr(
        remux_stability.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=512 * 1024 * 1024),
    )

    cmd = remux_stability._stable_build_hls_command(
        mode=PlaybackMode.TRANSCODE_AUDIO,
        target_audio_codec="aac",
    )

    ac = cmd.index("-ac")
    assert cmd[ac + 1] == "2"


def test_large_host_preserves_source_channel_count_by_default(monkeypatch):
    monkeypatch.delenv("NOMAD_HLS_AUDIO_CHANNELS", raising=False)
    monkeypatch.setattr(remux_stability, "_ORIGINAL_BUILD", _fake_command)
    monkeypatch.setattr(
        remux_stability.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=4 * 1024 * 1024 * 1024),
    )

    cmd = remux_stability._stable_build_hls_command(
        mode=PlaybackMode.TRANSCODE_AUDIO,
        target_audio_codec="aac",
    )

    assert "-ac" not in cmd


def test_audio_channel_override_can_preserve_source(monkeypatch):
    monkeypatch.setenv("NOMAD_HLS_AUDIO_CHANNELS", "off")
    monkeypatch.setattr(remux_stability, "_ORIGINAL_BUILD", _fake_command)
    monkeypatch.setattr(
        remux_stability.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=512 * 1024 * 1024),
    )

    cmd = remux_stability._stable_build_hls_command(
        mode=PlaybackMode.TRANSCODE_AUDIO,
        target_audio_codec="aac",
    )

    assert "-ac" not in cmd
