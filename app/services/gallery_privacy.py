"""Retire the pre-profile shared Gallery index.

Nomad Photos scans the active profile's roots directly. Keeping old gallery
rows in library_index would let global search reveal filenames from the legacy
shared gallery even though the profile-aware stream route correctly denied the
file. Removing only category='gallery' rows is cheap, idempotent and leaves all
other media indexes untouched.
"""

from app import database


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


retire_shared_gallery_index()
