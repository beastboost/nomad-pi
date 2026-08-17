from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers import playback_gallery_albums as albums


def test_album_name_validation():
    assert albums._clean_album("  Family   Trips  ") == "Family Trips"
    assert albums._clean_album("", allow_empty=True) == ""
    for value in ("../secret", "Family/Trips", ".hidden", ".."):
        with pytest.raises(HTTPException):
            albums._clean_album(value)


def test_album_detection_uses_only_albums_root(tmp_path):
    root = tmp_path / "Albums"
    album_file = root / "Holiday" / "photo.jpg"
    loose_file = tmp_path / "Library" / "2026" / "08" / "photo.jpg"
    album_file.parent.mkdir(parents=True)
    loose_file.parent.mkdir(parents=True)
    album_file.write_bytes(b"x")
    loose_file.write_bytes(b"x")

    assert albums._album_for_path(album_file, root) == "Holiday"
    assert albums._album_for_path(loose_file, root) == ""


def test_unique_destination_preserves_existing_file(tmp_path):
    root = tmp_path / "Album"
    root.mkdir()
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"new")
    (root / "photo.jpg").write_bytes(b"old")

    destination = albums._unique_destination(root, source)
    assert destination.name == "photo (2).jpg"
    assert (root / "photo.jpg").read_bytes() == b"old"


def test_unfiled_destination_is_year_month(tmp_path):
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"x")
    destination = albums._library_destination(tmp_path / "private", source)
    assert destination.parts[-3] == "Library"
    assert len(destination.parts[-2]) == 4
    assert len(destination.parts[-1]) == 2
