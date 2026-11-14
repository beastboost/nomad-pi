"""Hotspot secrets must survive setup, updates and pre-provisioned image boot."""
import os
from pathlib import Path
import subprocess


def _source_network_with(override=None):
    env = dict(os.environ)
    env.pop("NOMAD_HOTSPOT_PASSWORD", None)
    if override is not None:
        env["NOMAD_HOTSPOT_PASSWORD"] = override
    script = (
        'nomad_get_env_key() { printf "unique-device-secret"; }; '
        '. scripts/network-appliance.sh; '
        'printf "%s" "$NOMAD_HOTSPOT_PASSWORD"'
    )
    result = subprocess.run(
        ["bash", "-c", script], env=env, text=True, check=True,
        capture_output=True,
    )
    return result.stdout


def test_network_helper_uses_stored_hotspot_password():
    assert _source_network_with() == "unique-device-secret"


def test_explicit_hotspot_override_wins():
    assert _source_network_with("my-configured-pass") == "my-configured-pass"


def test_setup_persists_hotspot_secret():
    setup = Path("setup.sh").read_text(encoding="utf-8")
    assert 'nomad_set_env_key "$ENV_FILE" NOMAD_HOTSPOT_PASSWORD "$NOMAD_HOTSPOT_PASSWORD"' in setup


def test_image_firstboot_uses_preprovisioned_password():
    firstboot = Path("os-builder/stage3-nomad/03-setup-services/files/nomad-pi-firstboot.sh").read_text(encoding="utf-8")
    assert "NOMAD_HOTSPOT_PASSWORD=" in firstboot
    assert 'wifi-sec.psk "$HOTSPOT_PASSWORD"' in firstboot
