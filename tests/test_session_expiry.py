"""Session lifetime must be decided when the session is issued, not when it is read.

Expiry used to be recomputed from created_at against the *current*
SESSION_MAX_AGE_DAYS on every lookup, so raising the setting resurrected
sessions that had already lapsed. A role change also left existing sessions
running under their old privileges.
"""

import sqlite3
import uuid

import pytest

from app import database


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    # A fresh pool, so this test never borrows a connection to the real file.
    from queue import Queue

    monkeypatch.setattr(database, "_connection_pool", Queue(maxsize=5))
    database.init_db()
    yield


def _expiry(token):
    conn = database.get_db()
    try:
        row = conn.execute("SELECT expires_at FROM sessions WHERE token = ?", (token,)).fetchone()
        return row["expires_at"] if row else None
    finally:
        database.return_db(conn)


def test_new_session_stamps_its_own_expiry(db):
    token = uuid.uuid4().hex
    database.create_session(token, 1)
    assert _expiry(token) is not None
    assert database.get_session(token)["user_id"] == 1


def test_expired_session_is_not_returned(db):
    token = uuid.uuid4().hex
    database.create_session(token, 1, max_age_days=1)
    conn = database.get_db()
    try:
        conn.execute(
            "UPDATE sessions SET expires_at = datetime('now', '-1 day') WHERE token = ?", (token,))
        conn.commit()
    finally:
        database.return_db(conn)
    assert database.get_session(token) is None


def test_raising_the_setting_does_not_resurrect_a_lapsed_session(db, monkeypatch):
    token = uuid.uuid4().hex
    database.create_session(token, 1, max_age_days=1)
    conn = database.get_db()
    try:
        conn.execute(
            "UPDATE sessions SET expires_at = datetime('now', '-1 hour') WHERE token = ?", (token,))
        conn.commit()
    finally:
        database.return_db(conn)

    monkeypatch.setattr(database, "SESSION_MAX_AGE_DAYS", 365)
    assert database.get_session(token) is None


def test_shortening_the_setting_does_not_extend_an_issued_session(db, monkeypatch):
    token = uuid.uuid4().hex
    database.create_session(token, 1, max_age_days=30)
    monkeypatch.setattr(database, "SESSION_MAX_AGE_DAYS", 1)
    # Still valid: the deadline it was issued with has not passed.
    assert database.get_session(token) is not None


def test_legacy_rows_without_an_expiry_still_authenticate(db):
    token = uuid.uuid4().hex
    conn = database.get_db()
    try:
        conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, NULL)", (token, 9))
        conn.commit()
    finally:
        database.return_db(conn)
    assert database.get_session(token)["user_id"] == 9


def test_legacy_rows_still_age_out(db):
    token = uuid.uuid4().hex
    conn = database.get_db()
    try:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) "
            "VALUES (?, ?, datetime('now', '-400 days'), NULL)", (token, 9))
        conn.commit()
    finally:
        database.return_db(conn)
    assert database.get_session(token) is None


def test_cleanup_removes_expired_sessions_and_keeps_live_ones(db):
    live, dead = uuid.uuid4().hex, uuid.uuid4().hex
    database.create_session(live, 1)
    database.create_session(dead, 1)
    conn = database.get_db()
    try:
        conn.execute(
            "UPDATE sessions SET expires_at = datetime('now', '-1 day') WHERE token = ?", (dead,))
        conn.commit()
    finally:
        database.return_db(conn)

    database.cleanup_sessions()
    assert database.get_session(dead) is None
    assert database.get_session(live) is not None


def test_max_age_is_clamped_to_a_sane_range(monkeypatch):
    for raw, expected in [("0", 1), ("-5", 1), ("9999", 365), ("7", 7), ("nonsense", 30)]:
        monkeypatch.setenv("SESSION_MAX_AGE_DAYS", raw)
        assert database._session_max_age_days() == expected


def test_role_change_revokes_existing_sessions(db):
    user_id = database.create_user("rolechange", "hash", is_admin=False)
    token = uuid.uuid4().hex
    database.create_session(token, user_id)
    assert database.get_session(token) is not None

    from app.routers import auth

    auth.update_user_role(
        user_id,
        auth.UserRoleRequest(is_admin=True),
        admin={"id": user_id + 1000},
    )
    assert database.get_session(token) is None
