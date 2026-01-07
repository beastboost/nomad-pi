
import asyncio
import sys
import os

# Add the current directory to sys.path so we can import app modules
sys.path.append(os.getcwd())

async def test_shows_library_api():
    from app.routers import media
    from app import database
    
    # Mocking user_id=1 as the current user
    user_id = 1
    print(f"Testing get_shows_library for user_id={user_id}")
    
    # Call the router function directly
    result = media.get_shows_library(user_id=user_id)
    
    shows = result.get("shows", [])
    print(f"Total shows in library: {len(shows)}")
    for show in shows:
        seasons = show.get("seasons", [])
        total_episodes = sum(len(s.get("episodes", [])) for s in seasons)
        print(f"- {show['name']}: {len(seasons)} seasons, {total_episodes} total episodes")
        for season in seasons:
            print(f"  - {season['name']}: {len(season.get('episodes', []))} episodes")

if __name__ == "__main__":
    asyncio.run(test_shows_library_api())
