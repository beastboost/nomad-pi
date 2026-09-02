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
    def __init__(self, path, host="192.168.1.20"):
        self.url = type("U", (), {"path": path})()
        self.client = type("C", (), {"host": host})()


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


# ── the known bootstrap password ─────────────────────────────────────────
# Nomad bootstraps on "nomad" on purpose. An image install has no console to
# print a generated secret to, and reading one over SSH needs a network you can
# only reach by logging in first. What makes it safe is that it cannot be kept:
# the API is closed until it is replaced, and only local clients can sign in
# while it is outstanding.

def test_setup_and_the_app_agree_on_the_bootstrap_password():
    setup = Path("setup.sh").read_text()
    assert 'ADMIN_PASS_VALUE="nomad"' in setup
    # The app must take it verbatim; silently substituting a random one is what
    # made the installer announce a password that did not work.
    source = Path("app/routers/auth.py").read_text()
    assert "password = secrets.token_urlsafe(16)" not in source


def test_setup_tells_the_operator_the_password_and_that_it_expires():
    setup = Path("setup.sh").read_text()
    assert 'echo "Admin:   admin / $ADMIN_PASS_VALUE"' in setup
    assert "set your own password immediately" in setup


def test_the_bootstrap_password_still_cannot_be_chosen(monkeypatch):
    # Accepting "nomad" as a starting point must not mean it can be settled on.
    monkeypatch.setattr(auth, "ALLOW_INSECURE_DEFAULT", False)
    assert not auth.validate_password_strength("nomad")[0]


def test_hotspot_passphrase_is_unchanged():
    # A per-device passphrase deadlocks the flashed-image install: joining the
    # AP is the only way to reach the UI that would show it.
    appliance = Path("scripts/network-appliance.sh").read_text()
    assert 'NOMAD_HOTSPOT_PASSWORD="${NOMAD_HOTSPOT_PASSWORD:-nomadpassword}"' in appliance
    firstboot = Path("os-builder/stage3-nomad/03-setup-services/files/nomad-pi-firstboot.sh").read_text()
    assert "nomadpassword" in firstboot, "image and setup.sh installs must agree"


# ── the race a known password opens ──────────────────────────────────────

@pytest.mark.parametrize("host", ["127.0.0.1", "192.168.1.20", "10.42.0.9", "100.101.5.9", "::1"])
def test_local_clients_may_sign_in_while_provisional(host):
    assert auth._is_local_client(host)


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "2606:4700::1111"])
def test_remote_clients_may_not(host):
    assert not auth._is_local_client(host)


class _ClientRequest:
    def __init__(self, host):
        self.client = type("C", (), {"host": host})() if host else None
        self.url = type("U", (), {"path": "/api/auth/login"})()


def test_provisional_account_refuses_a_remote_sign_in(monkeypatch):
    monkeypatch.setattr(auth, "ALLOW_INSECURE_DEFAULT", False)
    with pytest.raises(HTTPException) as excinfo:
        auth.enforce_local_only_while_provisional(
            _ClientRequest("8.8.8.8"), {"must_change_password": 1})
    assert excinfo.value.status_code == 403


def test_provisional_account_allows_a_local_sign_in(monkeypatch):
    monkeypatch.setattr(auth, "ALLOW_INSECURE_DEFAULT", False)
    auth.enforce_local_only_while_provisional(
        _ClientRequest("192.168.1.20"), {"must_change_password": 1})


def test_a_settled_account_is_reachable_from_anywhere(monkeypatch):
    # The restriction is about the setup password, not about remote access.
    monkeypatch.setattr(auth, "ALLOW_INSECURE_DEFAULT", False)
    auth.enforce_local_only_while_provisional(
        _ClientRequest("8.8.8.8"), {"must_change_password": 0})


def test_lab_override_lifts_the_restriction(monkeypatch):
    monkeypatch.setattr(auth, "ALLOW_INSECURE_DEFAULT", True)
    auth.enforce_local_only_while_provisional(
        _ClientRequest("8.8.8.8"), {"must_change_password": 1})


# ── the scoped policy must cover what the code actually runs ──────────────
# Scoping sudo trades a blanket grant for a list that can fall out of date. A
# missing entry does not fail loudly: the sudo call returns non-zero and the
# admin feature silently stops working.

def _sudo_invocations():
    """Every ["sudo", ...] argument list built anywhere in app/."""
    import ast

    found = []
    for path in Path("app").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.List) or not node.elts:
                continue
            first = node.elts[0]
            if not (isinstance(first, ast.Constant) and first.value == "sudo"):
                continue
            words = []
            for element in node.elts[1:]:
                if isinstance(element, ast.Constant):
                    words.append(str(element.value))
                else:
                    words.append(None)  # resolved at runtime
            words = [w for w in words if w != "-n"]
            if words:
                found.append((str(path), node.lineno, words))
    return found


def test_the_sudo_probe_is_granted():
    # `sudo -n true` is how two diagnostics endpoints ask whether passwordless
    # sudo works. Ungranted, they report a healthy device as broken.
    probes = [w for _, _, w in _sudo_invocations() if w and w[0] == "true"]
    assert probes, "the sudo probe has moved; update this test"
    directives = _sudoers_directives()
    assert "/usr/bin/true" in directives or "/bin/true" in directives


def test_every_literal_sudo_binary_appears_in_the_policy():
    directives = _sudoers_directives()
    granted = set(re.findall(r"(/[A-Za-z0-9_/.*-]+)", directives))
    granted_names = {p.rsplit("/", 1)[-1] for p in granted}

    missing = []
    for path, line, words in _sudo_invocations():
        binary = words[0]
        if binary is None:  # shutil.which() result, checked by path below
            continue
        name = binary.rsplit("/", 1)[-1]
        if name not in granted_names:
            missing.append(f"{path}:{line} runs sudo {name}")
    assert not missing, "sudo calls with no matching grant: " + "; ".join(missing)


def test_mount_targets_inside_the_checkout_are_grantable():
    # Drives can be mounted under data/external as well as /media and /mnt;
    # the chown/chmod that follows the mount has to reach all three or the
    # library cannot read the drive it just mounted.
    directives = _sudoers_directives()
    assert "__ROOT__/data/external/*" in directives
