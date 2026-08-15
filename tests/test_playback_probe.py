import json
from types import SimpleNamespace

from app.services.playback.probe import probe_media


def test_probe_media_captures_source_duration(tmp_path, monkeypatch):
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"fixture")
    payload = {
        "format": {
            "format_name": "matroska,webm",
            "bit_rate": "12000000",
            "duration": "7265.432",
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "bit_rate": "10000000",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "bit_rate": "192000",
            },
        ],
    }

    monkeypatch.setattr(
        "app.services.playback.probe.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )

    result = probe_media(str(media))
    assert result.container == "mkv"
    assert result.video_codec == "h264"
    assert result.audio_codec == "aac"
    assert result.duration == 7265.432
    assert result.bitrate == 12_000_000
