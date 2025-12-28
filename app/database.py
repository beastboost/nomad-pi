import sqlite3
import os
import json
from typing import Optional

DB_PATH = "data/nomad.db"

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS progress (
            path TEXT PRIMARY KEY,
            current_time REAL,
            duration REAL,
            last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS file_metadata (
            path TEXT PRIMARY KEY,
            media_type TEXT,
            title TEXT,
            year TEXT,
            imdb_id TEXT,
            poster TEXT,
            plot TEXT,
            rated TEXT,
            runtime TEXT,
            genre TEXT,
            meta_json TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS library_index (
            path TEXT PRIMARY KEY,
            category TEXT,
            name TEXT,
            folder TEXT,
            source TEXT,
            poster TEXT,
            mtime REAL,
            size INTEGER,
            indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS library_index_state (
            category TEXT PRIMARY KEY,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            item_count INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def set_setting(key: str, value: str):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
    ''', (key, value))
    conn.commit()
    conn.close()

def get_setting(key: str) -> Optional[str]:
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    if row:
        return row['value']
    return None

def update_progress(path: str, current_time: float, duration: float):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO progress (path, current_time, duration, last_played)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(path) DO UPDATE SET
            current_time = excluded.current_time,
            duration = excluded.duration,
            last_played = CURRENT_TIMESTAMP
    ''', (path, current_time, duration))
    conn.commit()
    conn.close()

def get_progress(path: str) -> Optional[dict]:
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT current_time, duration, last_played FROM progress WHERE path = ?', (path,))
    row = c.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def get_all_progress():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT path, current_time, duration, last_played FROM progress')
    rows = c.fetchall()
    conn.close()
    return {row['path']: dict(row) for row in rows}

def get_file_metadata(path: str) -> Optional[dict]:
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM file_metadata WHERE path = ?', (path,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    meta_raw = data.get("meta_json")
    if isinstance(meta_raw, str) and meta_raw:
        try:
            data["meta"] = json.loads(meta_raw)
        except Exception:
            data["meta"] = None
    else:
        data["meta"] = None
    return data

def upsert_file_metadata(path: str, media_type: str, meta: dict):
    title = meta.get("Title")
    year = meta.get("Year")
    imdb_id = meta.get("imdbID")
    poster = meta.get("Poster")
    plot = meta.get("Plot")
    rated = meta.get("Rated")
    runtime = meta.get("Runtime")
    genre = meta.get("Genre")
    meta_json = json.dumps(meta, ensure_ascii=False)

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO file_metadata (path, media_type, title, year, imdb_id, poster, plot, rated, runtime, genre, meta_json, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(path) DO UPDATE SET
            media_type = excluded.media_type,
            title = excluded.title,
            year = excluded.year,
            imdb_id = excluded.imdb_id,
            poster = excluded.poster,
            plot = excluded.plot,
            rated = excluded.rated,
            runtime = excluded.runtime,
            genre = excluded.genre,
            meta_json = excluded.meta_json,
            fetched_at = CURRENT_TIMESTAMP
    ''', (path, media_type, title, year, imdb_id, poster, plot, rated, runtime, genre, meta_json))
    conn.commit()
    conn.close()

def upsert_library_index_item(item: dict):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO library_index (path, category, name, folder, source, poster, mtime, size, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(path) DO UPDATE SET
            category = excluded.category,
            name = excluded.name,
            folder = excluded.folder,
            source = excluded.source,
            poster = excluded.poster,
            mtime = excluded.mtime,
            size = excluded.size,
            indexed_at = CURRENT_TIMESTAMP
    ''', (
        item.get("path"),
        item.get("category"),
        item.get("name"),
        item.get("folder"),
        item.get("source"),
        item.get("poster"),
        item.get("mtime"),
        item.get("size"),
    ))
    conn.commit()
    conn.close()

def delete_library_index_item(path: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM library_index WHERE path = ?", (path,))
    conn.commit()
    conn.close()

def upsert_library_index_items(items: list):
    if not items:
        return
    conn = get_db()
    c = conn.cursor()
    c.executemany('''
        INSERT INTO library_index (path, category, name, folder, source, poster, mtime, size, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(path) DO UPDATE SET
            category = excluded.category,
            name = excluded.name,
            folder = excluded.folder,
            source = excluded.source,
            poster = excluded.poster,
            mtime = excluded.mtime,
            size = excluded.size,
            indexed_at = CURRENT_TIMESTAMP
    ''', ((
        it.get("path"),
        it.get("category"),
        it.get("name"),
        it.get("folder"),
        it.get("source"),
        it.get("poster"),
        it.get("mtime"),
        it.get("size"),
    ) for it in items))
    conn.commit()
    conn.close()

def clear_library_index_category(category: str):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM library_index WHERE category = ?', (category,))
    c.execute('DELETE FROM library_index_state WHERE category = ?', (category,))
    conn.commit()
    conn.close()

def set_library_index_state(category: str, item_count: int):
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        INSERT INTO library_index_state (category, scanned_at, item_count)
        VALUES (?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(category) DO UPDATE SET
            scanned_at = CURRENT_TIMESTAMP,
            item_count = excluded.item_count
    ''', (category, int(item_count or 0)))
    conn.commit()
    conn.close()

def get_library_index_state(category: str) -> Optional[dict]:
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT category, scanned_at, item_count FROM library_index_state WHERE category = ?', (category,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def query_library_index(category: str, q: str, offset: int, limit: int):
    q = (q or "").strip().lower()
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 50), 200))

    conn = get_db()
    c = conn.cursor()
    if q:
        like = f"%{q}%"
        c.execute('''
            SELECT path, category, name, folder, source, poster, mtime, size
            FROM library_index
            WHERE category = ?
              AND (LOWER(name) LIKE ? OR LOWER(folder) LIKE ?)
            ORDER BY LOWER(folder), LOWER(name)
            LIMIT ? OFFSET ?
        ''', (category, like, like, limit, offset))
    else:
        c.execute('''
            SELECT path, category, name, folder, source, poster, mtime, size
            FROM library_index
            WHERE category = ?
            ORDER BY LOWER(folder), LOWER(name)
            LIMIT ? OFFSET ?
        ''', (category, limit, offset))

    rows = c.fetchall()

    if q:
        like = f"%{q}%"
        c.execute('''
            SELECT COUNT(1) AS cnt
            FROM library_index
            WHERE category = ?
              AND (LOWER(name) LIKE ? OR LOWER(folder) LIKE ?)
        ''', (category, like, like))
    else:
        c.execute('SELECT COUNT(1) AS cnt FROM library_index WHERE category = ?', (category,))
    total = int(c.fetchone()["cnt"])

    conn.close()
    return [dict(r) for r in rows], total

def rename_media_path(old_path: str, new_path: str):
    if not old_path or not new_path or old_path == new_path:
        return
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE progress SET path = ? WHERE path = ?', (new_path, old_path))
    c.execute('UPDATE file_metadata SET path = ? WHERE path = ?', (new_path, old_path))
    c.execute('UPDATE library_index SET path = ? WHERE path = ?', (new_path, old_path))
    conn.commit()
    conn.close()

SESSION_MAX_AGE_DAYS = int(os.environ.get("SESSION_MAX_AGE_DAYS", 30))

def create_session(token: str):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO sessions (token) VALUES (?)', (token,))
    conn.commit()
    conn.close()

def get_session(token: str) -> Optional[dict]:
    cleanup_sessions() # Run cleanup when checking sessions
    conn = get_db()
    c = conn.cursor()
    # Only return session if it hasn't expired
    c.execute('''
        SELECT token, created_at 
        FROM sessions 
        WHERE token = ? AND created_at >= datetime('now', '-' || ? || ' days')
    ''', (token, SESSION_MAX_AGE_DAYS))
    row = c.fetchone()
    
    if not row:
        # If no row found, it might have expired. Try to delete it just in case.
        c.execute('DELETE FROM sessions WHERE token = ?', (token,))
        conn.commit()
        conn.close()
        return None
        
    conn.close()
    return dict(row)

def delete_session(token: str):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM sessions WHERE token = ?', (token,))
    conn.commit()
    conn.close()

def cleanup_sessions():
    """Remove sessions older than the configured max_age."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            DELETE FROM sessions 
            WHERE created_at < datetime('now', '-' || ? || ' days')
        ''', (SESSION_MAX_AGE_DAYS,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error cleaning up sessions: {e}")
