from pathlib import Path

from app.routers import debrid_manifest


def test_episode_numbers_support_common_pack_names():
    assert debrid_manifest._episode_numbers("Show.Name.S01E03.1080p.mp4") == (1, 3, None)
    assert debrid_manifest._episode_numbers("Show Name 2x07 HDTV.mkv") == (2, 7, None)
    assert debrid_manifest._episode_numbers("Show.S01E01E02.mkv") == (1, 1, 2)
    assert debrid_manifest._episode_numbers("Show.Name.S06.E01.1080p.mp4") == (6, 1, None)
    assert debrid_manifest._episode_numbers("Show.Name.Season.06.Episode.01.1080p.mp4") == (6, 1, None)
    assert debrid_manifest._episode_numbers("Show Name/Season 6/Episode 12.mkv") == (6, 12, None)


def test_normal_file_annotates_episode_and_size():
    item = debrid_manifest._normal_file(
        {"id": 9, "path": "Series/Season 04/Series.S04E12.1080p.mp4", "bytes": 123456},
        0,
    )
    assert item["id"] == 9
    assert item["video"] is True
    assert item["season"] == 4
    assert item["episode"] == 12
    assert item["bytes"] == 123456


def test_normal_file_understands_long_form_season_episode_names():
    item = debrid_manifest._normal_file(
        {
            "id": 3,
            "path": "Rick.and.Morty.Season.06.Episode.01.Solaricks.1080p.mp4",
            "bytes": 456789,
        },
        0,
    )
    assert item["season"] == 6
    assert item["episode"] == 1


def test_show_destination_uses_series_and_season_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(debrid_manifest.media, "pick_effective_storage_root_fs", lambda category: str(tmp_path))
    monkeypatch.setattr(debrid_manifest.media, "pick_unique_dest", lambda path: path)

    body = debrid_manifest.LibraryDownloadRequest(
        url="https://example.com/file.mp4",
        filename="release-name.mp4",
        source_path="Some.Release.S01E03.1080p.mp4",
        title="Some Show",
        year="2024",
        media_type="series",
        season=1,
        episode=3,
    )
    dest, filename, season, episode = debrid_manifest._show_destination(body)

    assert season == 1
    assert episode == 3
    assert filename == "Some Show - S01E03.mp4"
    assert Path(dest) == tmp_path / "Some Show (2024)" / "Season 01" / "Some Show - S01E03.mp4"


def test_show_destination_can_infer_episode_from_source_path(tmp_path, monkeypatch):
    monkeypatch.setattr(debrid_manifest.media, "pick_effective_storage_root_fs", lambda category: str(tmp_path))
    monkeypatch.setattr(debrid_manifest.media, "pick_unique_dest", lambda path: path)

    body = debrid_manifest.LibraryDownloadRequest(
        url="https://example.com/file.mkv",
        filename="raw-file.mkv",
        source_path="Series.Name.S03E08.1080p.mkv",
        title="Series Name",
        media_type="series",
    )
    dest, filename, season, episode = debrid_manifest._show_destination(body)

    assert (season, episode) == (3, 8)
    assert filename == "Series Name - S03E08.mkv"
    assert Path(dest).parent.name == "Season 03"


def test_provider_episode_identity_overrides_wrong_search_context(tmp_path, monkeypatch):
    monkeypatch.setattr(debrid_manifest.media, "pick_effective_storage_root_fs", lambda category: str(tmp_path))
    monkeypatch.setattr(debrid_manifest.media, "pick_unique_dest", lambda path: path)

    body = debrid_manifest.LibraryDownloadRequest(
        url="https://example.com/file.mp4",
        filename="Rick.and.Morty.Season.06.Episode.01.Solaricks.1080p.mp4",
        source_path="Rick.and.Morty.Season.06.Episode.01.Solaricks.1080p.mp4",
        title="Rick and Morty",
        media_type="series",
        season=1,
        episode=1,
    )
    dest, filename, season, episode = debrid_manifest._show_destination(body)

    assert (season, episode) == (6, 1)
    assert filename == "Rick and Morty - S06E01.mp4"
    assert Path(dest) == tmp_path / "Rick and Morty" / "Season 06" / "Rick and Morty - S06E01.mp4"
