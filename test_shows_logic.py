
import asyncio
import json

async def test_shows():
    # Let's just use the database directly to see what would be returned.
    from app import database
    items, total = database.query_library_index("shows", limit=1000000)
    print(f"Total items in DB: {total}")
    
    shows_dict = {}
    for r in items:
        folder = r.get("folder") or ""
        parts = folder.split('/')
        show_name = parts[0] if len(parts) >= 1 else "Unsorted"
        if show_name not in shows_dict:
            shows_dict[show_name] = True
    
    print(f"Shows found: {list(shows_dict.keys())}")

if __name__ == "__main__":
    asyncio.run(test_shows())
