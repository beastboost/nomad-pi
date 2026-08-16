from app.services import debrid_lite


def test_h264_1080p_mp4_aac_is_direct_candidate(monkeypatch):
    monkeypatch.delenv("NOMAD_DEBRID_MAX_MOVIE_GB", raising=False)
    item = {
        "name": "Movie.2024.1080p.WEB-DL.H264.AAC.mp4",
        "details": "2.80 GB",
        "quality": "1080p",
        "codec": "H264",
        "size": "2.80 GB",
        "seeders": 42,
    }
    result = debrid_lite._analyse_release(item, "movie")
    assert result["lite_compatible"] is True
    assert result["lite_direct_candidate"] is True
    assert result["container_hint"] == "mp4"
    assert result["audio_hint"] == "aac"


def test_hevc_4k_remux_is_not_lite_compatible():
    item = {
        "name": "Movie.2160p.UHD.BluRay.REMUX.HEVC.HDR.TrueHD.mkv",
        "details": "55.0 GB",
        "quality": "2160p",
        "codec": "HEVC",
        "size": "55.0 GB",
    }
    result = debrid_lite._analyse_release(item, "movie")
    assert result["lite_compatible"] is False
    joined = " ".join(result["lite_reasons"])
    assert "HEVC" in joined
    assert "REMUX" in joined


def test_episode_size_cap_is_smaller_than_movie_cap(monkeypatch):
    monkeypatch.delenv("NOMAD_DEBRID_MAX_EPISODE_GB", raising=False)
    item = {
        "name": "Show.S01E01.1080p.H264.AAC.mp4",
        "details": "4.0 GB",
        "quality": "1080p",
        "codec": "H264",
        "size": "4.0 GB",
    }
    result = debrid_lite._analyse_release(item, "series")
    assert result["lite_compatible"] is False
    assert result["lite_max_size_gb"] == 3.0


def test_lite_search_ranks_compatible_release_first(monkeypatch):
    monkeypatch.setattr(
        debrid_lite,
        "_ORIGINAL_SEARCH",
        lambda *args, **kwargs: [
            {
                "name": "Movie.2160p.REMUX.HEVC.mkv",
                "details": "50 GB",
                "quality": "2160p",
                "codec": "HEVC",
                "size": "50 GB",
                "seeders": 500,
            },
            {
                "name": "Movie.1080p.H264.AAC.mp4",
                "details": "3.2 GB",
                "quality": "1080p",
                "codec": "H264",
                "size": "3.2 GB",
                "seeders": 20,
            },
        ],
    )
    results = debrid_lite._lite_search("", imdb_id="tt123", media_type="movie")
    assert results[0]["lite_compatible"] is True
    assert results[0]["lite_direct_candidate"] is True
    assert results[1]["lite_compatible"] is False
