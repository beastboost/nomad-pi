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


# ── the forced change must be completable ─────────────────────────────────
# Enforcing must_change_password without a way to satisfy it would strand a
# first-run user in an app that 403s every request.

def test_login_screen_offers_a_first_password_form():
    markup = Path("app/static/index.html").read_text()
    assert 'id="first-password-form"' in markup
    assert 'id="new-password-input"' in markup
    assert 'id="confirm-password-input"' in markup


def test_client_diverts_a_provisional_account_to_that_form():
    source = Path("app/static/js/app_legacy.js").read_text()
    assert "must_change_password" in source, "the client ignores the provisional flag"
    assert "setFirstPassword" in source
    # Both entry points: a fresh login and a stored token on boot.
    assert source.count("must_change_password") >= 2


def test_change_password_endpoint_is_reachable_while_provisional():
    assert "/api/auth/change-password" in auth.PASSWORD_CHANGE_EXEMPT_PATHS


# ── setup.sh and the app must agree on the bootstrap password ─────────────
# setup.sh wrote ADMIN_PASSWORD=nomad into /etc/nomadpi.env and announced it as
# the initial password. The app then rejected it as well-known and generated a
# random one instead, so the operator was told a password that did not work and
# the real one only ever reached the service journal.

def test_setup_does_not_bootstrap_on_a_well_known_password():
    setup = Path("setup.sh").read_text()
    assert 'ADMIN_PASS_VALUE="nomad"' not in setup
    assert "initial password is 'nomad'" not in setup


def test_setup_generates_a_password_the_app_will_accept(monkeypatch):
    monkeypatch.setattr(auth, "ALLOW_INSECURE_DEFAULT", False)
    setup = Path("setup.sh").read_text()
    assert "ADMIN_PASS_GENERATED=1" in setup
    # 16 random lowercase-alnum characters clears both the length floor and the
    # well-known list, so the app uses it verbatim instead of silently
    # replacing it with one nobody has seen.
    assert "head -c 16" in setup
    assert not auth.is_weak_password("niep4ehi2e8mqroe")


def test_setup_tells_the_operator_where_to_find_it():
    setup = Path("setup.sh").read_text()
    assert "ADMIN_PASSWORD /etc/nomadpi.env" in setup, "no recovery hint in the banner"
    assert 'echo "Admin:   admin / $ADMIN_PASS_VALUE"' in setup, "banner does not print it"
