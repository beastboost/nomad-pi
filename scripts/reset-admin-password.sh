#!/bin/bash
# Convenience wrapper: run the reset tool with Nomad's own interpreter.
#
#   sudo bash scripts/reset-admin-password.sh --list
#   sudo bash scripts/reset-admin-password.sh --generate
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

PYTHON="$SCRIPT_DIR/venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
[ -n "$PYTHON" ] || { echo "error: no python3 found" >&2; exit 1; }

# The database is owned by the account the service runs as. Running as root
# would work but leaves root-owned WAL files behind that the service then
# cannot write, so drop to the owner when we can identify them.
OWNER="$(stat -c '%U' data/nomad.db 2>/dev/null || true)"
if [ -n "$OWNER" ] && [ "$OWNER" != "$(id -un)" ] && [ "$(id -u)" -eq 0 ]; then
    exec sudo -u "$OWNER" "$PYTHON" scripts/reset-admin-password.py "$@"
fi
exec "$PYTHON" scripts/reset-admin-password.py "$@"
