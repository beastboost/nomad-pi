import requests
import os

# Assuming the server is running on localhost:8000
BASE_URL = "http://localhost:8000"

def test_poster():
    # 1. Login to get session cookie
    login_url = f"{BASE_URL}/auth/login"
    # We need the admin password hash from the database to know what password to use, 
    # but let's assume it's "admin" for now or check the database.
    # From check_db.py output, we have the hash. 
    # Let's try to find the password or just bypass auth by checking the file directly.
    
    # Actually, I'll just check if the file exists and the middleware logic.
    poster_path = "data/media/movies/poster.jpg"
    print(f"Checking if poster exists on disk: {poster_path}")
    if os.path.exists(poster_path):
        print("Poster exists on disk.")
    else:
        print("Poster NOT found on disk.")

    # Check the API response for movies
    # We need a token for this. 
    # Since I can't easily login without knowing the password, I'll just check the database entry for the poster.
    from app.database import get_db
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT path, poster FROM library_index WHERE category = 'movies'")
    rows = c.fetchall()
    for r in rows:
        print(f"Movie: {r['path']}, Poster: {r['poster']}")
    conn.close()

if __name__ == "__main__":
    test_poster()
