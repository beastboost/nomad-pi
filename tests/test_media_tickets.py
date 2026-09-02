"""Media URLs must not carry the session token.

The session token is a 30-day credential for the entire API. Putting it in
`?token=` on every <video src>, poster and download link leaked it into browser
history, proxy logs and Referer headers — a shared stream link was a shared
account. Media URLs now carry a short-lived signed ticket that only
byte-serving endpoints accept.
"""

import re
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app
from app.routers import auth
from app.services import media_tickets


@pytest.fixture
def session_token():
    token = uuid.uuid4().hex
    database.create_session(token, 3131)
    try:
        yield token
    finally:
        database.delete_session(token)


@pytest.fixture
def client():
    return TestClient(app)


# ── the ticket itself ─────────────────────────────────────────────────────

def test_ticket_round_trips_its_user():
    assert media_tickets.user_id_from(media_tickets.issue(7)) == 7


def test_tampered_ticket_is_rejected():
    ticket = media_tickets.issue(7)
    with pytest.raises(media_tickets.MediaTicketError):
        media_tickets.verify(ticket[:-4] + "AAAA")


def test_expired_ticket_is_rejected():
    with pytest.raises(media_tickets.MediaTicketError):
        media_tickets.verify(media_tickets.issue(7, ttl_seconds=60, now=1))


def test_ticket_is_short_lived_by_default():
    # Hours, not the session's thirty days.
    assert media_tickets.DEFAULT_TTL_SECONDS <= 24 * 3600


def test_other_signed_tokens_cannot_pose_as_a_media_ticket():
    from app.services import display_tokens
    from app.services.playback.tickets import StreamTicketSigner

    for foreign in (display_tokens.issue(), StreamTicketSigner().issue(session_id="s", user_id=1)):
        with pytest.raises(media_tickets.MediaTicketError):
            media_tickets.verify(foreign)


# ── the session token no longer opens anything from a URL ─────────────────

class _QueryRequest:
    def __init__(self, params, cookies=None, headers=None):
        self.query_params = params
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.url = type("U", (), {"path": "/api/media/stream"})()


def test_session_token_is_not_read_from_the_query_string(session_token):
    assert auth._extract_auth_token(_QueryRequest({"token": session_token})) is None


def test_session_token_is_still_read_from_cookie_and_header(session_token):
    assert auth._extract_auth_token(_QueryRequest({}, cookies={"auth_token": session_token}))
    assert auth._extract_auth_token(
        _QueryRequest({}, headers={"Authorization": f"Bearer {session_token}"}))


def test_no_source_file_still_accepts_a_query_session_token():
    for path in Path("app").rglob("*.py"):
        source = path.read_text()
        assert 'query_params.get("token")' not in source, f"{path} still reads ?token="


def test_frontend_media_urls_use_tickets_not_session_tokens():
    for path in Path("app/static/js").glob("*.js"):
        source = path.read_text()
        leaked = re.findall(r"[?&]token=\$\{", source)
        assert not leaked, f"{path} still puts the session token in a URL"


# ── endpoint behaviour ────────────────────────────────────────────────────

def test_media_ticket_endpoint_needs_a_login(client):
    assert client.get("/api/auth/media-ticket").status_code == 401


def test_media_ticket_endpoint_issues_a_usable_ticket(client):
    app.dependency_overrides[auth.get_current_user_id] = lambda: 3131
    try:
        body = client.get("/api/auth/media-ticket").json()
    finally:
        app.dependency_overrides.pop(auth.get_current_user_id, None)
    assert media_tickets.user_id_from(body["ticket"]) == 3131
    assert body["expires_in"] > 0


def test_stream_rejects_a_session_token_in_the_query(client, session_token):
    response = client.get(f"/api/media/stream?path=/data/movies/x.mp4&token={session_token}")
    assert response.status_code == 401


def test_stream_accepts_a_ticket(client):
    # 404 (not 401) proves the ticket authenticated and only the file is absent.
    ticket = media_tickets.issue(3131)
    response = client.get(f"/api/media/stream?path=/data/movies/absent.mp4&ticket={ticket}")
    assert response.status_code != 401


def test_stream_rejects_a_forged_ticket(client):
    response = client.get("/api/media/stream?path=/data/movies/x.mp4&ticket=not.a.ticket")
    assert response.status_code == 401


def test_ticket_does_not_open_the_wider_api(client):
    # A leaked stream URL must not become an account.
    ticket = media_tickets.issue(3131)
    for path in ("/api/auth/users", "/api/system/settings", "/api/media/library/movies"):
        assert client.get(f"{path}?ticket={ticket}").status_code in (401, 403)


# ── no client may put the session token in a URL ──────────────────────────
# The first sweep for this only looked for a literal "&token=" in a template
# string, and missed gallery-photos.js building the same thing through
# URLSearchParams — so every photo thumbnail 401'd. It also missed the Android
# client entirely. These check every form, in every client.

TOKEN_IN_URL_PATTERNS = [
    r"[?&]token=\$\{",                     # `...?token=${t}`
    r"[?&]token=\"?\s*\+",                 # "...?token=" + t
    r"params\.set\(\s*['\"]token['\"]",    # URLSearchParams
    r"append\(\s*['\"]token['\"]",
    r"[?&]token=\$\{enc\(",                # Kotlin string template
]


def _offending_lines(text, patterns):
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        if "display_token" in line:
            continue
        for pattern in patterns:
            if re.search(pattern, line):
                hits.append((number, line.strip()[:100]))
                break
    return hits


def test_no_frontend_module_puts_the_session_token_in_a_url():
    for path in Path("app/static/js").glob("*.js"):
        hits = _offending_lines(path.read_text(), TOKEN_IN_URL_PATTERNS)
        assert not hits, f"{path} puts the session token in a URL: {hits}"


def test_the_android_client_does_not_put_the_session_token_in_a_url():
    android = Path("android/app/src/main/java/com/nomadpi/android")
    if not android.exists():
        pytest.skip("android client not present in this checkout")
    for path in android.glob("*.kt"):
        hits = _offending_lines(path.read_text(), TOKEN_IN_URL_PATTERNS)
        assert not hits, f"{path} puts the session token in a URL: {hits}"


def test_the_android_client_builds_media_urls_from_a_ticket():
    api = Path("android/app/src/main/java/com/nomadpi/android/NomadApi.kt")
    if not api.exists():
        pytest.skip("android client not present in this checkout")
    source = api.read_text()
    assert "ensureMediaTicket" in source
    # The builders run inside composables; a blocking fetch there would raise
    # NetworkOnMainThreadException, so they must read the cache only.
    builders = source[source.index("fun musicStreamUrl"):source.index("fun absoluteUrl")]
    assert "ensureMediaTicket(" not in builders, "a URL builder fetches on the calling thread"
    assert "cachedMediaTicket" in builders


def test_every_byte_serving_endpoint_reached_from_a_url_accepts_a_ticket():
    # <img src>, <video src> and native loaders cannot send a header, so any
    # endpoint they hit must take a media ticket.
    from app.main import app as fastapi_app
    from app.routers.auth import get_media_user_id

    URL_REACHED = (
        "/api/media/stream",
        "/api/media/subtitle",
        "/api/playback/music/stream",
        "/api/playback/music/artwork",
        "/api/playback/gallery/item/{item_id}",
    )
    found = {}

    def walk(router, prefix=""):
        for route in getattr(router, "routes", []):
            ctx = getattr(route, "include_context", None)
            if ctx is not None:
                walk(ctx.included_router, prefix + (ctx.prefix or ""))
                continue
            dependant = getattr(route, "dependant", None)
            if dependant is None:
                continue
            names = {d.call.__name__ for d in dependant.dependencies if d.call}
            found.setdefault(prefix + getattr(route, "path", ""), set()).update(names)

    for route in fastapi_app.routes:
        ctx = getattr(route, "include_context", None)
        if ctx is not None:
            walk(ctx.included_router, ctx.prefix or "")

    for path in URL_REACHED:
        assert path in found, f"{path} is no longer registered"
        assert "get_media_user_id" in found[path], f"{path} does not accept a media ticket"
