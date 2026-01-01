from app.routers import media
media.build_library_index("movies")
media.build_library_index("shows")
print("Index rebuild complete.")