from app.services.playback import (
    ClientCapabilities,
    MediaProbe,
    PlaybackMode,
    PlaybackPlanner,
)


planner = PlaybackPlanner()


def browser_caps(**overrides):
    values = {
        "containers": ["mp4", "webm"],
        "video_codecs": ["h264", "vp9"],
        "audio_codecs": ["aac", "opus"],
        "subtitle_formats": ["vtt"],
        "max_width": 1920,
        "max_height": 1080,
        "max_bitrate": 15_000_000,
    }
    values.update(overrides)
    return ClientCapabilities.from_values(**values)


def test_direct_play_when_source_is_fully_supported():
    plan = planner.plan(
        MediaProbe(
            container="MP4",
            video_codec="H264",
            audio_codec="AAC",
            width=1920,
            height=1080,
            bitrate=8_000_000,
        ),
        browser_caps(),
    )

    assert plan.mode == PlaybackMode.DIRECT_PLAY
    assert plan.requires_ffmpeg is False
    assert plan.reasons == ()


def test_remux_when_only_container_is_incompatible():
    plan = planner.plan(
        MediaProbe(
            container="mkv",
            video_codec="h264",
            audio_codec="aac",
            width=1920,
            height=1080,
            bitrate=8_000_000,
        ),
        browser_caps(),
    )

    assert plan.mode == PlaybackMode.REMUX
    assert plan.target_container == "mp4"
    assert plan.target_video_codec is None
    assert plan.target_audio_codec is None
    assert plan.requires_ffmpeg is True


def test_transcode_audio_but_copy_video_when_audio_codec_is_incompatible():
    plan = planner.plan(
        MediaProbe(
            container="mkv",
            video_codec="h264",
            audio_codec="dts",
            width=1920,
            height=1080,
            bitrate=9_000_000,
        ),
        browser_caps(),
    )

    assert plan.mode == PlaybackMode.TRANSCODE_AUDIO
    assert plan.target_container == "mp4"
    assert plan.target_video_codec is None
    assert plan.target_audio_codec == "aac"


def test_transcode_video_for_unsupported_video_codec():
    plan = planner.plan(
        MediaProbe(
            container="mkv",
            video_codec="hevc",
            audio_codec="aac",
            width=1920,
            height=1080,
            bitrate=8_000_000,
        ),
        browser_caps(),
    )

    assert plan.mode == PlaybackMode.TRANSCODE_VIDEO
    assert plan.target_container == "mp4"
    assert plan.target_video_codec == "h264"
    # AAC can be copied unchanged, so no audio target is necessary.
    assert plan.target_audio_codec is None


def test_transcode_video_when_resolution_exceeds_client_limit():
    plan = planner.plan(
        MediaProbe(
            container="mp4",
            video_codec="h264",
            audio_codec="aac",
            width=3840,
            height=2160,
            bitrate=25_000_000,
        ),
        browser_caps(),
    )

    assert plan.mode == PlaybackMode.TRANSCODE_VIDEO
    assert plan.target_video_codec == "h264"
    assert any("width" in reason for reason in plan.reasons)
    assert any("height" in reason for reason in plan.reasons)
    assert any("bitrate" in reason for reason in plan.reasons)


def test_audio_only_media_can_direct_play():
    caps = ClientCapabilities.from_values(
        containers=["m4a", "mp4"],
        audio_codecs=["aac"],
    )
    plan = planner.plan(
        MediaProbe(container="m4a", audio_codec="aac", bitrate=320_000),
        caps,
    )

    assert plan.mode == PlaybackMode.DIRECT_PLAY


def test_audio_only_media_transcodes_when_codec_is_unsupported():
    caps = ClientCapabilities.from_values(
        containers=["m4a", "mp4"],
        audio_codecs=["aac"],
    )
    plan = planner.plan(
        MediaProbe(container="flac", audio_codec="flac", bitrate=1_000_000),
        caps,
    )

    assert plan.mode == PlaybackMode.TRANSCODE_AUDIO
    assert plan.target_audio_codec == "aac"
    assert plan.target_container == "mp4"


def test_reports_unsupported_when_client_has_no_video_target_codec():
    caps = ClientCapabilities.from_values(
        containers=["mp4"],
        video_codecs=[],
        audio_codecs=["aac"],
    )
    plan = planner.plan(
        MediaProbe(container="mkv", video_codec="hevc", audio_codec="aac"),
        caps,
    )

    assert plan.mode == PlaybackMode.UNSUPPORTED
    assert any("no usable video codec" in reason for reason in plan.reasons)


def test_capabilities_are_case_insensitive_and_trimmed():
    caps = ClientCapabilities.from_values(
        containers=[" MP4 "],
        video_codecs=[" H264 "],
        audio_codecs=[" AAC "],
    )
    plan = planner.plan(
        MediaProbe(container="mp4", video_codec="h264", audio_codec="aac"),
        caps,
    )

    assert plan.mode == PlaybackMode.DIRECT_PLAY
