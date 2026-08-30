"""The dashboard must not hand out household activity to unauthenticated callers.

/api/dashboard/ws, /public and /stats were open to anyone who could reach the
port, streaming every session's title, poster and progress. /control/ws let a
caller attach to any session id and receive its pause/resume/stop commands, and
pause/resume skipped the ownership check that command_session and stop_session
both perform.
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.routers import auth, dashboard
from app.services import display_tokens


@pytest.fixture(autouse=True)
def clean_sessions():
    dashboard.active_sessions.clear()
    yield
    dashboard.active_sessions.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _as_user(user_id: int):
    app.dependency_overrides[auth.get_current_user_id] = lambda: user_id


def _logout():
    app.dependency_overrides.pop(auth.get_current_user_id, None)
    app.dependency_overrides.pop(auth.get_current_admin, None)


# ── unauthenticated read access ───────────────────────────────────────────

def test_public_snapshot_requires_credentials(client):
    _logout()
    assert client.get("/api/dashboard/public").status_code == 401


def test_stats_requires_credentials(client):
    _logout()
    assert client.get("/api/dashboard/stats").status_code == 401


def test_dashboard_websocket_refuses_anonymous_clients(client):
    _logout()
    with pytest.raises(Exception):
        with client.websocket_connect("/api/dashboard/ws") as ws:
            ws.receive_json()


# ── display tokens ────────────────────────────────────────────────────────

def test_display_token_opens_read_only_endpoints(client):
    _logout()
    token = display_tokens.issue(label="hallway")
    assert client.get(f"/api/dashboard/public?display_token={token}").status_code == 200
    assert client.get(f"/api/dashboard/stats?display_token={token}").status_code == 200


def test_display_token_streams_the_dashboard_websocket(client):
    _logout()
    token = display_tokens.issue(label="hallway")
    with client.websocket_connect(f"/api/dashboard/ws?display_token={token}") as ws:
        message = ws.receive_json()
    assert "sessions" in message and "system" in message


def test_revoking_invalidates_previously_issued_tokens(client):
    _logout()
    token = display_tokens.issue(label="hallway")
    assert client.get(f"/api/dashboard/public?display_token={token}").status_code == 200
    display_tokens.revoke_all()
    assert client.get(f"/api/dashboard/public?display_token={token}").status_code == 401
    fresh = display_tokens.issue(label="hallway")
    assert client.get(f"/api/dashboard/public?display_token={fresh}").status_code == 200


def test_tampered_display_token_is_rejected(client):
    _logout()
    token = display_tokens.issue()
    assert client.get(f"/api/dashboard/public?display_token={token[:-4]}AAAA").status_code == 401


def test_stream_ticket_cannot_be_replayed_as_a_display_token():
    from app.services.playback.tickets import StreamTicketSigner

    ticket = StreamTicketSigner().issue(session_id="s1", user_id=1)
    with pytest.raises(display_tokens.DisplayTokenError):
        display_tokens.verify(ticket)


def test_display_token_is_read_only_and_cannot_control_a_session(client):
    _logout()
    token = display_tokens.issue()
    dashboard.active_sessions["s1"] = {"user_id": 7, "state": "playing"}
    # No control path accepts a display token; they all require an account.
    assert client.post(f"/api/dashboard/session/s1/pause?display_token={token}").status_code == 401


def test_minting_a_token_requires_an_admin(client):
    _as_user(5)
    try:
        assert client.post("/api/dashboard/display/tokens").status_code in (401, 403)
    finally:
        _logout()


# ── session ownership ─────────────────────────────────────────────────────

def test_pause_refuses_someone_elses_session(client):
    dashboard.active_sessions["s1"] = {"user_id": 7, "state": "playing"}
    _as_user(8)
    try:
        assert client.post("/api/dashboard/session/s1/pause").status_code == 403
        assert dashboard.active_sessions["s1"]["state"] == "playing"
    finally:
        _logout()


def test_resume_refuses_someone_elses_session(client):
    dashboard.active_sessions["s1"] = {"user_id": 7, "state": "paused"}
    _as_user(8)
    try:
        assert client.post("/api/dashboard/session/s1/resume").status_code == 403
        assert dashboard.active_sessions["s1"]["state"] == "paused"
    finally:
        _logout()


def test_owner_can_pause_and_resume(client):
    dashboard.active_sessions["s1"] = {"user_id": 7, "state": "playing"}
    _as_user(7)
    try:
        assert client.post("/api/dashboard/session/s1/pause").status_code == 200
        assert dashboard.active_sessions["s1"]["state"] == "paused"
        assert client.post("/api/dashboard/session/s1/resume").status_code == 200
        assert dashboard.active_sessions["s1"]["state"] == "playing"
    finally:
        _logout()


def test_unknown_session_is_not_found_rather_than_forbidden(client):
    _as_user(7)
    try:
        assert client.post("/api/dashboard/session/nope/pause").json()["status"] == "not_found"
    finally:
        _logout()


def test_pause_resume_and_stop_agree_on_ownership():
    dashboard.active_sessions["s1"] = {"user_id": 7}
    with pytest.raises(HTTPException) as excinfo:
        dashboard._owned_session("s1", 8)
    assert excinfo.value.status_code == 403
    assert dashboard._owned_session("s1", 7) is not None
    assert dashboard._owned_session("missing", 7) is None


# ── control websocket ─────────────────────────────────────────────────────
# This socket receives the pause/resume/stop stream for one playback session,
# so it takes a real account (not a display token) and checks ownership. It
# reads the session table directly rather than through Depends, so these tests
# mint genuine tokens instead of overriding a dependency.

@pytest.fixture
def real_user_token():
    import uuid

    token = uuid.uuid4().hex
    user_id = 4242
    database.create_session(token, user_id)
    try:
        yield token, user_id
    finally:
        database.delete_session(token)


def test_control_socket_refuses_anonymous_clients(client):
    dashboard.active_sessions["s1"] = {"user_id": 7}
    with pytest.raises(Exception):
        with client.websocket_connect("/api/dashboard/control/ws?session_id=s1") as ws:
            ws.send_text("hi")
            ws.receive_text()


def test_control_socket_refuses_someone_elses_session(client, real_user_token):
    token, user_id = real_user_token
    dashboard.active_sessions["s1"] = {"user_id": user_id + 1}
    with pytest.raises(Exception):
        with client.websocket_connect(
            f"/api/dashboard/control/ws?session_id=s1&token={token}"
        ) as ws:
            ws.send_text("hi")
            ws.receive_text()
    assert "s1" not in dashboard.control_connections


def test_control_socket_accepts_the_session_owner(client, real_user_token):
    token, user_id = real_user_token
    dashboard.active_sessions["s1"] = {"user_id": user_id}
    with client.websocket_connect(
        f"/api/dashboard/control/ws?session_id=s1&token={token}"
    ) as ws:
        assert dashboard.control_connections.get("s1") is not None
        ws.close()
    dashboard.control_connections.pop("s1", None)


def test_display_token_cannot_open_the_control_socket(client):
    display = display_tokens.issue()
    dashboard.active_sessions["s1"] = {"user_id": 7}
    with pytest.raises(Exception):
        with client.websocket_connect(
            f"/api/dashboard/control/ws?session_id=s1&display_token={display}"
        ) as ws:
            ws.send_text("hi")
            ws.receive_text()
