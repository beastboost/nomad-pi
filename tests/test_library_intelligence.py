from pathlib import Path

from app.services import library_intelligence as li


def test_movie_version_key_strips_release_noise_and_keeps_year(tmp_path):
    root = tmp_path / "movies"
    root.mkdir()
    a = root / "Blade.Runner.1982.2160p.UHD.BluRay.x265.TrueHD.Atmos.mkv"
    b = root / "Blade Runner (1982) 1080p remux h264.mkv"
    key_a, *_ = li._normalise_key(str(a), "movies", str(root))
    key_b, *_ = li._normalise_key(str(b), "movies", str(root))
    assert key_a == "blade runner|1982"
    assert key_b == "blade runner|1982"


def test_show_episode_identity_supports_sxxeyy_and_1x02(tmp_path):
    root = tmp_path / "shows"
    show = root / "Test Show" / "Season 1"
    show.mkdir(parents=True)
    first = show / "Test.Show.S01E03.1080p.mkv"
    second = show / "Test Show - 1x04.mkv"
    assert li._episode_identity(str(first), str(root)) == ("Test Show", 1, 3)
    assert li._episode_identity(str(second), str(root)) == ("Test Show", 1, 4)


def test_quality_issues_flag_sd_legacy_and_missing_audio():
    issues = li._issues({
        "video_codec": "mpeg2video",
        "audio_codec": "",
        "width": 720,
        "height": 576,
        "duration": 500,
    }, "movies")
    assert "low_resolution" in issues
    assert "legacy_video_codec" in issues
    assert "no_audio_stream" in issues


def test_quick_hash_matches_same_content_and_changes_with_content(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    c = tmp_path / "c.bin"
    payload = b"A" * (2 * 1024 * 1024 + 17)
    a.write_bytes(payload)
    b.write_bytes(payload)
    c.write_bytes(b"B" + payload[1:])
    assert li._quick_hash(str(a)) == li._quick_hash(str(b))
    assert li._quick_hash(str(a)) != li._quick_hash(str(c))


def test_missing_episode_detection_uses_cached_index(monkeypatch, tmp_path):
    db = tmp_path / "quality.db"
    monkeypatch.setattr(li.database, "DB_PATH", str(db))
    monkeypatch.setattr(li, "_schema_ready", False)
    li.ensure_schema()
    conn = li._connect()
    try:
        for episode in (1, 2, 4, 5):
            path = f"/data/shows/Test/Season 1/Test.S01E{episode:02d}.mkv"
            conn.execute(
                """
                INSERT INTO library_quality_files (
                    path,fs_path,category,name,media_key,show_name,season,episode,
                    file_size,mtime_ns,duration,container,video_codec,audio_codec,
                    width,height,bitrate,probe_ok,issues_json,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    path,path,"shows",Path(path).name,f"test|s01e{episode:03d}","Test",1,episode,
                    100,1,1200,"matroska","h264","aac",1920,1080,4_000_000,1,"[]",li._now(),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    groups = li.missing_episodes()
    assert len(groups) == 1
    assert groups[0]["show"] == "Test"
    assert groups[0]["season"] == 1
    assert groups[0]["missing"] == [3]


def test_duplicate_summary_groups_matching_fingerprints(monkeypatch, tmp_path):
    db = tmp_path / "quality.db"
    monkeypatch.setattr(li.database, "DB_PATH", str(db))
    monkeypatch.setattr(li, "_schema_ready", False)
    li.ensure_schema()
    conn = li._connect()
    try:
        for idx in (1, 2):
            path = f"/data/movies/Test {idx}.mkv"
            conn.execute(
                """
                INSERT INTO library_quality_files (
                    path,fs_path,category,name,media_key,file_size,mtime_ns,quick_hash,
                    duration,container,video_codec,audio_codec,width,height,bitrate,
                    probe_ok,issues_json,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    path,path,"movies",Path(path).name,"test|2020",12345,1,"samehash",
                    6000,"matroska","h264","aac",1920,1080,8_000_000,1,"[]",li._now(),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    data = li.duplicates()
    assert len(data["exact"]) == 1
    assert len(data["exact"][0]["files"]) == 2
