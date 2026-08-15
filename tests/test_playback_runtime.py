from pathlib import Path

import pytest

from app.routers.playback import parse_byte_range, _ticketed_playlist
from app.services.playback.hls import build_hls_command, fit_dimensions
from app.services.playback.store import PlaybackSessionStore
from app.services.playback.tickets import StreamTicketSigner, TicketError


def test_stream_ticket_is_scoped_and_expires():
    signer = StreamTicketSigner(secret=b"unit-test-secret", ttl_seconds=120)
    ticket = signer.issue(session_id="session-a", user_id=7, now=1000)

    payload = signer.verify(ticket, session_id="session-a", user_id=7, now=1100)
    assert payload["sid"] == "session-a"
    assert payload["uid"] == 7

    with pytest.raises(TicketError):
        signer.verify(ticket, session_id="session-b", now=1100)
    with pytest.raises(TicketError):
        signer.verify(ticket, user_id=8, now=1100)
    with pytest.raises(TicketError):
        signer.verify(ticket, now=1121)


def test_stream_ticket_detects_tampering():
    signer = StreamTicketSigner(secret=b"unit-test-secret", ttl_seconds=120)
    ticket = signer.issue(session_id="session-a", user_id=7, now=1000)
    body, signature = ticket.split(".", 1)
    tampered = ("A" if body[0] != "A" else "B") + body[1:] + "." + signature
    with pytest.raises(TicketError):
        signer.verify(tampered, now=1001)


def test_playback_session_store_persists_between_instances(tmp_path):
    db_path = str(tmp_path / "nomad-test.db")
    first = PlaybackSessionStore(db_path=db_path)
    created = first.create(
        user_id=42,
        path="/data/movies/Test.mp4",
        mode="direct_play",
        position=12.5,
        device_id="iphone",
        metadata={"source": {"container": "mp4"}},
    )
    first.update(created.id, user_id=42, state="playing", position=33.0)

    second = PlaybackSessionStore(db_path=db_path)
    restored = second.get(created.id, user_id=42)
    assert restored is not None
    assert restored.state == "playing"
    assert restored.position == 33.0
    assert restored.device_id == "iphone"
    assert restored.metadata["source"]["container"] == "mp4"
    assert second.get(created.id, user_id=99) is None


def test_playback_session_stop_and_list(tmp_path):
    store = PlaybackSessionStore(db_path=str(tmp_path / "sessions.db"))
    one = store.create(user_id=1, path="/data/movies/A.mp4", mode="direct_play")
    store.create(user_id=2, path="/data/movies/B.mp4", mode="direct_play")
    assert [s.id for s in store.list_for_user(1)] == [one.id]
    assert store.delete(one.id, user_id=2) is False
    assert store.delete(one.id, user_id=1) is True
    assert store.get(one.id) is None


@pytest.mark.parametrize(
    "header,size,expected",
    [
        (None, 1000, None),
        ("bytes=0-99", 1000, (0, 99)),
        ("bytes=100-", 1000, (100, 999)),
        ("bytes=-100", 1000, (900, 999)),
        ("bytes=900-2000", 1000, (900, 999)),
    ],
)
def test_byte_range_parser(header, size, expected):
    assert parse_byte_range(header, size) == expected


def test_byte_range_parser_rejects_invalid_ranges():
    for header in ("bytes=", "bytes=20-10", "bytes=1000-", "items=0-10", "bytes=0-1,3-4"):
        with pytest.raises(ValueError):
            parse_byte_range(header, 1000)


def test_hls_playlist_rewrites_init_and_segments_with_ticket():
    source = """#EXTM3U
#EXT-X-VERSION:7
#EXT-X-MAP:URI=\"init.mp4\"
#EXTINF:4.000,
segment_00000.m4s
#EXT-X-ENDLIST
"""
    output = _ticketed_playlist(source, "abc.def")
    assert 'URI="init.mp4?ticket=abc.def"' in output
    assert "segment_00000.m4s?ticket=abc.def" in output


def test_fit_dimensions_preserves_aspect_and_even_dimensions():
    assert fit_dimensions(3840, 2160, 1920, 1080) == (1920, 1080)
    assert fit_dimensions(1920, 1080, 1920, 1080) is None
    assert fit_dimensions(1920, 1080, None, 720) == (1280, 720)


def _arg_after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def _mapped_streams(cmd):
    return [cmd[i + 1] for i, value in enumerate(cmd[:-1]) if value == "-map"]


def test_hls_remux_copies_streams(tmp_path):
    cmd = build_hls_command(
        source_path="movie.mkv",
        output_dir=Path(tmp_path),
        mode="remux",
        target_video_codec=None,
        target_audio_codec=None,
    )
    assert _arg_after(cmd, "-c:v") == "copy"
    assert _arg_after(cmd, "-c:a") == "copy"
    assert _arg_after(cmd, "-hls_segment_type") == "fmp4"
    assert _mapped_streams(cmd) == ["0:v:0?", "0:a:0?"]


def test_hls_maps_explicit_audio_stream_index(tmp_path):
    cmd = build_hls_command(
        source_path="movie.mkv",
        output_dir=Path(tmp_path),
        mode="transcode_audio",
        target_video_codec=None,
        target_audio_codec="aac",
        audio_stream_index=4,
    )
    assert _mapped_streams(cmd) == ["0:v:0?", "0:4?"]
    assert _arg_after(cmd, "-c:v") == "copy"
    assert _arg_after(cmd, "-c:a") == "aac"


def test_hls_audio_transcode_keeps_video(tmp_path):
    cmd = build_hls_command(
        source_path="movie.mkv",
        output_dir=Path(tmp_path),
        mode="transcode_audio",
        target_video_codec=None,
        target_audio_codec="aac",
    )
    assert _arg_after(cmd, "-c:v") == "copy"
    assert _arg_after(cmd, "-c:a") == "aac"


def test_hls_video_transcode_scales_to_client_limit(tmp_path):
    cmd = build_hls_command(
        source_path="movie.mkv",
        output_dir=Path(tmp_path),
        mode="transcode_video",
        target_video_codec="h264",
        target_audio_codec="aac",
        source_width=3840,
        source_height=2160,
        max_width=1920,
        max_height=1080,
        max_bitrate=8_000_000,
    )
    assert _arg_after(cmd, "-c:v") == "libx264"
    assert _arg_after(cmd, "-vf") == "scale=1920:1080"
    assert _arg_after(cmd, "-maxrate") == "8000000"
    assert _arg_after(cmd, "-c:a") == "aac"
