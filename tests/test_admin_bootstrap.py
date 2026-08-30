"""A fresh install must not be usable on a password everyone knows.

ALLOW_INSECURE_DEFAULT used to default to true, so every install shipped with
the admin password "nomad", and must_change_password was reported to the client
and then ignored — the prompt could simply be dismissed.
"""

import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers import auth


def test_insecure_default_is_opt_in():
    # The shipped default must be off. A lab box can still set the env var.
    source = Path("app/routers/auth.py").read_text()
    assert 'os.environ.get("ALLOW_INSECURE_DEFAULT", "false")' in source


@pytest.mark.parametrize("password", ["nomad", "admin", "password", "raspberry", "changeme"])
def test_known_weak_passwords_are_rejected(password, monkeypatch):
    monkeypatch.setattr(auth, "ALLOW_INSECURE_DEFAULT", False)
    valid, _ = auth.validate_password_strength(password)
    assert not valid


def test_a_real_passphrase_is_accepted():
    assert auth.validate_password_strength("driftwood-antenna-77")[0]


def test_short_passwords_are_still_rejected():
    assert not auth.validate_password_strength("abc")[0]


def test_weak_check_is_case_insensitive():
    assert auth.is_weak_password("NoMaD")
    assert auth.is_weak_password("  password  ")


# ── must_change_password is enforced, not merely advertised ───────────────

class _FakeRequest:
    def __init__(self, path):
        self.url = type("U", (), {"path": path})()


def test_provisional_password_blocks_the_api(monkeypatch):
    monkeypatch.setattr(auth.database, "get_user_by_id", lambda uid: {"must_change_password": 1})
    with pytest.raises(HTTPException) as excinfo:
        auth.enforce_password_change(_FakeRequest("/api/media/library/movies"), 1)
    assert excinfo.value.status_code == 403


@pytest.mark.parametrize("path", list(auth.PASSWORD_CHANGE_EXEMPT_PATHS))
def test_the_user_can_still_reach_what_they_need_to_fix_it(path, monkeypatch):
    monkeypatch.setattr(auth.database, "get_user_by_id", lambda uid: {"must_change_password": 1})
    auth.enforce_password_change(_FakeRequest(path), 1)


def test_a_settled_account_is_not_blocked(monkeypatch):
    monkeypatch.setattr(auth.database, "get_user_by_id", lambda uid: {"must_change_password": 0})
    auth.enforce_password_change(_FakeRequest("/api/media/library/movies"), 1)


# ── sudoers policy ────────────────────────────────────────────────────────

def test_installers_no_longer_grant_blanket_root():
    for script in ("setup.sh", "update.sh"):
        source = Path(script).read_text()
        assert "NOPASSWD: ALL" not in source, f"{script} still grants unrestricted sudo"
        assert "nomad_install_sudoers" in source


def _sudoers_directives() -> str:
    """The template minus its comments, so prose about the old policy is not
    mistaken for the policy."""
    lines = Path("scripts/nomad-sudoers.template").read_text().splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_sudoers_template_scopes_the_grant():
    template = _sudoers_directives()
    # The four jobs Nomad actually needs privilege for.
    for alias in ("NOMAD_POWER", "NOMAD_STORAGE", "NOMAD_NETWORK", "NOMAD_UPDATE"):
        assert alias in template
    # And not a blanket grant by another spelling.
    assert not re.search(r"NOPASSWD:\s*ALL\b", template)
    # systemctl must be pinned to units, never granted bare.
    assert "/usr/bin/systemctl restart nomad-pi.service" in template
    assert not re.search(r"^\s*Cmnd_Alias[^=]*=\s*/usr/bin/systemctl\s*(,|$)", template, re.M)


def test_sudoers_template_does_not_grant_a_shell():
    template = _sudoers_directives()
    for shell in ("/bin/bash", "/bin/sh", "/usr/bin/bash", "/usr/bin/env", "/usr/bin/python"):
        assert shell not in template, f"{shell} in sudoers is equivalent to full root"


def test_wifi_restart_uses_a_fixed_script_not_sudo_bash():
    source = Path("app/routers/system_legacy.py").read_text()
    assert '"bash", "-c"' not in source
    assert Path("scripts/nomad-wifi-restart.sh").exists()


def test_hotspot_passphrase_is_per_device():
    source = Path("scripts/network-appliance.sh").read_text()
    assert "nomadpassword" not in source, "the shared default hotspot key is back"
    assert "nomad_hotspot_password" in source
