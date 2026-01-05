import os
import shutil
from app.routers.media import find_local_poster, BASE_DIR

def test_find_local_poster():
    test_dir = os.path.join(BASE_DIR, "test_posters")
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    os.makedirs(test_dir)

    # Test 1: Standard poster.jpg
    with open(os.path.join(test_dir, "poster.jpg"), "w") as f:
        f.write("fake image")
    
    poster = find_local_poster(test_dir)
    print(f"Test 1 (poster.jpg): {poster}")
    assert poster == "/data/test_posters/poster.jpg"

    # Test 2: Filename-specific poster
    video_file = "my_movie.mp4"
    poster_file = "my_movie.jpg"
    with open(os.path.join(test_dir, poster_file), "w") as f:
        f.write("fake image")
    
    poster = find_local_poster(test_dir, filename=video_file)
    print(f"Test 2 (my_movie.jpg): {poster}")
    assert poster == "/data/test_posters/my_movie.jpg"

    # Test 3: Filename-specific poster takes precedence over poster.jpg
    # (already have poster.jpg from Test 1)
    poster = find_local_poster(test_dir, filename=video_file)
    print(f"Test 3 (precedence): {poster}")
    assert poster == "/data/test_posters/my_movie.jpg"

    # Test 4: No filename-specific poster, falls back to poster.jpg
    poster = find_local_poster(test_dir, filename="other_movie.mp4")
    print(f"Test 4 (fallback): {poster}")
    assert poster == "/data/test_posters/poster.jpg"

    # Cleanup
    shutil.rmtree(test_dir)
    print("All poster lookup tests passed!")

if __name__ == "__main__":
    test_find_local_poster()
