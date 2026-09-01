#!/usr/bin/env python3
"""Reset a Nomad Pi account password from the device itself.

The recovery path of last resort. Nomad forces a password change at first
sign-in and refuses well-known passwords, which is right up until you are the
one locked out — at which point the only alternative is hand-editing SQLite.

Physical or SSH access to the box is the authorisation here, the same trust
level as pulling the SD card, so this deliberately does not ask for the old
password. It must be run on the Pi, as the user that owns the database.

    sudo -u nomad ./venv/bin/python scripts/reset-admin-password.py
    sudo -u nomad ./venv/bin/python scripts/reset-admin-password.py --list
    sudo -u nomad ./venv/bin/python scripts/reset-admin-password.py --user dad
    sudo -u nomad ./venv/bin/python scripts/reset-admin-password.py --generate
"""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
from pathlib import Path

# Run from anywhere: the repository root is this file's parent's parent.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


def _fail(message: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset a Nomad Pi account password.",
        epilog="Run this on the Pi, as the user that owns data/nomad.db.",
    )
    parser.add_argument("--user", default=None,
                        help="Username to reset (default: the only admin, or 'admin')")
    parser.add_argument("--password", default=None,
                        help="New password. Omitted, you are prompted; see also --generate")
    parser.add_argument("--generate", action="store_true",
                        help="Generate a strong password and print it")
    parser.add_argument("--list", action="store_true",
                        help="List accounts and exit, changing nothing")
    parser.add_argument("--make-admin", action="store_true",
                        help="Also grant admin, for when the last admin was demoted")
    parser.add_argument("--keep-sessions", action="store_true",
                        help="Do not sign the account out of its other devices")
    args = parser.parse_args()

    try:
        from app import database
        from app.routers import auth
    except Exception as exc:  # noqa: BLE001 - a bad venv should say so plainly
        _fail(f"could not import Nomad ({exc}).\n"
              "       Run this with the app's own interpreter, e.g.\n"
              "       sudo -u nomad ./venv/bin/python scripts/reset-admin-password.py")

    db_path = Path(database.DB_PATH)
    if not db_path.exists():
        _fail(f"no database at {db_path.resolve()}. Is this a Nomad checkout that has been run?")

    users = database.get_all_users()
    if not users:
        _fail("this database has no accounts. Start Nomad once to bootstrap one.")

    if args.list:
        # get_all_users() selects id/username/is_admin/created_at only, so this
        # deliberately does not show must_change_password rather than printing
        # a column that would always read "no".
        print(f"{'id':>4}  {'username':<24} admin")
        for user in users:
            print(f"{user['id']:>4}  {user['username']:<24} "
                  f"{'yes' if user['is_admin'] else 'no'}")
        return 0

    if args.user:
        target = database.get_user_by_username(args.user)
        if not target:
            _fail(f"no account named {args.user!r}. Use --list to see them.")
    else:
        admins = [u for u in users if u["is_admin"]]
        if len(admins) == 1:
            target = admins[0]
        else:
            target = database.get_user_by_username("admin")
            if not target:
                _fail("could not pick an account by default. Name one with --user.")

    if args.generate:
        password = secrets.token_urlsafe(12)
    elif args.password:
        password = args.password
    else:
        if not sys.stdin.isatty():
            _fail("no terminal to prompt on. Pass --password or --generate.")
        password = getpass.getpass(f"New password for {target['username']}: ")
        if password != getpass.getpass("Confirm: "):
            _fail("those did not match.")

    valid, why = auth.validate_password_strength(password)
    if not valid:
        _fail(why)

    database.update_user_password(target["id"], auth.pwd_context.hash(password))
    if args.make_admin and not target["is_admin"]:
        database.update_user_role(target["id"], True)
    if not args.keep_sessions:
        # update_user_password already revokes sessions in the running app, but
        # this script may be run against a stopped service; be explicit.
        database.delete_user_sessions(target["id"])

    print(f"Password reset for {target['username']}.")
    if args.generate:
        print(f"New password: {password}")
    if args.make_admin:
        print("Granted admin.")
    if not args.keep_sessions:
        print("Signed out of all devices.")
    print("\nRestart Nomad if it is running:  sudo systemctl restart nomad-pi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
