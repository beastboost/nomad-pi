import sqlite3
import os

db_path = "data/nomad.db"
if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# List tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]
print(f"Tables: {tables}")

# Check library_index schema
if "library_index" in tables:
    cursor.execute("PRAGMA table_info(library_index)")
    schema = cursor.fetchall()
    print(f"library_index schema: {schema}")
    
    # Search in library_index
    cursor.execute("SELECT * FROM library_index WHERE name LIKE '%Big Mouth%' OR name LIKE '%Solar Opposites%'")
    results = cursor.fetchall()
    print(f"library_index results: {results}")

if "file_metadata" in tables:
    cursor.execute("PRAGMA table_info(file_metadata)")
    schema = cursor.fetchall()
    print(f"file_metadata schema: {schema}")
    
    # Search in file_metadata
    cursor.execute("SELECT * FROM file_metadata WHERE title LIKE '%Big Mouth%' OR title LIKE '%Solar Opposites%'")
    results = cursor.fetchall()
    print(f"file_metadata results: {results}")

conn.close()
