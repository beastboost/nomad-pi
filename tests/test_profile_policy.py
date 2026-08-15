import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import profile_policy as pp


class FakeQuery(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeRequest:
    def __init__(self, path, method="GET", query=None):
        self.url = SimpleNamespace(path=path)
        self.method = method
        self.query_params = FakeQuery(query or {})


def test_policy_normalises_aliases_and_defaults():
    policy = pp.normalise_policy({
        "enabled": True,
        "libraries": ["Movies", "Shows"],
        "blocked_keywords": ["horror"],
        "max_rating_age": "12",
        "allow_debrid": False,
        "allow_offline": False,
    })
    assert policy["enabled"] is True
    assert policy["allowed_libraries"] == ["movies", "shows"]
    assert policy["blocked_terms"] == ["horror"]
    assert policy["max_age"] == 12
    assert policy["allow_debrid"] is False
    assert policy["allow_offline_sync"] is False
    assert policy["allow_library_health"] is False


def test_common_uk_and_us_ratings_map_to_ages():
    assert pp.rating_to_age("U") == 0
    assert pp.rating_to_age("PG") == 8
    assert pp.rating_to_age("Rated PG-13") == 13
    assert pp.rating_to_age("15 (UK)") == 15
    assert pp.rating_to_age("TV-MA") == 17
    assert pp.rating_to_age("18") == 18
    assert pp.rating_to_age("Unrated") is None


def test_profile_policy_is_loaded_only_for_profiles_owned_by_user(monkeypatch, tmp_path):
    db = tmp_path / "profiles.db"
    monkeypatch.setattr(pp.database, "DB_PATH", str(db))
    conn = pp._connect()
    try:
        conn.execute("CREATE TABLE profiles (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, parental_controls TEXT)")
        conn.execute(
            "INSERT INTO profiles (id,user_id,name,parental_controls) VALUES (1,7,'Kids',?)",
            (json.dumps({"enabled": True, "allowed_libraries": ["movies"], "max_age": 12}),),
        )
        conn.commit()
    finally:
        conn.close()
    policy = pp.get_profile_policy(7, 1)
    assert policy["profile_name"] == "Kids"
    assert policy["allowed_libraries"] == ["movies"]
    assert policy["max_age"] == 12
    assert pp.get_profile_policy(8, 1) is None


def test_allowed_library_and_blocked_term_are_enforced():
    policy = pp.normalise_policy({
        "enabled": True,
        "allowed_libraries": ["movies"],
        "blocked_terms": ["blocked title"],
    })
    pp.assert_policy(policy, request=FakeRequest("/api/media/library", query={"category": "movies"}), payload={})
    with pytest.raises(HTTPException) as exc:
        pp.assert_policy(policy, request=FakeRequest("/api/media/library", query={"category": "shows"}), payload={})
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        pp.assert_policy(
            policy,
            request=FakeRequest("/api/playback/start", method="POST"),
            payload={"path": "/data/movies/Blocked Title (2020).mkv"},
        )


def test_debrid_offline_delete_and_library_health_permissions():
    policy = pp.normalise_policy({
        "enabled": True,
        "allow_debrid": False,
        "allow_offline_sync": False,
        "allow_delete": False,
        "allow_library_health": False,
    })
    with pytest.raises(HTTPException):
        pp.assert_policy(policy, request=FakeRequest("/api/debrid/search"), payload={})
    with pytest.raises(HTTPException):
        pp.assert_policy(policy, request=FakeRequest("/api/playback/offline", method="POST"), payload={"path": "/data/movies/A.mkv"})
    with pytest.raises(HTTPException):
        pp.assert_policy(policy, request=FakeRequest("/api/media/delete", method="DELETE", query={"path": "/data/movies/A.mkv"}), payload={})
    with pytest.raises(HTTPException):
        pp.assert_policy(policy, request=FakeRequest("/api/playback/intelligence/summary"), payload={})


def test_unrated_blocking_and_age_limits(monkeypatch):
    policy = pp.normalise_policy({"enabled": True, "max_age": 12, "block_unrated": True})
    monkeypatch.setattr(pp, "_metadata_rating", lambda path: None)
    with pytest.raises(HTTPException):
        pp.assert_policy(policy, request=FakeRequest("/api/playback/start", method="POST"), payload={"path": "/data/movies/A.mkv"})

    policy = pp.normalise_policy({"enabled": True, "max_age": 12, "block_unrated": False})
    monkeypatch.setattr(pp, "_metadata_rating", lambda path: 15)
    with pytest.raises(HTTPException) as exc:
        pp.assert_policy(policy, request=FakeRequest("/api/playback/start", method="POST"), payload={"path": "/data/movies/B.mkv"})
    assert "age limit" in str(exc.value.detail)
