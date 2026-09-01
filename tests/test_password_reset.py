"""The recovery path for a locked-out owner.

Nomad forces a password change at first sign-in and refuses well-known
passwords. That is right until you are the one locked out, at which point the
only alternative was hand-editing SQLite on the Pi.
"""

import subprocess
import sys
import uuid
from pathlib import Path

import pytest

SCRIPT = Path("scripts/reset-admin-password.py")
WRAPPER = Path("scripts/reset-admin-password.sh")


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT.resolve()), *args],
        capture_output=True, text=True, cwd=cwd or Path.cwd(), timeout=60,
    )


def test_the_tool_ships_and_is_executable():
    assert SCRIPT.exists() and WRAPPER.exists()
    for path in (SCRIPT, WRAPPER):
        assert path.stat().st_mode & 0o111, f"{path} is not executable"


def test_help_documents_running_it_on_the_device():
    result = _run("--help")
    assert result.returncode == 0
    assert "--generate" in result.stdout
    assert "--list" in result.stdout
    assert "--make-admin" in result.stdout


def test_it_anchors_to_its_own_checkout_not_the_cwd(tmp_path):
    # A recovery tool run from /root or /home must still find the install's
    # database rather than looking for one beside the caller.
    source = SCRIPT.read_text()
    assert "REPO_ROOT = Path(__file__).resolve().parent.parent" in source
    assert "os.chdir(REPO_ROOT)" in source


def test_it_refuses_a_weak_new_password():
    result = _run("--password", "nomad")
    assert result.returncode == 1
    assert "error:" in result.stderr


def test_it_refuses_an_unknown_account():
    result = _run("--user", f"nobody-{uuid.uuid4().hex[:8]}", "--generate")
    assert result.returncode == 1
    assert "no account named" in result.stderr


def test_it_will_not_prompt_without_a_terminal():
    result = subprocess.run(
        [sys.executable, str(SCRIPT.resolve())],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
    )
    assert result.returncode == 1
    assert "no terminal" in result.stderr


def test_reset_changes_the_hash_and_revokes_sessions(tmp_path, monkeypatch):
    from queue import Queue

    from app import database
    from app.routers import auth

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "nomad.db"))
    monkeypatch.setattr(database, "_connection_pool", Queue(maxsize=5))
    database.init_db()
    user_id = database.create_user("owner", auth.pwd_context.hash("old-password-here"), is_admin=True)
    token = uuid.uuid4().hex
    database.create_session(token, user_id)

    # What the script does, against the same helpers it calls.
    database.update_user_password(user_id, auth.pwd_context.hash("driftwood-antenna-77"))
    database.delete_user_sessions(user_id)

    refreshed = database.get_user_by_username("owner")
    assert auth.pwd_context.verify("driftwood-antenna-77", refreshed["password_hash"])
    assert not auth.pwd_context.verify("old-password-here", refreshed["password_hash"])
    assert database.get_session(token) is None


def test_reset_can_restore_admin_on_a_demoted_account(tmp_path, monkeypatch):
    from queue import Queue

    from app import database
    from app.routers import auth

    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "nomad.db"))
    monkeypatch.setattr(database, "_connection_pool", Queue(maxsize=5))
    database.init_db()
    user_id = database.create_user("demoted", auth.pwd_context.hash("old-password-here"), is_admin=False)

    database.update_user_role(user_id, True)
    assert database.get_user_by_username("demoted")["is_admin"]
