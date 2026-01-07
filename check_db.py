
import sqlite3
import json

def check():
    conn = sqlite3.connect('data/nomad.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT folder, name FROM library_index WHERE category="shows"')
    rows = [dict(r) for r in c.fetchall()]
    print(json.dumps(rows, indent=2))

if __name__ == "__main__":
    check()
