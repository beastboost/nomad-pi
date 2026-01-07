import sqlite3
import os
import json
import re
import threading
from queue import Queue
from typing import List, Dict, Optional
# Removed heavy scikit-learn/numpy imports for SBC stability

def sanitize_like_pattern(pattern: str) -> str:
    """
    Sanitize user input for SQL LIKE queries to prevent SQL injection.
    Escapes special LIKE characters: %, _, and backslash.
    """
    if not pattern:
        return ""
    # Escape special characters used in LIKE patterns
    pattern = str(pattern).replace("\\", "\\\\")
    pattern = pattern.replace("%", "\\%")
    pattern = pattern.replace("_", "\\_")
    return pattern

DB_PATH = "data/nomad.db"

# Connection Pool
_connection_pool = Queue(maxsize=10)
_pool_lock = threading.Lock()

def natural_sort_key_list(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'([0-9]+)', str(s or ''))]

def natural_compare(a, b):
    ka = natural_sort_key_list(a)
    kb = natural_sort_key_list(b)
    if ka < kb: return -1
    if ka > kb: return 1
    return 0

def get_db():
    """Get a database connection from the pool"""
    try:
        conn = _connection_pool.get_nowait()
        # Verify connection is still valid
        try:
            conn.execute("SELECT 1")
            return conn
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            # Connection closed or invalid, create new one below
            pass
    except:
        # Pool empty, create new connection below
        pass

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    print(f"DEBUG: Connecting to database at {DB_PATH}")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.create_collation("NATSORT", natural_compare)
    # Enable performance settings
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn

def return_db(conn):
    """Return connection to pool"""
    if conn is None:
        return
    try:
        _connection_pool.put_nowait(conn)
    except:
        # Pool full, close connection
        try:
            conn.close()
        except:
            pass

def init_db():
    print("DEBUG: Starting database initialization...")
    conn = get_db()
    try:
        c = conn.cursor()
        print("DEBUG: Creating tables...")
        c.execute('''
            CREATE TABLE IF NOT EXISTS progress (
                user_id INTEGER,
                path TEXT,
                current_time REAL,
                duration REAL,
                play_count INTEGER DEFAULT 0,
                last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, path)
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password_hash TEXT,
                is_admin INTEGER DEFAULT 0,
                must_change_password INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                name TEXT,
                avatar TEXT,
                preferences TEXT, -- JSON
                parental_controls INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
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
                genre TEXT,
                year TEXT,
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
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Migrations for existing tables
        try:
            c.execute("ALTER TABLE progress ADD COLUMN play_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
        
        try:
            c.execute("ALTER TABLE library_index ADD COLUMN genre TEXT")
        except sqlite3.OperationalError: pass
        
        try:
            c.execute("ALTER TABLE library_index ADD COLUMN year TEXT")
        except sqlite3.OperationalError: pass

        try:
            c.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER")
        except sqlite3.OperationalError: pass

        try:
            c.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass

        try:
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_user_id ON profiles(user_id)")
        except sqlite3.OperationalError: pass

        # Add indexes for performance
        c.execute("CREATE INDEX IF NOT EXISTS idx_library_category ON library_index(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_library_path ON library_index(path)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_library_folder ON library_index(folder)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_library_mtime ON library_index(mtime)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_progress_path ON progress(path)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_metadata_path ON file_metadata(path)")

        conn.commit()
    finally:
        return_db(conn)

def set_setting(key: str, value: str):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
        ''', (key, value))
        conn.commit()
    finally:
        return_db(conn)

def get_setting(key: str) -> Optional[str]:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT value FROM settings WHERE key = ?', (key,))
        row = c.fetchone()
        if row:
            return row['value']
        return None
    finally:
        return_db(conn)

def get_user_by_username(username: str) -> Optional[dict]:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE username = ?', (username.lower(),))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        return_db(conn)

def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        return_db(conn)

def create_user(username: str, password_hash: str, is_admin: bool = False, must_change_password: bool = False) -> int:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO users (username, password_hash, is_admin, must_change_password)
            VALUES (?, ?, ?, ?)
        ''', (username.lower(), password_hash, 1 if is_admin else 0, 1 if must_change_password else 0))
        conn.commit()
        return c.lastrowid
    finally:
        return_db(conn)

def update_user_password(user_id: int, new_hash: str):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?', (new_hash, user_id))
        conn.commit()
    finally:
        return_db(conn)

def get_all_users() -> List[dict]:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT id, username, is_admin, created_at FROM users')
        return [dict(row) for row in c.fetchall()]
    finally:
        return_db(conn)

def delete_user(user_id: int):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM users WHERE id = ?', (user_id,))
        c.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))
        c.execute('DELETE FROM profiles WHERE user_id = ?', (user_id,))
        c.execute('DELETE FROM progress WHERE user_id = ?', (user_id,))
        conn.commit()
    finally:
        return_db(conn)

def update_user_role(user_id: int, is_admin: bool):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('UPDATE users SET is_admin = ? WHERE id = ?', (1 if is_admin else 0, user_id))
        conn.commit()
    finally:
        return_db(conn)

def get_profile(user_id: int) -> Optional[dict]:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM profiles WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        if row:
            data = dict(row)
            if data.get('preferences'):
                try:
                    data['preferences'] = json.loads(data['preferences'])
                except:
                    data['preferences'] = {}
            return data
        return None
    finally:
        return_db(conn)

def upsert_profile(user_id: int, name: str, avatar: str = None, preferences: dict = None, parental_controls: int = 0):
    conn = get_db()
    try:
        c = conn.cursor()
        prefs_json = json.dumps(preferences or {})
        c.execute('''
            INSERT INTO profiles (user_id, name, avatar, preferences, parental_controls)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                avatar = excluded.avatar,
                preferences = excluded.preferences,
                parental_controls = excluded.parental_controls
        ''', (user_id, name, avatar, prefs_json, parental_controls))
        conn.commit()
    finally:
        return_db(conn)

def update_progress(user_id: int, path: str, current_time: float, duration: float):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO progress (user_id, path, current_time, duration, last_played, play_count)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, 0)
            ON CONFLICT(user_id, path) DO UPDATE SET
                current_time = excluded.current_time,
                duration = excluded.duration,
                last_played = CURRENT_TIMESTAMP
        ''', (user_id, path, current_time, duration))
        conn.commit()
    finally:
        return_db(conn)

def increment_play_count(user_id: int, path: str):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''
            UPDATE progress SET play_count = play_count + 1 
            WHERE user_id = ? AND path = ?
        ''', (user_id, path))
        if c.rowcount == 0:
            c.execute('''
                INSERT INTO progress (user_id, path, current_time, duration, play_count, last_played)
                VALUES (?, ?, 0, 0, 1, CURRENT_TIMESTAMP)
            ''', (user_id, path))
        conn.commit()
    finally:
        return_db(conn)

def get_progress(user_id: int, path: str) -> Optional[dict]:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''
            SELECT current_time, duration, last_played 
            FROM progress 
            WHERE user_id = ? AND path = ?
        ''', (user_id, path))
        row = c.fetchone()
        if row:
            return dict(row)
        return None
    finally:
        return_db(conn)

def get_all_progress(user_id: int):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''
            SELECT path, current_time, duration, last_played 
            FROM progress 
            WHERE user_id = ?
        ''', (user_id,))
        rows = c.fetchall()
        return {row['path']: dict(row) for row in rows}
    finally:
        return_db(conn)

def get_file_metadata(path: str) -> Optional[dict]:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM file_metadata WHERE path = ?', (path,))
        row = c.fetchone()
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
    finally:
        return_db(conn)

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
    try:
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
    finally:
        return_db(conn)

def upsert_library_index_item(item: dict):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO library_index (path, category, name, folder, source, poster, mtime, size, genre, year, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(path) DO UPDATE SET
                category = excluded.category,
                name = excluded.name,
                folder = excluded.folder,
                source = excluded.source,
                poster = excluded.poster,
                mtime = excluded.mtime,
                size = excluded.size,
                genre = excluded.genre,
                year = excluded.year,
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
            item.get("genre"),
            item.get("year"),
        ))
        conn.commit()
    finally:
        return_db(conn)

def delete_library_index_item(path: str):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM library_index WHERE path = ?", (path,))
        c.execute("DELETE FROM file_metadata WHERE path = ?", (path,))
        c.execute("DELETE FROM progress WHERE path = ?", (path,))
        conn.commit()
    finally:
        return_db(conn)

def delete_library_index_items_by_prefix(path_prefix: str):
    """Delete all items from library_index, file_metadata, and progress starting with path_prefix"""
    conn = get_db()
    try:
        c = conn.cursor()
        # Ensure prefix ends with / to only match sub-items
        if not path_prefix.endswith('/'):
            path_prefix += '/'
        
        pattern = path_prefix + '%'
        c.execute("DELETE FROM library_index WHERE path LIKE ?", (pattern,))
        c.execute("DELETE FROM file_metadata WHERE path LIKE ?", (pattern,))
        c.execute("DELETE FROM progress WHERE path LIKE ?", (pattern,))
        
        # Also delete the directory itself if it matches the prefix (without trailing slash)
        dir_path = path_prefix.rstrip('/')
        c.execute("DELETE FROM library_index WHERE path = ?", (dir_path,))
        c.execute("DELETE FROM file_metadata WHERE path = ?", (dir_path,))
        c.execute("DELETE FROM progress WHERE path = ?", (dir_path,))
        
        conn.commit()
    finally:
        return_db(conn)

def find_duplicate_files() -> List[dict]:
    """Find files with the same name and size across the entire library."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''
            SELECT name, size, category, GROUP_CONCAT(path, '|') as paths, COUNT(*) as count
            FROM library_index
            WHERE category NOT IN ('music', 'books') -- Skip small files that might have common names
            GROUP BY name, size
            HAVING count > 1
            ORDER BY count DESC
        ''')
        return [dict(row) for row in c.fetchall()]
    finally:
        return_db(conn)

def find_duplicate_metadata() -> List[dict]:
    """Find media items that represent the same content based on IMDb ID."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''
            SELECT imdb_id, title, media_type, GROUP_CONCAT(path, '|') as paths, COUNT(*) as count
            FROM file_metadata
            WHERE imdb_id IS NOT NULL AND imdb_id != 'N/A' AND imdb_id != ''
            GROUP BY imdb_id
            HAVING count > 1
            ORDER BY count DESC
        ''')
        return [dict(row) for row in c.fetchall()]
    finally:
        return_db(conn)

def fix_duplicate_files() -> List[str]:
    """
    Find duplicate files (same name and size) and return a list of paths to delete.
    Keeps the one with the shortest path (likely already organized).
    """
    dupes = find_duplicate_files()
    to_delete = []
    for d in dupes:
        paths = d["paths"].split("|")
        # Sort by path length and then alphabetically to be deterministic
        # Shorter paths (like /data/movies/Title/Title.mkv) are preferred over 
        # longer/temporary ones (like /data/uploads/temp/Title.mkv)
        paths.sort(key=lambda x: (len(x), x))
        # Keep the first one, delete the rest
        to_delete.extend(paths[1:])
    return to_delete

def fix_duplicate_content() -> List[str]:
    """
    Find duplicate content (same IMDb ID) and return a list of paths to delete.
    Keeps the one with the shortest path.
    """
    dupes = find_duplicate_metadata()
    to_delete = []
    for d in dupes:
        paths = d["paths"].split("|")
        paths.sort(key=lambda x: (len(x), x))
        to_delete.extend(paths[1:])
    return to_delete

def upsert_library_index_items(items: list):
    if not items:
        return
    conn = get_db()
    try:
        c = conn.cursor()
        c.executemany('''
            INSERT INTO library_index (path, category, name, folder, source, poster, mtime, size, genre, year, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(path) DO UPDATE SET
                category = excluded.category,
                name = excluded.name,
                folder = excluded.folder,
                source = excluded.source,
                poster = excluded.poster,
                mtime = excluded.mtime,
                size = excluded.size,
                genre = excluded.genre,
                year = excluded.year,
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
            it.get("genre"),
            it.get("year"),
        ) for it in items))
        conn.commit()
    finally:
        return_db(conn)

def clear_library_index_category(category: str):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM library_index WHERE category = ?', (category,))
        c.execute('DELETE FROM library_index_state WHERE category = ?', (category,))
        conn.commit()
    finally:
        return_db(conn)

def set_library_index_state(category: str, item_count: int):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''
            INSERT INTO library_index_state (category, scanned_at, item_count)
            VALUES (?, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(category) DO UPDATE SET
                scanned_at = CURRENT_TIMESTAMP,
                item_count = excluded.item_count
        ''', (category, int(item_count or 0)))
        conn.commit()
    finally:
        return_db(conn)

def get_similar_media(path: str, limit: int = 10) -> List[Dict]:
    """Find similar media items using lightweight SQL keyword matching."""
    conn = get_db()
    try:
        c = conn.cursor()
        
        # 1. Get the target item's info
        c.execute('''
            SELECT l.category, l.name, l.genre, l.year, m.genre as meta_genre 
            FROM library_index l
            LEFT JOIN file_metadata m ON l.path = m.path
            WHERE l.path = ?
        ''', (path,))
        target = c.fetchone()
        if not target:
            return []
            
        category = target['category']
        # Clean title for matching (remove year and extension)
        target_name = re.sub(r'\.\w+$', '', target['name'])
        target_name = re.sub(r'\(\d{4}\)', '', target_name).strip()
        
        # Get first genre
        genres = (target['meta_genre'] or target['genre'] or "").split(',')
        primary_genre = genres[0].strip() if genres else None
        
        # 2. Find similar items via SQL (much lighter than TF-IDF on Pi Zero)
        # Priority: Same primary genre AND similar title words
        query = '''
            SELECT l.path, l.name, l.poster, l.genre, l.year
            FROM library_index l
            LEFT JOIN file_metadata m ON l.path = m.path
            WHERE l.category = ? AND l.path != ?
            ORDER BY 
                (CASE WHEN l.genre LIKE ? THEN 5 ELSE 0 END) + 
                (CASE WHEN l.name LIKE ? THEN 3 ELSE 0 END) DESC
            LIMIT ?
        '''
        
        genre_param = f"%{primary_genre}%" if primary_genre else "%"
        # Take first word of title for simple matching
        title_word = target_name.split(' ')[0] if ' ' in target_name else target_name
        title_param = f"%{title_word}%"
        
        c.execute(query, (category, path, genre_param, title_param, limit))
        return [dict(r) for r in c.fetchall()]
    finally:
        return_db(conn)

def get_library_index_state(category: str) -> Optional[dict]:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT category, scanned_at, item_count FROM library_index_state WHERE category = ?', (category,))
        row = c.fetchone()
        return dict(row) if row else None
    finally:
        return_db(conn)

def get_unique_genres(category: str) -> List[str]:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT DISTINCT genre FROM library_index WHERE category = ? AND genre IS NOT NULL', (category,))
        rows = c.fetchall()
        genres = set()
        for r in rows:
            if r['genre']:
                # Genres are often comma separated: "Action, Adventure"
                parts = [p.strip() for p in r['genre'].split(',')]
                genres.update(parts)
        return sorted(list(genres))
    finally:
        return_db(conn)

def get_unique_years(category: str) -> List[str]:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT DISTINCT year FROM library_index WHERE category = ? AND year IS NOT NULL ORDER BY year DESC', (category,))
        return [r['year'] for r in c.fetchall() if r['year']]
    finally:
        return_db(conn)

def query_library_index(category: str, q: str = None, offset: int = 0, limit: int = 50, sort: str = 'name', genre: str = None, year: str = None, user_id: int = None):
    # Validation
    allowed_sorts = ['name', 'newest', 'oldest', 'year_desc', 'year_asc', 'recently_played', 'top_watched']
    if sort not in allowed_sorts:
        sort = 'name'

    # Handle FastAPI Query objects if passed directly in tests
    if hasattr(q, 'default'): q = q.default
    if hasattr(genre, 'default'): genre = genre.default
    if hasattr(year, 'default'): year = year.default
    if hasattr(sort, 'default'): sort = sort.default
    if hasattr(offset, 'default'): offset = offset.default
    if hasattr(limit, 'default'): limit = limit.default

    q = (str(q) if q is not None and not hasattr(q, 'default') else "").strip().lower()
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 50), 200))

    conn = get_db()
    try:
        c = conn.cursor()
        
        # Base query joins with progress for sorting by last_played or play_count
        # Base query joins with progress for sorting by last_played or play_count
        # We always join or simulate progress to keep sorting logic consistent
        if user_id is not None:
            sql = '''
                SELECT l.*, p.current_time, p.duration, p.play_count, p.last_played
                FROM library_index l
                LEFT JOIN progress p ON l.path = p.path AND p.user_id = ?
                WHERE l.category = ?
            '''
            params = [user_id, category]
        else:
            sql = '''
                SELECT l.*, p.current_time, p.duration, p.play_count, p.last_played
                FROM library_index l
                LEFT JOIN (SELECT NULL as path, NULL as current_time, NULL as duration, 0 as play_count, NULL as last_played) p ON 1=0
                WHERE l.category = ?
            '''
            params = [category]
        
        if q:
            # Sanitize query to prevent SQL injection
            safe_q = sanitize_like_pattern(q)
            sql += ' AND (LOWER(l.name) LIKE ? ESCAPE "\\" OR LOWER(l.folder) LIKE ? ESCAPE "\\")'
            params.extend([f"%{safe_q}%", f"%{safe_q}%"])
        
        if genre:
            # Sanitize genre to prevent SQL injection
            safe_genre = sanitize_like_pattern(genre)
            sql += ' AND l.genre LIKE ? ESCAPE "\\"'
            params.append(f"%{safe_genre}%")
            
        if year:
            # Validate year is numeric to prevent injection
            if year.isdigit():
                sql += ' AND l.year = ?'
                params.append(year)
            else:
                # Invalid year parameter - skip it
                pass
            
        # Sorting
        if sort == 'name':
            sql += ' ORDER BY l.name COLLATE NATSORT'
        elif sort == 'newest':
            sql += ' ORDER BY l.mtime DESC'
        elif sort == 'oldest':
            sql += ' ORDER BY l.mtime ASC'
        elif sort == 'year_desc':
            sql += ' ORDER BY l.year DESC, l.name COLLATE NATSORT'
        elif sort == 'year_asc':
            sql += ' ORDER BY l.year ASC, l.name COLLATE NATSORT'
        elif sort == 'recently_played':
            sql += ' ORDER BY p.last_played DESC'
        elif sort == 'top_watched':
            sql += ' ORDER BY p.play_count DESC, l.name COLLATE NATSORT'
        else:
            # Default sort
            if category == 'movies':
                sql += ' ORDER BY l.name COLLATE NATSORT'
            else:
                sql += ' ORDER BY l.folder COLLATE NATSORT, l.name COLLATE NATSORT'
                
        sql += ' LIMIT ? OFFSET ?'
        params.extend([limit, offset])
        
        c.execute(sql, params)
        rows = c.fetchall()

        # Get total count for pagination (reuse filter logic)
        count_sql = 'SELECT COUNT(1) AS cnt FROM library_index l WHERE l.category = ?'
        count_params = [category]
        if q:
            safe_q = sanitize_like_pattern(q)
            count_sql += ' AND (LOWER(l.name) LIKE ? ESCAPE "\\" OR LOWER(l.folder) LIKE ? ESCAPE "\\")'
            count_params.extend([f"%{safe_q}%", f"%{safe_q}%"])
        if genre:
            safe_genre = sanitize_like_pattern(genre)
            count_sql += ' AND l.genre LIKE ? ESCAPE "\\"'
            count_params.append(f"%{safe_genre}%")
        if year:
            if year.isdigit():
                count_sql += ' AND l.year = ?'
                count_params.append(year)
            
        c.execute(count_sql, count_params)
        total = int(c.fetchone()["cnt"])

        return [dict(r) for r in rows], total
    finally:
        return_db(conn)

def query_shows(q: str = None, offset: int = 0, limit: int = 50, sort: str = 'name', genre: str = None, year: str = None, user_id: int = None):
    # Handle FastAPI Query objects if passed directly in tests
    if hasattr(q, 'default'): q = q.default
    if hasattr(genre, 'default'): genre = genre.default
    if hasattr(year, 'default'): year = year.default
    if hasattr(sort, 'default'): sort = sort.default
    if hasattr(offset, 'default'): offset = offset.default
    if hasattr(limit, 'default'): limit = limit.default

    # Validation
    allowed_sorts = ['name', 'newest', 'top_watched', 'recently_played']
    if sort not in allowed_sorts:
        sort = 'name'

    conn = get_db()
    try:
        c = conn.cursor()
        
        # Subquery to extract show name and include relevant columns
        if user_id is not None:
            sql_base = '''
                FROM (
                    SELECT 
                        CASE 
                            WHEN INSTR(folder, '/') > 0 THEN SUBSTR(folder, 1, INSTR(folder, '/') - 1)
                            WHEN folder LIKE '% Season %' THEN TRIM(SUBSTR(folder, 1, INSTR(UPPER(folder), ' SEASON ') - 1))
                            ELSE folder 
                        END as show_name,
                        folder, path, poster, mtime, genre, year
                    FROM library_index
                    WHERE category = 'shows'
                ) l
                LEFT JOIN progress p ON l.path = p.path AND p.user_id = ?
            '''
            params = [user_id]
        else:
            sql_base = '''
                FROM (
                    SELECT 
                        CASE 
                            WHEN INSTR(folder, '/') > 0 THEN SUBSTR(folder, 1, INSTR(folder, '/') - 1)
                            WHEN folder LIKE '% Season %' THEN TRIM(SUBSTR(folder, 1, INSTR(UPPER(folder), ' SEASON ') - 1))
                            ELSE folder 
                        END as show_name,
                        folder, path, poster, mtime, genre, year
                    FROM library_index
                    WHERE category = 'shows'
                ) l
                LEFT JOIN (SELECT NULL as path, NULL as last_played, 0 as play_count) p ON 1=0
            '''
            params = []
        
        where_clauses = []
        
        if q:
            safe_q = sanitize_like_pattern(q)
            where_clauses.append('l.show_name LIKE ? ESCAPE "\\"')
            params.append(f"%{safe_q}%")
        
        if genre:
            safe_genre = sanitize_like_pattern(genre)
            where_clauses.append('l.genre LIKE ? ESCAPE "\\"')
            params.append(f"%{safe_genre}%")
            
        if year:
            if year.isdigit():
                where_clauses.append('l.year = ?')
                params.append(year)
            
        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)
            
        # Grouping query
        group_sql = f'''
            SELECT 
                show_name as name,
                MAX(l.poster) as poster,
                MAX(l.mtime) as mtime,
                MAX(p.last_played) as last_played,
                COUNT(*) as episode_count,
                SUM(COALESCE(p.play_count, 0)) as total_plays,
                GROUP_CONCAT(DISTINCT l.genre) as genres,
                MIN(l.year) as year
            {sql_base}
            {where_sql}
            GROUP BY show_name
        '''
        
        # Get total count for pagination
        count_sql = f"SELECT COUNT(DISTINCT show_name) {sql_base} {where_sql}"
        c.execute(count_sql, params)
        total = c.fetchone()[0]
        
        # Sorting
        order_by = "name COLLATE NATSORT ASC"
        if sort == 'newest':
            order_by = "mtime DESC"
        elif sort == 'top_watched':
            order_by = "total_plays DESC, episode_count DESC"
        elif sort == 'recently_played':
            order_by = "last_played DESC"
            
        final_sql = f"{group_sql} ORDER BY {order_by} LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        c.execute(final_sql, params)
        rows = c.fetchall()
        
        items = []
        for r in rows:
            item = dict(r)
            # Clean up genres
            if item.get('genres'):
                gs = set()
                for g_str in item['genres'].split(','):
                    gs.update([p.strip() for p in g_str.split(',')])
                item['genres'] = sorted(list(gs))
            items.append(item)
            
        return items, total
    finally:
        return_db(conn)

def rename_media_path(old_path: str, new_path: str, is_dir: bool = False):
    if not old_path or not new_path or old_path == new_path:
        return
    
    conn = get_db()
    try:
        c = conn.cursor()
        
        if is_dir:
            # Update directory path and all children
            # format: /data/category/folder/...
            c.execute('UPDATE progress SET path = ? || SUBSTR(path, ?) WHERE path LIKE ? || "/%"', (new_path, len(old_path) + 1, old_path))
            c.execute('UPDATE file_metadata SET path = ? || SUBSTR(path, ?) WHERE path LIKE ? || "/%"', (new_path, len(old_path) + 1, old_path))
            
            # For library_index, we need to update 'path' and 'folder' columns
            # First, find the category and old folder prefix
            # old_path looks like /data/category/old_folder_prefix
            path_parts = old_path.split('/')
            if len(path_parts) >= 3:
                category = path_parts[2]
                # old_folder is relative to /data/category/
                old_folder_prefix = "/".join(path_parts[3:])
                
                new_path_parts = new_path.split('/')
                new_folder_prefix = "/".join(new_path_parts[3:])
                
                if old_folder_prefix:
                    # Update folder column for children
                    # If folder was 'ShowName/Season 1' and we rename 'ShowName' to 'NewShowName'
                    # folder should become 'NewShowName/Season 1'
                    c.execute('''
                        UPDATE library_index 
                        SET folder = ? || SUBSTR(folder, ?) 
                        WHERE category = ? AND (folder = ? OR folder LIKE ? || "/%")
                    ''', (new_folder_prefix, len(old_folder_prefix) + 1, category, old_folder_prefix, old_folder_prefix))
                    
                    # Update name if the directory itself is indexed (rare but possible)
                    c.execute('UPDATE library_index SET name = ? WHERE path = ?', (new_path_parts[-1], old_path))

            c.execute('UPDATE library_index SET path = ? || SUBSTR(path, ?) WHERE path LIKE ? || "/%"', (new_path, len(old_path) + 1, old_path))
            
            # Also update the directory itself if it exists in the index
            c.execute('UPDATE library_index SET path = ? WHERE path = ?', (new_path, old_path))
        else:
            # Single file rename
            parts = new_path.split('/')
            new_name = parts[-1] if parts else ""
            new_folder = "."
            if len(parts) > 3:
                new_folder = "/".join(parts[3:-1])
            if not new_folder:
                new_folder = "."

            c.execute('UPDATE progress SET path = ? WHERE path = ?', (new_path, old_path))
            c.execute('UPDATE file_metadata SET path = ? WHERE path = ?', (new_path, old_path))
            c.execute('UPDATE library_index SET path = ?, name = ?, folder = ? WHERE path = ?', (new_path, new_name, new_folder, old_path))
        
        conn.commit()
    finally:
        return_db(conn)

SESSION_MAX_AGE_DAYS = int(os.environ.get("SESSION_MAX_AGE_DAYS", 30))

def create_session(token: str, user_id: int):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('INSERT INTO sessions (token, user_id) VALUES (?, ?)', (token, user_id))
        conn.commit()
    finally:
        return_db(conn)

def get_session(token: str) -> Optional[dict]:
    conn = get_db()
    try:
        c = conn.cursor()
        # Only return session if it hasn't expired
        c.execute('''
            SELECT token, user_id, created_at 
            FROM sessions 
            WHERE token = ? AND created_at >= datetime('now', '-' || ? || ' days')
        ''', (token, SESSION_MAX_AGE_DAYS))
        row = c.fetchone()
        
        if not row:
            return None
            
        return dict(row)
    finally:
        return_db(conn)

def delete_session(token: str):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('DELETE FROM sessions WHERE token = ?', (token,))
        conn.commit()
    finally:
        return_db(conn)

def cleanup_sessions():
    """Remove sessions older than the configured max_age."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('''
            DELETE FROM sessions 
            WHERE created_at < datetime('now', '-' || ? || ' days')
        ''', (SESSION_MAX_AGE_DAYS,))
        conn.commit()
    except Exception as e:
        print(f"Error cleaning up sessions: {e}")
    finally:
        return_db(conn)
