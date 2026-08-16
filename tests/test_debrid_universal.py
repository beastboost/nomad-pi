from app.routers import debrid_universal


def release(name, *, quality, codec, size, info_hash, seeders=5):
    return {
        "name": name,
        "details": f"{size} {quality} {codec}",
        "quality": quality,
        "codec": codec,
        "size": size,
        "info_hash": info_hash,
        "seeders": seeders,
    }


def test_cached_h264_mp4_aac_is_ranked_first(monkeypatch):
    monkeypatch.setattr(
        debrid_universal,
        "_provider_cached",
        lambda hashes: ("rd", {"direct": True, "mkv": True}),
    )
    results = [
        release(
            "Film.2025.2160p.HEVC.10bit.HDR.mkv",
            quality="2160p",
            codec="HEVC",
            size="12 GB",
            info_hash="heavy",
            seeders=100,
        ),
        release(
            "Film.2025.1080p.H264.AAC.mkv",
            quality="1080p",
            codec="H264",
            size="3.2 GB",
            info_hash="mkv",
            seeders=20,
        ),
        release(
            "Film.2025.1080p.H264.AAC.mp4",
            quality="1080p",
            codec="H264",
            size="3.8 GB",
            info_hash="direct",
            seeders=10,
        ),
    ]

    payload = debrid_universal._release_payload(
        results,
        "movie",
        include_heavy=False,
        limit=10,
    )

    assert payload["provider"] == "rd"
    assert payload["safe_count"] == 2
    assert payload["cached_count"] == 2
    assert payload["heavy_count"] == 1
    assert [item["info_hash"] for item in payload["releases"]] == ["direct", "mkv"]
    assert payload["releases"][0]["lite_direct_candidate"] is True
    assert all(item["lite_compatible"] for item in payload["releases"])


def test_heavy_releases_only_return_when_explicitly_requested(monkeypatch):
    monkeypatch.setattr(
        debrid_universal,
        "_provider_cached",
        lambda hashes: ("rd", {}),
    )
    results = [
        release(
            "Film.2025.1080p.H264.AAC.mp4",
            quality="1080p",
            codec="H264",
            size="2.8 GB",
            info_hash="safe",
        ),
        release(
            "Film.2025.2160p.AV1.HDR.mkv",
            quality="2160p",
            codec="AV1",
            size="10 GB",
            info_hash="heavy",
        ),
    ]

    default = debrid_universal._release_payload(
        results,
        "movie",
        include_heavy=False,
        limit=10,
    )
    expanded = debrid_universal._release_payload(
        results,
        "movie",
        include_heavy=True,
        limit=10,
    )

    assert [item["info_hash"] for item in default["releases"]] == ["safe"]
    assert [item["info_hash"] for item in expanded["releases"]] == ["safe", "heavy"]
    assert expanded["releases"][-1]["lite_compatible"] is False
