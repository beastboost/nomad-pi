
import os
import sys

# Add current directory to path so we can import app
sys.path.append(os.getcwd())

from app import database
from app.routers import media

def test_queries():
    print("Testing database initialization...")
    database.init_db()
    
    categories = ['movies', 'shows', 'music']
    for cat in categories:
        print(f"\nTesting category: {cat}")
        try:
            # Test direct database query
            if cat == 'shows':
                items, total = database.query_shows(limit=5)
            else:
                items, total = database.query_library_index(cat, limit=5)
            print(f"  Database query successful. Total: {total}, Items returned: {len(items)}")
            
            # Test media router function
            res = media.get_library(cat, limit=5)
            print(f"  Media router get_library successful. Source: {res.get('source')}, Items: {len(res.get('items'))}")
            
        except Exception as e:
            print(f"  ERROR in {cat}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    # Mock BASE_DIR if needed
    if not os.path.exists("data"):
        os.makedirs("data")
    test_queries()
