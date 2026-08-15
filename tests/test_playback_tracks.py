import json
from types import SimpleNamespace

from app.routers import playback_tracks
from app.services.playback.tracks import probe_tracks


def test_probe_tracks_exposes_audio_and_subtitle_metadata(tmp_path, monkeypatch):
    media = tmp_path / "sample.mkv"
    media.write_bytes(b"fixture")

    payload = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "tags": {},
                "disposition": {"default": 1, "forced": 0},
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 6,
                "channel_layout": "5.1",
                "tags": {"language": "eng", "title": "Main"},
                "disposition": {"default": 1, "forced": 0},
            },
            {
                "index": 2,
                "codec_type": "audio",
                "codec_name": "dts",
                "channels": 6,
                "channel_layout": "5.1",
                "tags": {"language": "jpn"},
                "disposition": {"default": 0, "forced": 0},
            },
            {
                "index": 3,
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "tags": {"language": "eng"},
                "disposition": {"default": 1, "forced": 0},
            },
            {
                "index": 4,
                "codec_type": "subtitle",
                "codec_name": "hdmv_pgs_subtitle",
                "tags": {"language": "eng", "title": "Signs"},
                "disposition": {"default": 0, "forced": 1},
            },
        ]
    }

    monkeypatch.setattr(
        "app.services.playback.tracks.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )

    tracks = probe_tracks(str(media))
    assert tracks["video"][0]["stream_index"] == 0
    assert tracks["audio"][0]["language"] == "eng"
    assert tracks["audio"][0]["channel_layout"] == "5.1"
    assert tracks["audio"][1]["codec"] == "dts"
    assert tracks["subtitles"][0]["text_supported"] is True
    assert tracks["subtitles"][1]["text_supported"] is False
    assert tracks["subtitles"][1]["forced"] is True


def test_subtitle_cache_is_specific_to_source_and_hls_offset(tmp_path, monkeypatch):
    media = tmp_path / "sample.mkv"
    media.write_bytes(b"fixture")
    cache = tmp_path / "subtitle-cache"
    monkeypatch.setattr(playback_tracks, "SUBTITLE_CACHE", cache)

    start = playback_tracks._subtitle_cache_path(str(media), 3, offset=0)
    resumed = playback_tracks._subtitle_cache_path(str(media), 3, offset=1800)
    another_stream = playback_tracks._subtitle_cache_path(str(media), 4, offset=0)

    assert start.parent == cache
    assert start.suffix == ".vtt"
    assert start != resumed
    assert start != another_stream
    assert resumed == playback_tracks._subtitle_cache_path(str(media), 3, offset=1800)
