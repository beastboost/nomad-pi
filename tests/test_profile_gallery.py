from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers import playback_gallery as gallery
from app.services.household_profiles import HouseholdProfile


def _profile(profile_id: int, *, default: bool = False) -> HouseholdProfile:
    return HouseholdProfile(
        id=profile_id,
        user_id=1,
        name=f"Profile {profile_id}",
        avatar=None,
        preferences={},
        parental_controls={},
        pin_required=False,
        is_default=default,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def _write(path: Path, data: bytes = b"photo") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_gallery_is_scoped_to_active_profile(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    private = tmp_path / "private"
    monkeypatch.setattr(gallery, "_GALLERY_ROOT", legacy.resolve())
    monkeypatch.setattr(gallery, "_PRIVATE_ROOT", private.resolve())
    gallery._CACHE.clear()

    _write(legacy / "old-family-photo.jpg")
    _write(private / "u1" / "p1" / "owner-only.jpg")
    _write(private / "u1" / "p2" / "second-only.jpg")

    owner = gallery._scan(1, _profile(1, default=True), limit=100)
    second = gallery._scan(1, _profile(2), limit=100)

    assert {item["name"] for item in owner} == {"old-family-photo.jpg", "owner-only.jpg"}
    assert {item["name"] for item in second} == {"second-only.jpg"}
    assert all(item["name"] != "old-family-photo.jpg" for item in second)


def test_item_id_from_another_profile_cannot_be_resolved(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    private = tmp_path / "private"
    monkeypatch.setattr(gallery, "_GALLERY_ROOT", legacy.resolve())
    monkeypatch.setattr(gallery, "_PRIVATE_ROOT", private.resolve())
    gallery._CACHE.clear()

    _write(private / "u1" / "p1" / "secret.jpg")
    owner = _profile(1, default=True)
    second = _profile(2)
    item = gallery._scan(1, owner, limit=100)[0]

    with pytest.raises(HTTPException) as exc:
        gallery._resolve_item(1, second, item["id"])
    assert exc.value.status_code == 404


def test_private_gallery_root_is_outside_public_data_mount():
    root = gallery._PRIVATE_ROOT
    data = Path("data").resolve()
    with pytest.raises(ValueError):
        root.resolve().relative_to(data)


def test_gallery_range_parser():
    assert gallery._parse_range("bytes=0-99", 1000) == (0, 99)
    assert gallery._parse_range("bytes=900-", 1000) == (900, 999)
    assert gallery._parse_range("bytes=-100", 1000) == (900, 999)
    with pytest.raises(ValueError):
        gallery._parse_range("bytes=1000-", 1000)
