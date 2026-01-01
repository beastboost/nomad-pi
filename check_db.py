import sqlite3
import os

db_path = "c:\\Users\\conne\\Documents\\trae_projects\\media server\\data\\nomad.db"
if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
else:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    print("\n--- Settings ---")
    try:
        c.execute("SELECT * FROM settings")
        rows = c.fetchall()
        for r in rows:
            print(dict(r))
    except Exception as e:
        print(f"Error reading settings: {e}")

    print("\n--- library_index (first 20) ---")
    c.execute("SELECT category, folder, name, path, poster FROM library_index LIMIT 20")
    for row in c.fetchall():
        print(f"[{row['category']}] {row['folder']} -> {row['name']} ({row['path']}) | Poster: {row['poster']}")

    print("\n--- category counts ---")
    c.execute("SELECT category, COUNT(*) as cnt FROM library_index GROUP BY category")
    for row in c.fetchall():
        print(f"{row['category']}: {row['cnt']}")
    conn.close()
