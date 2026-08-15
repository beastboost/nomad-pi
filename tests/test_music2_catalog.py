import json
from types import SimpleNamespace

from app.routers import music2


def test_track_disc_and_replaygain_parsing():
    assert music2._first_int("03/12") == 3
    assert music2._first_int("Disc 2") == 2
    assert music2._first_int(None) is None
    assert music2._gain("-7.12 dB") == -7.12
    assert music2._gain("+1.50 dB") == 1.5
    assert music2._gain("") is None


def test_ffprobe_music_tags_are_normalized(monkeypatch, tmp_path):
    source = tmp_path / "Artist" / "Album" / "03 - Track.flac"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake")

    payload = {
        "format": {
            "duration": "245.125",
            "bit_rate": "1411200",
            "tags": {
                "TITLE": "Track Name",
                "ARTIST": "Track Artist",
                "ALBUM_ARTIST": "Album Artist",
                "ALBUM": "Album Name",
                "DATE": "2024-04-12",
                "GENRE": "Electronic",
                "TRACK": "03/12",
                "DISC": "2/2",
                "REPLAYGAIN_TRACK_GAIN": "-6.25 dB",
                "REPLAYGAIN_ALBUM_GAIN": "-5.75 dB",
            },
        },
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "flac",
                "sample_rate": "96000",
                "bits_per_raw_sample": "24",
                "channels": 2,
                "disposition": {"attached_pic": 0},
            },
            {
                "codec_type": "video",
                "codec_name": "mjpeg",
                "disposition": {"attached_pic": 1},
            },
        ],
    }

    monkeypatch.setattr(music2.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        music2.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )

    meta = music2._probe(str(source))
    assert meta["title"] == "Track Name"
    assert meta["artist"] == "Track Artist"
    assert meta["album_artist"] == "Album Artist"
    assert meta["album"] == "Album Name"
    assert meta["track_number"] == 3
    assert meta["disc_number"] == 2
    assert meta["year"] == 2024
    assert meta["genre"] == "Electronic"
    assert meta["duration"] == 245.125
    assert meta["codec"] == "flac"
    assert meta["bitrate"] == 1411200
    assert meta["sample_rate"] == 96000
    assert meta["bit_depth"] == 24
    assert meta["channels"] == 2
    assert meta["replaygain_track_gain"] == -6.25
    assert meta["replaygain_album_gain"] == -5.75
    assert meta["has_artwork"] is True


def test_missing_tags_fall_back_to_artist_album_folders(monkeypatch, tmp_path):
    source = tmp_path / "Artist Name" / "Album Name" / "01 Song Title.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake")
    payload = {
        "format": {"duration": "10", "tags": {}},
        "streams": [{"codec_type": "audio", "codec_name": "mp3", "sample_rate": "44100", "channels": 2}],
    }
    monkeypatch.setattr(music2.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        music2.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""),
    )
    meta = music2._probe(str(source))
    assert meta["title"] == "01 Song Title"
    assert meta["artist"] == "Artist Name"
    assert meta["album"] == "Album Name"


def test_music_catalog_cache_reuses_unchanged_file(monkeypatch, tmp_path):
    db_path = tmp_path / "music.db"
    monkeypatch.setattr(music2.database, "DB_PATH", str(db_path))
    monkeypatch.setattr(music2, "_schema_ready", False)
    music2.ensure_schema()

    source = tmp_path / "track.flac"
    source.write_bytes(b"audio")
    stat = source.stat()
    web_path = "/data/music/track.flac"
    meta = {
        "title": "Track",
        "artist": "Artist",
        "album_artist": "Artist",
        "album": "Album",
        "disc_number": 1,
        "track_number": 1,
        "year": 2026,
        "genre": "Test",
        "duration": 60.0,
        "codec": "flac",
        "bitrate": 1000000,
        "sample_rate": 48000,
        "bit_depth": 24,
        "channels": 2,
        "replaygain_track_gain": -4.0,
        "replaygain_album_gain": -3.0,
        "has_artwork": False,
    }
    conn = music2._connect()
    try:
        music2._upsert(conn, web_path, str(source), meta, stat.st_size, stat.st_mtime_ns)
        conn.commit()
        assert music2._cached_fresh(conn, web_path, stat.st_size, stat.st_mtime_ns) is True
        assert music2._cached_fresh(conn, web_path, stat.st_size + 1, stat.st_mtime_ns) is False
        row = conn.execute("SELECT * FROM music_catalog WHERE path=?", (web_path,)).fetchone()
        assert row["artist"] == "Artist"
        assert row["bit_depth"] == 24
    finally:
        conn.close()
