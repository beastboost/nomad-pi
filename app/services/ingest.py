import os
import time
import shutil
import logging
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from app.routers import media

# Use app-wide logger
logger = logging.getLogger("ingest")

_observer = None
_observer_lock = threading.Lock()
_active_workers = set()
_workers_lock = threading.Lock()
_stop_event = threading.Event()

class IngestHandler(FileSystemEventHandler):
    def __init__(self, is_direct=False):
        self.is_direct = is_direct

    def on_created(self, event):
        if event.is_directory:
            return
        self.handle_file(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        self.handle_file(event.dest_path)

    def on_deleted(self, event):
        if event.is_directory:
            # Handle directory deletion - remove all items in this folder from index
            try:
                rel_path = os.path.relpath(event.src_path, media.BASE_DIR).replace(os.sep, '/')
                web_path_prefix = f"/data/{rel_path}/"
                media.database.delete_library_index_items_by_prefix(web_path_prefix)
                logger.info(f"Removed items from index for deleted directory: {rel_path}")
            except Exception as e:
                logger.warning(f"Failed to handle directory deletion {event.src_path}: {e}")
            return
        
        # Handle file deletion
        try:
            rel_path = os.path.relpath(event.src_path, media.BASE_DIR).replace(os.sep, '/')
            web_path = f"/data/{rel_path}"
            media.database.delete_library_index_item(web_path)
            logger.info(f"Removed file from index: {web_path}")
        except Exception as e:
            logger.warning(f"Failed to handle file deletion {event.src_path}: {e}")

    def handle_file(self, file_path):
        if _stop_event.is_set():
            return
        # Track worker threads to join them on shutdown
        t = threading.Thread(target=self.process, args=(file_path,))
        with _workers_lock:
            _active_workers.add(t)
        t.start()

    def process(self, file_path):
        try:
            filename = os.path.basename(file_path)
            if filename.startswith("."):
                return

            # Check extensions
            ext = os.path.splitext(filename)[1].lower()
            allowed_video = ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.wmv', '.flv', '.3gp', '.mpg', '.mpeg']
            allowed_music = ['.mp3', '.flac', '.wav', '.m4a']
            allowed_books = ['.pdf', '.epub', '.mobi', '.cbz', '.cbr']
            
            all_allowed = allowed_video + allowed_music + allowed_books
            if ext not in all_allowed:
                return 

            # Wait for file to be ready (size stability check)
            if not self.wait_for_file_ready(file_path):
                logger.warning(f"File {filename} not ready or removed.")
                return

            if not self.is_direct:
                # Logic for ingest folder:
                # 1. Try to parse as Show (SxxExx)
                # 2. If not, assume Movie
                is_show = False
                s, e = media.parse_season_episode(filename)
                if s is not None:
                    is_show = True
                elif media.parse_episode_only(filename) is not None:
                    is_show = True
                
                category = "shows" if is_show else "movies"
                
                try:
                    # Calculate destination
                    dest_rel = media.auto_dest_rel(category, filename)
                    dest_abs = os.path.join(media.BASE_DIR, category, dest_rel)
                    
                    # Ensure unique destination
                    dest_abs = media.pick_unique_dest(dest_abs)
                    
                    # Ensure destination directory exists
                    os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
                    
                    # Move file
                    shutil.move(file_path, dest_abs)
                    logger.info(f"Ingested {filename} -> {dest_abs}")
                    target_abs = dest_abs
                except Exception:
                    logger.exception(f"Failed to ingest {filename}")
                    return
            else:
                # For direct uploads, we just need to determine the category based on the path
                target_abs = file_path
                category = "movies"
                if "shows" in file_path.lower():
                    category = "shows"
                elif "music" in file_path.lower():
                    category = "music"
                elif "books" in file_path.lower():
                    category = "books"

            # Update DB for the final file location
            try:
                # Construct web path
                rel_path = os.path.relpath(target_abs, media.BASE_DIR).replace(os.sep, '/')
                web_path = f"/data/{rel_path}"
                
                # For movies/shows, the folder is relative to the category root
                try:
                    cat_root = os.path.join(media.BASE_DIR, category)
                    folder = os.path.relpath(os.path.dirname(target_abs), cat_root).replace(os.sep, '/')
                except:
                    folder = "."
                
                st = os.stat(target_abs)
                item = {
                    "path": web_path,
                    "category": category,
                    "name": os.path.basename(target_abs),
                    "folder": folder,
                    "source": "local",
                    "poster": None,
                    "mtime": float(getattr(st, "st_mtime", 0.0) or 0.0),
                    "size": int(getattr(st, "st_size", 0) or 0),
                }
                media.database.upsert_library_index_item(item)
                logger.info(f"Indexed {category} file: {web_path}")
            except Exception as e:
                logger.warning(f"Failed to update index for {filename}: {e}")
        finally:
            with _workers_lock:
                if threading.current_thread() in _active_workers:
                    _active_workers.remove(threading.current_thread())

    def wait_for_file_ready(self, file_path, timeout=60):
        """Wait until file size is stable for 5 seconds."""
        start_time = time.time()
        last_size = -1
        stable_count = 0
        
        while time.time() - start_time < timeout and not _stop_event.is_set():
            try:
                if not os.path.exists(file_path):
                    return False
                
                size = os.path.getsize(file_path)
                if size == last_size:
                    stable_count += 1
                else:
                    stable_count = 0
                
                last_size = size
                
                if stable_count >= 5: # 5 seconds of stability
                    return True
                
                time.sleep(1)
            except Exception:
                return False
        return False

def start_ingest_service():
    global _observer
    with _observer_lock:
        if _observer:
            return

        ingest_dir = os.path.join(media.BASE_DIR, "ingest")
        os.makedirs(ingest_dir, exist_ok=True)
        
        _stop_event.clear()
        _observer = Observer()
        
        # 1. Watch ingest folder for moving/auto-sorting
        _observer.schedule(IngestHandler(is_direct=False), ingest_dir, recursive=False)
        
        # 2. Watch direct upload folders for immediate indexing
        # We now use recursive=True to detect files in subfolders (e.g. Movie Name (Year)/movie.mkv)
        # 100,000 inotify watches are configured in setup.sh, which is plenty.
        watch_folders = ["movies", "shows", "music", "books"]
        for folder in watch_folders:
            folder_path = os.path.join(media.BASE_DIR, folder)
            os.makedirs(folder_path, exist_ok=True)
            _observer.schedule(IngestHandler(is_direct=True), folder_path, recursive=True)
            
        _observer.start()
        logger.info(f"Ingest service started watching {ingest_dir} and direct folders")

def stop_ingest_service():
    global _observer
    with _observer_lock:
        if _observer:
            _stop_event.set()
            _observer.stop()
            _observer.join()
            _observer = None
            logger.info("Ingest observer stopped.")

    # Wait for active workers to finish
    with _workers_lock:
        workers = list(_active_workers)
    
    if workers:
        logger.info(f"Waiting for {len(workers)} ingest workers to finish...")
        for t in workers:
            t.join(timeout=30)
        logger.info("All ingest workers finished.")

