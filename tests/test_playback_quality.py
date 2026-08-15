from app.routers.playback_quality import QUALITY_PROFILES, _capabilities, _media_probe
from app.services.playback.planner import PlaybackMode, PlaybackPlanner


def _metadata():
    return {
        "source": {
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": 3840,
            "height": 2160,
            "bitrate": 20_000_000,
        },
        "capabilities": {
            "containers": ["mp4", "webm"],
            "video_codecs": ["h264", "vp9"],
            "audio_codecs": ["aac", "opus"],
            "subtitle_formats": ["vtt"],
            "max_width": None,
            "max_height": None,
            "max_bitrate": None,
        },
    }


def test_original_quality_can_direct_play_compatible_4k_source():
    metadata = _metadata()
    caps = _capabilities(metadata, QUALITY_PROFILES["original"])
    plan = PlaybackPlanner().plan(_media_probe(metadata), caps)
    assert plan.mode == PlaybackMode.DIRECT_PLAY


def test_1080p_profile_forces_4k_video_transcode():
    metadata = _metadata()
    caps = _capabilities(metadata, QUALITY_PROFILES["1080p"])
    plan = PlaybackPlanner().plan(_media_probe(metadata), caps)
    assert caps.max_width == 1920
    assert caps.max_height == 1080
    assert caps.max_bitrate == 8_000_000
    assert plan.mode == PlaybackMode.TRANSCODE_VIDEO
    assert plan.target_video_codec == "h264"


def test_quality_profile_never_relaxes_existing_client_limit():
    metadata = _metadata()
    metadata["capabilities"]["max_height"] = 720
    metadata["capabilities"]["max_bitrate"] = 3_000_000
    caps = _capabilities(metadata, QUALITY_PROFILES["1080p"])
    assert caps.max_height == 720
    assert caps.max_bitrate == 3_000_000


def test_quality_profiles_include_portable_low_bandwidth_options():
    assert QUALITY_PROFILES["720p"]["max_bitrate"] == 4_000_000
    assert QUALITY_PROFILES["480p"]["max_bitrate"] == 2_000_000
