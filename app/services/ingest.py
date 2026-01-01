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
    def on_created(self, event):
        if event.is_directory:
            return
        self.handle_file(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        self.handle_file(event.dest_path)

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
            if ext not in ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.wmv', '.flv', '.3gp', '.mpg', '.mpeg']:
                return # Ignore non-video files

            # Wait for file to be ready (size stability check)
            if not self.wait_for_file_ready(file_path):
                logger.warning(f"File {filename} not ready or removed.")
                return

            # Logic:
            # 1. Try to parse as Show (SxxExx)
            # 2. If not, assume Movie
            
            is_show = False
            # Use public media wrappers
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
                
                # Update DB
                try:
                    # Construct web path
                    rel_path = os.path.relpath(dest_abs, media.BASE_DIR).replace(os.sep, '/')
                    web_path = f"/data/{rel_path}"
                    folder = os.path.dirname(rel_path)
                    
                    st = os.stat(dest_abs)
                    item = {
                        "path": web_path,
                        "category": category,
                        "name": os.path.basename(dest_abs),
                        "folder": folder,
                        "source": "local",
                        "poster": None,
                        "mtime": float(getattr(st, "st_mtime", 0.0) or 0.0),
                        "size": int(getattr(st, "st_size", 0) or 0),
                    }
                    media.database.upsert_library_index_item(item)
                except Exception as e:
                    logger.warning(f"Failed to update index for {filename}: {e}")
                
            except Exception:
                logger.exception(f"Failed to ingest {filename}")
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
        _observer.schedule(IngestHandler(), ingest_dir, recursive=False)
        _observer.start()
        logger.info(f"Ingest service started watching {ingest_dir}")

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

