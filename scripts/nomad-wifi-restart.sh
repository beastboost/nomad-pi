#!/bin/bash
# Bounce the Wi-Fi radio and the Nomad hotspot profile.
#
# This exists so the sudoers policy does not have to grant `sudo bash -c *`,
# which is indistinguishable from full root. The web admin calls this fixed
# script instead, and sudoers grants exactly this path.
set -uo pipefail

nmcli connection down NomadPi >/dev/null 2>&1 || true
nmcli radio wifi off >/dev/null 2>&1 || true
sleep 2
nmcli radio wifi on >/dev/null 2>&1 || true
exit 0
