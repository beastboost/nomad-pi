"""Regression tests for multi-device authentication behavior.

Nomad Pi is a media server, so the same account must be able to stay logged in
on a TV, phone, tablet, and desktop at the same time. Normal login/logout must
therefore operate on one session token at a time, while password changes/resets
remain account-wide security boundaries.
"""

from fastapi import Request

from app.routers import auth


def _request(*, token: str | None = None) -> Request:
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode("utf-8")))
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    })


def test_login_does_not_revoke_other_device_sessions(monkeypatch):
    user = {
        "id": 42,
        "username": "viewer",
        "password_hash": "hash",
        "is_admin": 0,
        "must_change_password": 0,
    }
    created = []

    monkeypatch.setattr(auth.database, "get_user_by_username", lambda username: user)
    monkeypatch.setattr(auth.pwd_context, "verify", lambda password, password_hash: True)
    monkeypatch.setattr(auth.database, "create_session", lambda token, user_id: created.append((token, user_id)))

    def should_not_be_called(*args, **kwargs):
        raise AssertionError("normal login must not revoke existing device sessions")

    monkeypatch.setattr(auth.database, "delete_user_sessions", should_not_be_called)

    response = auth.login(auth.LoginRequest(username="viewer", password="password123"), _request())

    assert response.status_code == 200
    assert len(created) == 1
    assert created[0][1] == 42


def test_logout_revokes_only_current_session(monkeypatch):
    deleted = []
    monkeypatch.setattr(auth.database, "delete_session", lambda token: deleted.append(token))

    def should_not_be_called(*args, **kwargs):
        raise AssertionError("logout must not revoke every session for the account")

    monkeypatch.setattr(auth.database, "delete_user_sessions", should_not_be_called)

    response = auth.logout(_request(token="phone-session"))

    assert response.status_code == 200
    assert deleted == ["phone-session"]


def test_password_change_revokes_other_sessions_but_keeps_current(monkeypatch):
    events = []
    user = {
        "id": 7,
        "username": "viewer",
        "password_hash": "old-hash",
        "is_admin": 0,
        "must_change_password": 0,
    }

    monkeypatch.setattr(auth.database, "get_user_by_id", lambda user_id: user)
    monkeypatch.setattr(auth.pwd_context, "verify", lambda password, password_hash: True)
    monkeypatch.setattr(auth.pwd_context, "hash", lambda password: "new-hash")
    monkeypatch.setattr(auth.database, "update_user_password", lambda user_id, new_hash: events.append(("password", user_id, new_hash)))
    monkeypatch.setattr(auth.database, "delete_user_sessions", lambda user_id: events.append(("revoke-all", user_id)))
    monkeypatch.setattr(auth.database, "create_session", lambda token, user_id: events.append(("restore-current", token, user_id)))

    response = auth.change_password(
        auth.PasswordChangeRequest(current_password="password123", new_password="newpassword123"),
        _request(token="current-device"),
        user_id=7,
    )

    assert response["status"] == "ok"
    assert ("revoke-all", 7) in events
    assert ("restore-current", "current-device", 7) in events


def test_admin_password_reset_revokes_target_sessions(monkeypatch):
    events = []
    monkeypatch.setattr(auth.pwd_context, "hash", lambda password: "reset-hash")
    monkeypatch.setattr(auth.database, "update_user_password", lambda user_id, new_hash: events.append(("password", user_id, new_hash)))
    monkeypatch.setattr(auth.database, "delete_user_sessions", lambda user_id: events.append(("revoke-all", user_id)))

    response = auth.reset_user_password(
        99,
        auth.UserPasswordResetRequest(new_password="replacement123"),
        admin={"id": 1, "is_admin": 1},
    )

    assert response["status"] == "ok"
    assert ("password", 99, "reset-hash") in events
    assert ("revoke-all", 99) in events
