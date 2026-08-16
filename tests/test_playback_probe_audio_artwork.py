import json
from types import SimpleNamespace

from app.routers import playback_music
from app.services.playback import probe as probe_module


def test_probe_ignores_attached_album_artwork(tmp_path, monkeypatch):
    media = tmp_path / "track.mp3"
    media.write_bytes(b"x")

    payload = {
        "format": {"format_name": "mp3", "duration": "180.0", "bit_rate": "320000"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "mjpeg",
                "width": 1000,
                "height": 1000,
                "disposition": {"attached_pic": 1},
            },
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "disposition": {"attached_pic": 0},
            },
        ],
    }

    monkeypatch.setattr(
        probe_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""),
    )

    result = probe_module.probe_media(str(media))
    assert result.container == "mp3"
    assert result.audio_codec == "mp3"
    assert result.video_codec is None
    assert result.width is None
    assert result.height is None


def test_probe_keeps_real_video_stream(tmp_path, monkeypatch):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")

    payload = {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "10.0"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "disposition": {"attached_pic": 0},
            },
            {"codec_type": "audio", "codec_name": "aac", "disposition": {"attached_pic": 0}},
        ],
    }
    monkeypatch.setattr(
        probe_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""),
    )

    result = probe_module.probe_media(str(media))
    assert result.video_codec == "h264"
    assert result.audio_codec == "aac"
    assert (result.width, result.height) == (1920, 1080)


def test_music_resolver_allows_legal_artist_filename_characters(tmp_path, monkeypatch):
    monkeypatch.setattr(playback_music.media, "BASE_DIR", str(tmp_path))
    music = tmp_path / "music"
    music.mkdir()
    track = music / "$NOT & Friends - Track + Mix.mp3"
    track.write_bytes(b"abc")

    resolved = playback_music._music_fs_path("/data/music/$NOT & Friends - Track + Mix.mp3")
    assert resolved == str(track.resolve())


def test_music_resolver_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(playback_music.media, "BASE_DIR", str(tmp_path))
    try:
        playback_music._music_fs_path("/data/../secret.mp3")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("Traversal must be rejected")
