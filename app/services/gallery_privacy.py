"""Retire and migrate the pre-profile shared Gallery.

Nomad Photos scans profile-private roots directly. Keeping old gallery rows in
``library_index`` could expose filenames through global search, while keeping
old files below ``data/gallery`` would leave them under Nomad's legacy /data
static mount. On startup we therefore assign the old shared gallery to the
primary account's default household profile and move supported photo/video
files into ``private/gallery`` (outside the web mount).

Older Nomad was primarily a single-owner appliance, so on multi-user installs
the primary account is the first admin account, falling back to the oldest
user. That is safer than continuing to expose the historical global gallery to
every authenticated profile.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil

from app import database
from app.services.household_profiles import HouseholdProfileStore


logger = logging.getLogger(__name__)
_ALLOWED = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif",
    ".mp4", ".mov", ".m4v", ".webm",
}


def retire_shared_gallery_index() -> None:
    conn = database.get_db()
    try:
        conn.execute("DELETE FROM library_index WHERE category='gallery'")
        conn.execute("DELETE FROM library_index_state WHERE category='gallery'")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        database.return_db(conn)


def _primary_user():
    try:
        users = list(database.get_all_users() or [])
    except Exception:
        return None
    if not users:
        return None
    admins = [user for user in users if bool(user.get("is_admin"))]
    candidates = admins or users
    try:
        candidates.sort(key=lambda user: int(user.get("id") or 0))
    except Exception:
        pass
    return candidates[0]


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(2, 10000):
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    raise OSError(f"Could not choose a unique gallery destination for {path.name}")


def migrate_legacy_gallery() -> None:
    source = Path("data/gallery").resolve()
    if not source.is_dir():
        return

    files = [
        path for path in source.rglob("*")
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in _ALLOWED
    ]
    if not files:
        return

    owner = _primary_user()
    if not owner:
        logger.warning("Legacy Gallery contains files but no account exists to own them yet")
        return

    user_id = int(owner.get("id"))
    try:
        profile = HouseholdProfileStore(database.DB_PATH).default(user_id)
    except Exception as exc:
        logger.warning("Could not resolve default profile for Gallery migration: %s", exc)
        return

    destination_root = (Path("private/gallery") / f"u{user_id}" / f"p{profile.id}" / "Legacy").resolve()
    moved = 0
    for path in files:
        try:
            relative = path.relative_to(source)
            destination = _unique((destination_root / relative).resolve())
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(destination))
            moved += 1
        except Exception as exc:
            logger.warning("Could not migrate legacy Gallery file %s: %s", path, exc)

    # Remove empty legacy folders but retain data/gallery itself for old tools
    # that expect the directory to exist.
    try:
        for directory in sorted(
            [path for path in source.rglob("*") if path.is_dir()],
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
    except OSError:
        pass

    if moved:
        logger.info(
            "Migrated %d legacy Gallery item(s) into private profile %s (%s)",
            moved, profile.id, profile.name,
        )


retire_shared_gallery_index()
migrate_legacy_gallery()
