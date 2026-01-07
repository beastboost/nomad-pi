import sqlite3
import os

DB_PATH = "data/nomad.db"

def migrate():
    if not os.path.exists(DB_PATH):
        print("Database does not exist.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("Starting migration...")

    # 1. Fix 'progress' table
    c.execute("PRAGMA table_info(progress)")
    columns = [r[1] for r in c.fetchall()]
    if 'user_id' not in columns:
        print("Adding user_id to progress table...")
        # Since it's a primary key change, we need to recreate the table
        c.execute("ALTER TABLE progress RENAME TO progress_old")
        c.execute('''
            CREATE TABLE progress (
                user_id INTEGER,
                path TEXT,
                current_time REAL,
                duration REAL,
                play_count INTEGER DEFAULT 0,
                last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, path)
            )
        ''')
        # Copy data, assuming user_id 1 for existing global progress
        c.execute('''
            INSERT INTO progress (user_id, path, current_time, duration, play_count, last_played)
            SELECT 1, path, current_time, duration, play_count, last_played FROM progress_old
        ''')
        c.execute("DROP TABLE progress_old")
        print("Progress table migrated.")

    # 2. Fix 'library_index' table
    c.execute("PRAGMA table_info(library_index)")
    columns = [r[1] for r in c.fetchall()]
    if 'omdb' not in columns:
        print("Adding omdb to library_index table...")
        c.execute("ALTER TABLE library_index ADD COLUMN omdb TEXT")
        print("Library_index table migrated.")

    # 3. Fix 'users' table (just in case)
    c.execute("PRAGMA table_info(users)")
    columns = [r[1] for r in c.fetchall()]
    if 'is_admin' not in columns:
        print("Adding is_admin to users table...")
        c.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    if 'must_change_password' not in columns:
        print("Adding must_change_password to users table...")
        c.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")

    # 4. Fix 'profiles' table
    c.execute("PRAGMA table_info(profiles)")
    columns = [r[1] for r in c.fetchall()]
    if 'user_id' not in columns:
         # Recreate if it's completely wrong
         print("Fixing profiles table...")
         c.execute("DROP TABLE IF EXISTS profiles")
         c.execute('''
            CREATE TABLE profiles (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                avatar TEXT,
                preferences TEXT,
                parental_controls INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
    
    conn.commit()
    conn.close()
    print("Migration completed.")

if __name__ == "__main__":
    migrate()
