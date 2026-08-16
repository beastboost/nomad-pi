from pathlib import Path

from app.services.playback import hls as hls_module
from app.services.playback import remux_stability
from app.services.playback.planner import PlaybackMode


def test_legacy_ffmpeg_drops_one_x_re_fallback(monkeypatch):
    monkeypatch.setattr(remux_stability, "_ORIGINAL_READRATE", lambda _mode: 2.0)
    monkeypatch.setattr(hls_module, "ffmpeg_supports_readrate", lambda _path=None: False)

    assert remux_stability._effective_streaming_readrate(PlaybackMode.REMUX) is None
    assert remux_stability._effective_streaming_readrate(PlaybackMode.TRANSCODE_AUDIO) is None


def test_modern_ffmpeg_keeps_two_x_readrate(monkeypatch):
    monkeypatch.setattr(remux_stability, "_ORIGINAL_READRATE", lambda _mode: 2.0)
    monkeypatch.setattr(hls_module, "ffmpeg_supports_readrate", lambda _path=None: True)

    assert remux_stability._effective_streaming_readrate(PlaybackMode.REMUX) == 2.0


def test_cheap_hls_command_removes_re_generates_pts_and_preserves_timebase(monkeypatch):
    monkeypatch.setattr(
        remux_stability,
        "_ORIGINAL_BUILD",
        lambda **_kwargs: [
            "ffmpeg", "-hide_banner", "-re", "-i", "movie.mkv",
            "-c:v", "copy", "index.m3u8",
        ],
    )

    cmd = remux_stability._stable_build_hls_command(mode="remux")
    assert "-re" not in cmd
    assert cmd[cmd.index("-fflags") + 1] == "+genpts"
    assert cmd.index("-fflags") < cmd.index("-i")
    assert cmd[cmd.index("-copytb") + 1] == "1"
    assert cmd.index("-copytb") > cmd.index("-i")


def test_audio_transcode_also_preserves_copied_video_timebase(monkeypatch):
    monkeypatch.setattr(
        remux_stability,
        "_ORIGINAL_BUILD",
        lambda **_kwargs: [
            "ffmpeg", "-i", "movie.mkv", "-c:v", "copy", "-c:a", "aac", "index.m3u8",
        ],
    )

    cmd = remux_stability._stable_build_hls_command(mode="transcode_audio")
    assert cmd[cmd.index("-copytb") + 1] == "1"


def test_video_transcode_command_is_not_rewritten(monkeypatch):
    original = ["ffmpeg", "-i", "movie.mkv", "-c:v", "libx264", "index.m3u8"]
    monkeypatch.setattr(remux_stability, "_ORIGINAL_BUILD", lambda **_kwargs: list(original))

    assert remux_stability._stable_build_hls_command(mode="transcode_video") == original


def test_playlist_segment_counter_ignores_hls_tags(tmp_path):
    playlist = Path(tmp_path) / "index.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\"\n#EXTINF:4.0,\nsegment_00000.m4s\n"
        "#EXTINF:4.0,\nsegment_00001.m4s\n",
        encoding="utf-8",
    )
    assert remux_stability._segment_count(playlist) == 2


def test_low_priority_wrapper_prefers_io_and_cpu_niceness(monkeypatch):
    def fake_which(name):
        return {"ionice": "/usr/bin/ionice", "nice": "/usr/bin/nice"}.get(name)

    monkeypatch.setattr(remux_stability.shutil, "which", fake_which)
    cmd = remux_stability._low_priority_command(["ffmpeg", "-i", "movie.mkv"])

    assert cmd[:5] == ["/usr/bin/ionice", "-c", "2", "-n", "7"]
    assert cmd[5:8] == ["/usr/bin/nice", "-n", "5"]
    assert cmd[8:] == ["ffmpeg", "-i", "movie.mkv"]
