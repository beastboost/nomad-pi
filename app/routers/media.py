from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Request, Query, BackgroundTasks
from fastapi.responses import FileResponse
from typing import List, Dict
import os
import posixpath
import platform
import re
import shutil
import zipfile
import hashlib
import subprocess
import json
import urllib.parse
import urllib.request
import logging
from datetime import datetime, timedelta
from collections import OrderedDict
from functools import lru_cache
from hashlib import md5
import threading
from app import database

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_DIR = os.path.abspath("data")
POSTER_CACHE_DIR = os.path.join(BASE_DIR, "cache", "posters")
os.makedirs(POSTER_CACHE_DIR, exist_ok=True)

@lru_cache(maxsize=100)
def _get_paged_data_cached(category: str, cache_key: str, q: str, offset: int, limit: int, sort: str, genre: str, year: str):
    """Internal cached version of paged data retrieval"""
    return _get_paged_data(category, q, offset, limit, sort, genre, year, False)

def _get_paged_data(category: str, q: str, offset: int, limit: int, sort: str, genre: str, year: str, rebuild: bool):
    idx_info = maybe_start_index_build(category, force=bool(rebuild))
    items, total = database.query_library_index(category, q, offset, limit, sort=sort, genre=genre, year=year)

    all_progress = database.get_all_progress()
    out = []
    for r in items:
        web_path = r.get("path")
        try:
            fs_path = safe_fs_path_from_web_path(web_path)
            if not os.path.isfile(fs_path):
                continue
        except Exception:
            continue
        item = {
            "name": r.get("name"),
            "path": web_path,
            "folder": r.get("folder") or ".",
            "type": category,
            "source": r.get("source") or "local",
        }
        if (category == "movies" or category == "shows") and r.get("poster"):
            item["poster"] = r.get("poster")
        if web_path in all_progress:
            item["progress"] = all_progress[web_path]
        out.append(item)

    if not out and int(offset or 0) == 0:
        out = scan_media_page(category, q, offset, limit)
        total = max(int(total or 0), int(offset or 0) + len(out))

    next_offset = int(offset or 0) + len(out)
    has_more = next_offset < int(total or 0)
    return {
        "items": out,
        "offset": int(offset or 0),
        "limit": int(limit or 0),
        "next_offset": next_offset,
        "total": int(total or 0),
        "has_more": has_more,
        "index": idx_info,
    }

def build_cache_key(category: str, q: str, offset: int, limit: int, 
                     sort: str, genre: str, year: str) -> str:
    """Build cache key for pagination"""
    params = f"{category}:{q}:{offset}:{limit}:{sort}:{genre}:{year}"
    return md5(params.encode()).hexdigest()

INDEX_TTL = timedelta(hours=12)
_index_lock = threading.Lock()
_index_building = {}

# Initialize DB on module load (or main startup)
database.init_db()

def get_scan_paths(category: str):
    paths = [os.path.join(BASE_DIR, category)]
    # Also check data/media/category
    media_cat_path = os.path.join(BASE_DIR, "media", category)
    if os.path.exists(media_cat_path):
        paths.append(media_cat_path)

    external_dir = os.path.join(BASE_DIR, "external")
    if os.path.exists(external_dir):
        try:
            # Check for actual mount points or subfolders in external
            for item in os.listdir(external_dir):
                drive_path = os.path.join(external_dir, item)
                if os.path.isdir(drive_path):
                    # Check for category folder (case insensitive-ish)
                    for cat_name in [category, category.capitalize(), category.upper()]:
                        cat_path = os.path.join(drive_path, cat_name)
                        if os.path.exists(cat_path):
                            paths.append(cat_path)
                            break
        except Exception:
            pass
            
    # Add auto-mounting logic for Linux (Pi)
    if platform.system() == "Linux":
        # Check /media/pi or /media/ (standard mount points)
        for mount_root in ["/media/pi", "/media"]:
            if os.path.exists(mount_root):
                try:
                    for drive in os.listdir(mount_root):
                        drive_path = os.path.join(mount_root, drive)
                        if os.path.ismount(drive_path) or os.path.isdir(drive_path):
                             # Ensure symlink in data/external exists for playback access
                             ext_root = os.path.join(BASE_DIR, "external")
                             os.makedirs(ext_root, exist_ok=True)
                             external_link = os.path.join(ext_root, drive)
                             
                             if not os.path.exists(external_link):
                                 try:
                                     os.symlink(drive_path, external_link)
                                     logger.info(f"Created symlink for USB drive: {drive_path} -> {external_link}")
                                 except Exception as e:
                                     logger.warning(f"Failed to create symlink for {drive_path}: {e}")
                             
                             # Use the symlinked path for consistency with web /data/ paths
                             base_to_use = external_link if os.path.exists(external_link) else drive_path

                             # Check for category folder
                             for cat_name in [category, category.capitalize(), category.upper()]:
                                cat_path = os.path.join(base_to_use, cat_name)
                                if os.path.exists(cat_path):
                                    if cat_path not in paths:
                                        paths.append(cat_path)
                                    break
                except Exception:
                    pass
    return paths

def safe_fs_path_from_web_path(web_path: str):
    # Allow Windows absolute paths
    if platform.system() == "Windows" and len(web_path) >= 2 and web_path[1] == ":":
        return os.path.abspath(web_path)

    # Allow Linux absolute paths to /media and /mnt if they exist
    if platform.system() == "Linux" and (web_path.startswith("/media") or web_path.startswith("/mnt")):
        abs_path = os.path.abspath(web_path)
        # Basic safety: ensure it's not trying to access system files
        if any(abs_path.startswith(p) for p in ["/media", "/mnt"]):
            return abs_path

    if not isinstance(web_path, str) or not web_path.startswith("/data/"):
        raise HTTPException(status_code=400, detail="Invalid path")

    rel = posixpath.normpath(web_path[len("/data/"):]).lstrip("/")
    if rel.startswith("..") or rel == ".":
        raise HTTPException(status_code=400, detail="Invalid path")

    base_abs = os.path.abspath(BASE_DIR)
    # Use os.path.join for constructing the file system path
    fs_path = os.path.abspath(os.path.join(base_abs, *rel.split('/')))
    if os.path.commonpath([base_abs, fs_path]) != base_abs:
        raise HTTPException(status_code=400, detail="Invalid path")
    return fs_path

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'([0-9]+)', s)]

def guess_title_year(name: str):
    # Remove extension
    s = os.path.splitext(os.path.basename(name or ""))[0]
    
    # 1. Truncate at common show markers if it looks like a TV show episode
    show_m = re.search(r"(?i)\bS(\d{1,3})\s*[\.\-_\s]*\s*E(\d{1,3})\b", s)
    if not show_m:
        show_m = re.search(r"(?i)\b(\d{1,3})x(\d{1,3})\b", s)
    if not show_m:
        show_m = re.search(r"(?i)\bseason\s*(\d{1,3})\s*[\.\-_\s]*\s*episode\s*(\d{1,3})\b", s)
    
    if show_m:
        s = s[:show_m.start()].strip()

    # 2. Aggressively remove common scene/rip tags FIRST to clean the string
    # This helps find the year if it's buried inside brackets
    tags = [
        r'480p', r'720p', r'1080p', r'2160p', r'4k', r'8k',
        r'hdr', r'hevc', r'h265', r'x265', r'h264', r'x264', r'avc',
        r'aac', r'ac3', r'dts', r'dd5 1', r'5 1', r'7 1',
        r'web[- ]dl', r'webrip', r'bluray', r'brrip', r'bdrip', r'dvdrip', r'remux', r'hdtv',
        r'yify', r'yts', r'rarbg', r'ettv', r'psa', r'tgx', r'qxr', r'utp', r'vxt',
        r'dual[- ]audio', r'multi[- ]audio', r'multi', r'hindi', r'english', r'subbed', r'subs',
        r'proper', r'repack', r'extended', r'director s cut', r'uncut', r'remastered',
        r'ctrlhd', r'dimension', r'lol', r'fleet', r'batv', r'asap', r'immerse', r'avs', r'evolve', r'publicHD'
    ]
    
    # Pre-clean dots/underscores/hyphens to spaces for tag matching
    s_clean = re.sub(r'[\._\-]+', ' ', s)
    for tag in tags:
        s_clean = re.sub(rf'\b{tag}\b', ' ', s_clean, flags=re.I)
    
    # 3. Extract year (4 digits starting with 19 or 20)
    # We look for a year that is preceded by a space or a bracket
    year = None
    # Enhanced year regex to handle double brackets like ((2010)) or ( (2010)
    m = re.search(r'(?:[\s\(\[])+(19\d{2}|20\d{2})(?:[\s\s\)\]])+', s_clean)
    if not m:
        # Fallback to any 4 digit year that looks like a year
        m = re.search(r'\b(19\d{2}|20\d{2})\b', s_clean)
        
    if m:
        year = m.group(1)
        # The title is everything before the year
        idx = s_clean.find(year)
        title = s_clean[:idx].strip()
        if not title:
            title = s_clean.replace(year, '').strip()
    else:
        title = s_clean
        
    # 4. Final cleanup of title (remove trailing brackets/dashes)
    # Clean up empty brackets first (often left by year extraction)
    title = re.sub(r'\(\s*\)|\s*\[\s*\]', ' ', title)
    title = re.sub(r'[\[\(].*?[\]\)]', ' ', title)
    # Special handling for hyphenated titles: don't replace hyphens if they are surrounded by letters
    # This preserves "Half-Blood" but cleans "Title - 1080p"
    title = re.sub(r'(?<!\w)-(?!\w)', ' ', title)
    title = re.sub(r'[\._]+', ' ', title)
    
    # Final trim of any remaining leading/trailing junk
    title = title.strip(' -_()[]')
    title = re.sub(r'\s+', ' ', title).strip()
    
    return title or s, year

def normalize_title(s: str):
    s = re.sub(r'[\._]+', ' ', str(s or ''))
    s = re.sub(r'[\W_]+', ' ', s, flags=re.UNICODE)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s

_poster_cache = OrderedDict()
_poster_cache_max = 2048

def find_local_poster(dir_path: str, filename: str = None):
    global _poster_cache
    if dir_path in _poster_cache and not filename:
        v = _poster_cache.pop(dir_path)
        _poster_cache[dir_path] = v
        return v
    
    candidates = ["poster.jpg", "poster.jpeg", "poster.png", "folder.jpg", "folder.png", "cover.jpg", "cover.png"]
    if filename:
        # Add {filename}.jpg and {filename}.png as candidates (used by NomadTransferTool for movies)
        base_name = os.path.splitext(filename)[0]
        candidates.insert(0, f"{base_name}.jpg")
        candidates.insert(1, f"{base_name}.png")

    v = None
    for name in candidates:
        p = os.path.join(dir_path, name)
        if os.path.isfile(p):
            try:
                rel_from_data = os.path.relpath(p, BASE_DIR).replace(os.sep, "/")
                v = f"/data/{rel_from_data}"
                break
            except Exception:
                continue
    
    # Only cache if we didn't use a specific filename (since filename-specific posters are not per-directory)
    if not filename:
        _poster_cache[dir_path] = v
        if len(_poster_cache) > _poster_cache_max:
            _poster_cache.popitem(last=False)
    return v

def infer_show_name(filename: str):
    # Try to extract show name from S01E01 style
    m = re.search(r'^(.*?)(?:\bS\d{1,3}\s*[\.\-_\s]*\s*E\d{1,3}\b|\b\d{1,3}x\d{1,3}\b)', filename, re.I)
    if m:
        name = m.group(1).replace('.', ' ').replace('_', ' ').strip()
        if name: return name
    return None

def omdb_fetch(title: str = None, year: str = None, imdb_id: str = None, media_type: str = None):
    api_key = os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="OMDb not configured")

    params = {"apikey": api_key, "plot": "short"}
    if imdb_id:
        params["i"] = imdb_id
    elif title:
        params["t"] = title
    else:
        raise HTTPException(status_code=400, detail="Missing title")

    if year:
        params["y"] = str(year)
    if media_type:
        params["type"] = media_type

    url = "https://www.omdbapi.com/?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = resp.read()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OMDb request failed: {e}")

    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        raise HTTPException(status_code=502, detail="Invalid OMDb response")

    if str(data.get("Response") or "").lower() == "false":
        raise HTTPException(status_code=404, detail=str(data.get("Error") or "Not found"))
    return data

def omdb_search(query: str, year: str = None, media_type: str = None):
    api_key = os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="OMDb not configured")

    params = {"apikey": api_key, "s": query}
    if year:
        params["y"] = str(year)
    if media_type:
        params["type"] = media_type
    url = "https://www.omdbapi.com/?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = resp.read()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OMDb request failed: {e}")

    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        raise HTTPException(status_code=502, detail="Invalid OMDb response")

    if str(data.get("Response") or "").lower() == "false":
        raise HTTPException(status_code=404, detail=str(data.get("Error") or "Not found"))
    return data

def cache_remote_poster(poster_url: str):
    if not poster_url or poster_url == "N/A":
        return None
    try:
        parsed = urllib.parse.urlparse(poster_url)
        if parsed.scheme not in ("http", "https"):
            return None
    except Exception:
        return None

    os.makedirs(POSTER_CACHE_DIR, exist_ok=True)
    key = hashlib.sha256(poster_url.encode("utf-8", errors="ignore")).hexdigest()
    out_fs = os.path.join(POSTER_CACHE_DIR, f"{key}.jpg")
    if os.path.isfile(out_fs) and os.path.getsize(out_fs) > 0:
        rel = os.path.relpath(out_fs, BASE_DIR).replace(os.sep, "/")
        return f"/data/{rel}"

    req = urllib.request.Request(poster_url, headers={"User-Agent": "NomadPi/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read(5_000_000)
    except Exception:
        return None

    if not data:
        return None
    try:
        with open(out_fs, "wb") as f:
            f.write(data)
    except Exception:
        return None

    rel = os.path.relpath(out_fs, BASE_DIR).replace(os.sep, "/")
    return f"/data/{rel}"

@router.get("/shows/library")
def get_shows_library():
    items, total = database.query_library_index("shows", limit=1000000)
    all_progress = database.get_all_progress()
    
    shows_dict = {}
    
    def parse_ep_num(name):
        # Try SxxExx or just Exx
        m = re.search(r"(?i)\bE(\d{1,3})\b", name)
        if m: return int(m.group(1))
        # Try 1x01
        m = re.search(r"(?i)\b\d+x(\d{1,3})\b", name)
        if m: return int(m.group(1))
        # Try just number
        m = re.search(r"(?i)\b(\d{1,3})\b", name)
        if m: return int(m.group(1))
        return 999

    for r in items:
        web_path = r.get("path")
        # Extract show and season from folder column: "ShowName/Season 1"
        folder = r.get("folder") or ""
        parts = folder.split('/')
        
        show_name = parts[0] if len(parts) >= 1 else "Unsorted"
        season_name = parts[1] if len(parts) >= 2 else "Season 1"
        
        # IMPROVEMENT: If show_name contains "Season X", try to split it
        # This handles folders like "Family Guy Season 14" instead of "Family Guy/Season 14"
        season_match = re.search(r"(?i)(.*)\s+Season\s+(\d+)", show_name)
        if season_match and len(parts) == 1:
            show_name = season_match.group(1).strip()
            season_name = f"Season {season_match.group(2)}"
        
        if show_name not in shows_dict:
            shows_dict[show_name] = {
                "name": show_name,
                "seasons": {},
                "poster": None,
                "path": os.path.join("/data/shows", show_name).replace(os.sep, '/')
            }
        
        if season_name not in shows_dict[show_name]["seasons"]:
            shows_dict[show_name]["seasons"][season_name] = {
                "name": season_name,
                "episodes": [],
                "poster": None,
                "path": os.path.join("/data/shows", show_name, season_name).replace(os.sep, '/')
            }
            
        ep = {
            "name": r.get("name"),
            "path": web_path,
            "poster": r.get("poster"),
            "progress": all_progress.get(web_path),
            "ep_num": parse_ep_num(r.get("name") or "")
        }

        # Aggregation: Use the first available poster for show/season if not set
        # Priority: Show-level poster.jpg, then Season-level poster.jpg, then first episode poster
        if r.get("poster"):
            # If it's a show-level poster (e.g. /data/shows/Show/poster.jpg)
            if r.get("poster").endswith("/poster.jpg") or r.get("poster").endswith("/poster.png"):
                poster_path = r.get("poster")
                if "/Season" not in poster_path:
                    shows_dict[show_name]["poster"] = poster_path
                else:
                    shows_dict[show_name]["seasons"][season_name]["poster"] = poster_path
            
            # Fallback for show poster
            if not shows_dict[show_name]["poster"]:
                shows_dict[show_name]["poster"] = r.get("poster")
            
            # Fallback for season poster
            if not shows_dict[show_name]["seasons"][season_name]["poster"]:
                shows_dict[show_name]["seasons"][season_name]["poster"] = r.get("poster")

        shows_dict[show_name]["seasons"][season_name]["episodes"].append(ep)
        
    # Convert to list structure
    out = []
    for s_name in sorted(shows_dict.keys(), key=database.natural_sort_key_list):
        show = shows_dict[s_name]
        seasons = []
        for sea_name in sorted(show["seasons"].keys(), key=database.natural_sort_key_list):
            season = show["seasons"][sea_name]
            # Sort episodes by episode number, then by natural name
            season["episodes"].sort(key=lambda x: (x["ep_num"], database.natural_sort_key_list(x["name"])))
            seasons.append(season)
        show["seasons"] = seasons
        out.append(show)
        
    return {"shows": out}

@router.get("/stats")
def get_media_stats():
    stats = {
        "movies": 0,
        "shows": 0,
        "music": 0,
        "books": 0
    }
    
    for category in stats.keys():
        try:
            # Check library index
            items, total = database.query_library_index(category, limit=1)
            stats[category] = total
        except Exception:
            # Fallback to file count if index doesn't exist
            count = 0
            paths = get_scan_paths(category)
            for p in paths:
                if os.path.exists(p):
                    for root, dirs, files in os.walk(p):
                        count += len([f for f in files if not f.startswith(".")])
            stats[category] = count
            
    return stats

@router.post("/rebuild")
def rebuild_library(background_tasks: BackgroundTasks):
    for category in ["movies", "shows", "music", "books"]:
        background_tasks.add_task(build_library_index, category)
    # Also trigger MiniDLNA rescan and auto-organization
    background_tasks.add_task(trigger_dlna_rescan)
    background_tasks.add_task(trigger_auto_organize)
    return {"status": "Library rebuild and organization started in background"}

def build_library_index(category: str):
    paths_to_scan = get_scan_paths(category)
    count = 0
    batch = []

    database.clear_library_index_category(category)

    allowed = None
    if category in ['movies', 'shows']:
        allowed = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.wmv', '.flv', '.3gp', '.mpg', '.mpeg'}
    elif category == 'music':
        allowed = {'.mp3', '.flac', '.wav', '.m4a'}
    elif category == 'books':
        allowed = {'.pdf', '.epub', '.mobi', '.cbz', '.cbr'}
    elif category == 'gallery':
        allowed = {'.jpg', '.jpeg', '.png', '.gif', '.mp4', '.mov'}

    for base in paths_to_scan:
        if not os.path.exists(base):
            continue
        for root, _, filenames in os.walk(base):
            for f in filenames:
                if f.startswith('.'):
                    continue
                ext = os.path.splitext(f)[1].lower()
                if allowed and ext not in allowed:
                    continue
                full_path = os.path.join(root, f)
                try:
                    st = os.stat(full_path)
                except Exception:
                    continue

                try:
                    rel_path = os.path.relpath(full_path, BASE_DIR)
                    url_path = rel_path.replace(os.sep, '/')
                    web_path = f"/data/{url_path}"
                except Exception:
                    continue

                try:
                    folder = os.path.relpath(root, base).replace(os.sep, '/')
                except Exception:
                    folder = "."

                # Poster lookup
                p_url = None
                if category == "movies":
                    p_url = find_local_poster(root, f)
                elif category == "shows":
                    # Priority 1: Episode-specific poster (if any)
                    p_url = find_local_poster(root, f)
                    if not p_url:
                        # Priority 2: Season-specific poster (poster.jpg in Season folder)
                        p_url = find_local_poster(root)
                    if not p_url:
                        # Priority 3: Show-level folder (poster.jpg in Show folder)
                        parent = os.path.dirname(root)
                        if parent != base and parent != BASE_DIR:
                            p_url = find_local_poster(parent)

                item = {
                    "path": web_path,
                    "category": category,
                    "name": f,
                    "folder": folder,
                    "source": "external" if "external" in rel_path else "local",
                    "poster": p_url,
                    "mtime": float(getattr(st, "st_mtime", 0.0) or 0.0),
                    "size": int(getattr(st, "st_size", 0) or 0),
                    "genre": None,
                    "year": None
                }
                
                # Try to get genre and year from cached metadata
                meta = database.get_file_metadata(web_path)
                if meta:
                    item["genre"] = meta.get("genre")
                    item["year"] = meta.get("year")
                
                batch.append(item)
                if len(batch) >= 500:
                    database.upsert_library_index_items(batch)
                    batch = []
                count += 1

    if batch:
        database.upsert_library_index_items(batch)
    database.set_library_index_state(category, count)

def maybe_start_index_build(category: str, force: bool = False):
    state = database.get_library_index_state(category)
    fresh = False
    if state and not force:
        scanned_at = state.get("scanned_at")
        if isinstance(scanned_at, str) and scanned_at:
            try:
                ts = datetime.fromisoformat(scanned_at)
                fresh = (datetime.now() - ts) < INDEX_TTL
            except Exception:
                fresh = False

    if fresh and not force:
        return {"building": False, "fresh": True, "state": state}

    with _index_lock:
        if _index_building.get(category):
            return {"building": True, "fresh": False, "state": state}
        _index_building[category] = True

    def run():
        try:
            build_library_index(category)
            # After indexing, if it's shows or movies, try to auto-organize a small batch of files
            if category in ["shows", "movies"]:
                try:
                    if category == "shows":
                        organize_shows(dry_run=False, rename_files=True, use_omdb=True, write_poster=True, limit=50)
                    else:
                        organize_movies(dry_run=False, use_omdb=True, write_poster=True, limit=50)
                except Exception as e:
                    logger.error(f"Auto-organize error for {category}: {e}")
        finally:
            with _index_lock:
                _index_building[category] = False

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return {"building": True, "fresh": False, "state": state}

def scan_media_page(category: str, q: str, offset: int, limit: int):
    paths_to_scan = get_scan_paths(category)
    qn = (q or "").strip().lower()
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 50), 200))
    want = offset + limit

    allowed = None
    if category in ['movies', 'shows']:
        allowed = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.wmv', '.flv', '.3gp', '.mpg', '.mpeg'}
    elif category == 'music':
        allowed = {'.mp3', '.flac', '.wav', '.m4a'}
    elif category == 'books':
        allowed = {'.pdf', '.epub', '.mobi', '.cbz', '.cbr'}
    elif category == 'gallery':
        allowed = {'.jpg', '.jpeg', '.png', '.gif', '.mp4', '.mov'}

    matched = []
    for base in paths_to_scan:
        if not os.path.exists(base):
            continue
        for root, _, filenames in os.walk(base):
            for f in filenames:
                if f.startswith('.'):
                    continue
                ext = os.path.splitext(f)[1].lower()
                if allowed and ext not in allowed:
                    continue
                if qn:
                    text = f"{f} {os.path.relpath(root, base)}".replace(os.sep, "/").lower()
                    if qn not in text:
                        continue
                full_path = os.path.join(root, f)
                try:
                    rel_path = os.path.relpath(full_path, BASE_DIR)
                    url_path = rel_path.replace(os.sep, '/')
                    web_path = f"/data/{url_path}"
                except Exception:
                    continue

                try:
                    folder = os.path.relpath(root, base).replace(os.sep, '/')
                except Exception:
                    folder = "."

                # Poster lookup
                p_url = None
                if category == "movies":
                    p_url = find_local_poster(root, f)
                elif category == "shows":
                    # Priority 1: Episode-specific poster (if any)
                    p_url = find_local_poster(root, f)
                    if not p_url:
                        # Priority 2: Season-specific poster (poster.jpg in Season folder)
                        p_url = find_local_poster(root)
                    if not p_url:
                        # Priority 3: Show-level folder (poster.jpg in Show folder)
                        parent = os.path.dirname(root)
                        if parent != base and parent != BASE_DIR:
                            p_url = find_local_poster(parent)

                item = {
                    "name": f,
                    "path": web_path,
                    "folder": folder,
                    "type": category,
                    "source": "external" if "external" in rel_path else "local",
                    "poster": p_url
                }

                matched.append(item)
                try:
                    st = os.stat(full_path)
                    item_to_index = {
                        "path": web_path,
                        "category": category,
                        "name": f,
                        "folder": folder,
                        "source": item["source"],
                        "poster": item.get("poster"),
                        "mtime": float(getattr(st, "st_mtime", 0.0) or 0.0),
                        "size": int(getattr(st, "st_size", 0) or 0),
                    }
                    # We could batch these, but since scan_media_page is for small-ish result sets (limit 200),
                    # individual upserts are okay, but let's at least make sure it's not slowing down the search UI too much.
                    # Actually, for consistency with build_library_index, let's use the batching pattern if we want to be thorough.
                    database.upsert_library_index_item(item_to_index)
                except Exception:
                    pass
                if len(matched) >= want:
                    break
            if len(matched) >= want:
                break
        if len(matched) >= want:
            break

    matched.sort(key=lambda x: (natural_sort_key(x.get("folder") or "."), natural_sort_key(x.get("name") or "")))
    return matched[offset: offset + limit]

@router.get("/genres")
def get_genres(category: str = Query(...)):
    return database.get_unique_genres(category)

@router.get("/years")
def get_years(category: str = Query(...)):
    return database.get_unique_years(category)

@router.post("/play_count")
def increment_play_count(path: str = Body(..., embed=True)):
    database.increment_play_count(path)
    return {"status": "success"}

@router.get("/library/{category}")
def get_library(
    category: str, 
    q: str = Query(default=None), 
    offset: int = Query(default=0), 
    limit: int = Query(default=50),
    sort: str = Query(default='name'),
    genre: str = Query(default=None),
    year: str = Query(default=None)
):
    # Try to use database index if available
    try:
        if category == 'shows':
            items, total = database.query_shows(q=q, offset=offset, limit=limit, sort=sort, genre=genre, year=year)
        else:
            items, total = database.query_library_index(category, q=q, offset=offset, limit=limit, sort=sort, genre=genre, year=year)
            
        if total > 0 or q or genre or year:
            return {
                "items": items, 
                "total": total, 
                "next_offset": offset + len(items),
                "has_more": (offset + len(items)) < total,
                "source": "database"
            }
    except Exception as e:
        logger.error(f"Database query failed for {category}: {e}")

    # Fallback to filesystem scan (less features)
    items = scan_media_page(category, q, offset, limit)
    return {
        "items": items, 
        "total": len(items), 
        "next_offset": offset + len(items),
        "has_more": len(items) >= limit,
        "source": "filesystem"
    }

@router.get("/meta")
def get_metadata(path: str = Query(...), fetch: bool = Query(default=False), force: bool = Query(default=False), media_type: str = Query(default=None)):
    if not isinstance(path, str) or not path.startswith("/data/"):
        raise HTTPException(status_code=400, detail="Invalid path")

    # Infer media_type if not provided
    if not media_type:
        if "/shows/" in path.lower():
            media_type = "series"
        elif "/movies/" in path.lower():
            media_type = "movie"
        else:
            media_type = "movie"

    cached = database.get_file_metadata(path)
    if cached and not fetch:
        return {"configured": bool(os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")), "cached": True, **cached}

    if not fetch:
        return {"configured": bool(os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")), "cached": False, "path": path}

    if cached and not force:
        fetched_at = cached.get("fetched_at")
        if isinstance(fetched_at, str) and fetched_at:
            try:
                ts = datetime.fromisoformat(fetched_at)
                if datetime.now() - ts < timedelta(days=30):
                    return {"configured": bool(os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")), "cached": True, **cached}
            except Exception:
                pass

    try:
        fs_path = safe_fs_path_from_web_path(path)
    except HTTPException:
        fs_path = None

    filename = os.path.basename(fs_path or path)
    title_guess, year_guess = guess_title_year(filename)
    
    # IMPROVEMENT: If title_guess is very short or generic (like 'movie' or 'video'),
    # try to use the parent folder name if we are in the movies directory.
    if "/movies/" in path.lower() and (len(title_guess) < 3 or title_guess.lower() in ["movie", "video", "film"]):
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3: # /data/movies/FolderName/file.mkv
            folder_name = parts[-2]
            f_title, f_year = guess_title_year(folder_name)
            if len(f_title) > len(title_guess):
                title_guess, year_guess = f_title, f_year or year_guess

    # If it's a show, we might want to try both "series" and "movie" (some miniseries are listed as movies)
    # or if it has SxxExx, definitely try series
    is_show_pattern = bool(re.search(r"(?i)\bS(\d{1,3})\s*[\.\-_\s]*\s*E(\d{1,3})\b|\b(\d{1,3})x(\d{1,3})\b", filename))
    if is_show_pattern:
        media_type = "series"

    # Try multiple search variations if the first one fails
    search_queries = [
        (title_guess, year_guess),
        (title_guess, None),  # Try without year if year might be wrong
    ]
    
    # Add variations for titles with numbers at the end (common for sequels)
    m_sequel = re.search(r'(.*)\s+(\d+)$', title_guess)
    if m_sequel:
        # e.g. "Toy Story 2" -> search "Toy Story 2" (already in), but also "Toy Story II"
        base_title = m_sequel.group(1)
        num = int(m_sequel.group(2))
        roman = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"][num] if num <= 10 else ""
        if roman:
            search_queries.append((f"{base_title} {roman}", year_guess))
            search_queries.append((f"{base_title} {roman}", None))
        
        # Also try "Toy Story" as fallback
        search_queries.append((base_title, year_guess))
        search_queries.append((base_title, None))

    # Add variation for "The " prefix
    if title_guess.lower().startswith("the "):
        no_the = title_guess[4:]
        search_queries.append((no_the, year_guess))
        search_queries.append((no_the, None))
    
    # Add variation for Harry Potter specific (Philosopher's vs Sorcerer's)
    if "sorcerer's stone" in title_guess.lower():
        alt = title_guess.lower().replace("sorcerer's stone", "philosopher's stone")
        search_queries.append((alt, year_guess))
    elif "philosopher's stone" in title_guess.lower():
        alt = title_guess.lower().replace("philosopher's stone", "sorcerer's stone")
        search_queries.append((alt, year_guess))

    # If title has multiple words, try stripping the last one if first match fails
    if ' ' in title_guess:
        words = title_guess.split()
        if len(words) > 2:
            shorter = ' '.join(words[:-1])
            search_queries.append((shorter, year_guess))
            search_queries.append((shorter, None))

    # Remove duplicates while preserving order
    seen = set()
    unique_queries = []
    for q in search_queries:
        if q not in seen:
            unique_queries.append(q)
            seen.add(q)
    search_queries = unique_queries

    meta = None
    last_error = None

    for q_title, q_year in search_queries:
        try:
            # Try direct fetch first
            meta = omdb_fetch(title=q_title, year=q_year, media_type=media_type)
            if meta: break
        except HTTPException as e:
            if e.status_code != 404:
                last_error = e
                continue
            
            # If we tried series and failed, try movie just in case
            if media_type == "series":
                try:
                    meta = omdb_fetch(title=q_title, year=q_year, media_type="movie")
                    if meta: break
                except: pass

            # Try search if direct fetch fails
            try:
                search = omdb_search(query=q_title, year=q_year, media_type=media_type)
                results = search.get("Search") or []
                if results:
                    # Score and pick best
                    want = normalize_title(q_title)
                    best = None
                    best_score = -1
                    for r in results[:10]: # Increase to top 10 for better coverage
                        t = r.get("Title")
                        y = r.get("Year")
                        if not t: continue
                        
                        score = 0
                        norm_t = normalize_title(t)
                        
                        # Exact match is highest priority
                        if norm_t == want: 
                            score += 50
                        # Sequel match (e.g. "Toy Story 2" matches "Toy Story 2")
                        elif want in norm_t or norm_t in want: 
                            score += 20
                        
                        # Year matching is very important for series
                        if q_year and y:
                            # Handle "2001–2004" or "2001-" year formats from OMDb
                            y_str = str(y)
                            if q_year in y_str:
                                score += 30
                            elif any(char.isdigit() for char in y_str):
                                # Check if the year is within a reasonable range (e.g. +/- 1 year)
                                try:
                                    y_val = int(re.search(r'\d{4}', y_str).group())
                                    if abs(y_val - int(q_year)) <= 1:
                                        score += 15
                                except: pass
                            
                        # Boost movies/series based on the inferred type
                        if r.get("Type") == media_type:
                            score += 10
                            
                        if best is None or score > best_score:
                            best = r
                            best_score = score
                    
                    if best and best_score >= 20: # Higher threshold for better accuracy
                        meta = omdb_fetch(imdb_id=best.get("imdbID"), media_type=media_type)
                        break
            except Exception:
                continue

    if not meta:
        if last_error: raise last_error
        raise HTTPException(status_code=404, detail="Could not find metadata for this file. Try renaming it to a cleaner title.")

    # Cache poster if available
    if meta.get("Poster") and meta["Poster"] != "N/A":
        cached_poster = cache_remote_poster(meta["Poster"])
        if cached_poster:
            meta["Poster"] = cached_poster

    database.upsert_file_metadata(path, media_type, meta)
    
    # Also update the library index with genre, year and poster
    try:
        database.upsert_library_index_item({
            "path": path,
            "genre": meta.get("Genre"),
            "year": meta.get("Year"),
            "poster": meta.get("Poster")
        })
    except Exception:
        pass

    stored = database.get_file_metadata(path)
    return {"configured": True, "cached": True, **(stored or {})}


from fastapi.responses import FileResponse, StreamingResponse
import mimetypes

@router.get("/info")
def get_media_info(path: str = Query(...)):
    """Get technical info about a media file using ffprobe."""
    try:
        fs_path = safe_fs_path_from_web_path(path)
    except:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="File not found")

    try:
        cmd = [
            "ffprobe", 
            "-v", "quiet", 
            "-print_format", "json", 
            "-show_format", 
            "-show_streams", 
            fs_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {"error": "ffprobe failed", "details": result.stderr}
        
        info = json.loads(result.stdout)
        
        # Simplify info for the UI
        streams = info.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        
        # Check compatibility (Basic checks)
        video_codec = video_stream.get("codec_name", "unknown")
        is_h265 = video_codec in ["hevc", "h265"]
        
        audio_info = []
        has_ac3_dts = False
        for a in audio_streams:
            codec = a.get("codec_name", "unknown")
            audio_info.append(codec)
            if codec in ["ac3", "dts", "eac3", "truehd"]:
                has_ac3_dts = True

        return {
            "format": info.get("format", {}).get("format_long_name"),
            "duration": float(info.get("format", {}).get("duration", 0)),
            "size": int(info.get("format", {}).get("size", 0)),
            "video": {
                "codec": video_codec,
                "width": video_stream.get("width"),
                "height": video_stream.get("height"),
                "pix_fmt": video_stream.get("pix_fmt"),
                "compatible": not is_h265 # H265 is often problematic
            },
            "audio": {
                "codecs": audio_info,
                "compatible": not has_ac3_dts # AC3/DTS is often problematic
            },
            "full_info": info if os.environ.get("DEBUG") else None
        }
    except Exception as e:
        return {"error": str(e)}

@router.get("/stream")
async def stream_media(path: str = Query(...), token: str = Query(None)):
    # The middleware already checks for token, but we can double check here if needed
    # However, if it got here, it's either authenticated or it's a path that doesn't start with /data or /api/media
    
    # We should ensure the path is valid
    if not os.path.isabs(path) and not path.startswith("/data/"):
        # Try to resolve relative to BASE_DIR if it's not absolute
        fs_path = os.path.abspath(os.path.join(BASE_DIR, path.lstrip("/")))
    else:
        if path.startswith("/data/"):
            try:
                fs_path = safe_fs_path_from_web_path(path)
            except:
                raise HTTPException(status_code=400, detail="Invalid data path")
        else:
            # Absolute path (e.g. D:\Music)
            fs_path = path

    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Simple FileResponse for now, it supports range requests
    return FileResponse(fs_path)

def refresh_external_links():
    """Ensure symlinks in data/external exist for all currently mounted USB drives."""
    if platform.system() != "Linux":
        return

    ext_root = os.path.join(BASE_DIR, "external")
    os.makedirs(ext_root, exist_ok=True)
    
    # Check /media/pi or /media/ (standard mount points)
    for mount_root in ["/media/pi", "/media"]:
        if os.path.exists(mount_root):
            try:
                for drive in os.listdir(mount_root):
                    drive_path = os.path.join(mount_root, drive)
                    if os.path.ismount(drive_path) or os.path.isdir(drive_path):
                        external_link = os.path.join(ext_root, drive)
                        if not os.path.exists(external_link):
                            try:
                                os.symlink(drive_path, external_link)
                                logger.info(f"Auto-created symlink for USB drive: {drive_path} -> {external_link}")
                            except Exception as e:
                                logger.warning(f"Failed to create symlink for {drive_path}: {e}")
            except Exception:
                pass

@router.get("/browse")
def browse_files(path: str = Query(default="/data")):
    # Proactively refresh external links if browsing /data or /data/external
    if path == "/data" or path.startswith("/data/external"):
        refresh_external_links()

    # Special handling for log files
    if path == "/update.log":
        log_path = os.path.abspath("update.log")
        if os.path.exists(log_path):
            return {"items": [{"name": "update.log", "path": "/update.log", "is_dir": False, "size": os.path.getsize(log_path)}]}
        return {"items": []}

    # Allow Windows absolute paths or paths starting with /data or Linux mount points
    is_windows_path = platform.system() == "Windows" and len(path) >= 2 and path[1] == ":"
    is_linux_mount = platform.system() == "Linux" and (path.startswith("/media") or path.startswith("/mnt"))
    
    if not path.startswith("/data") and not is_windows_path and not is_linux_mount:
        raise HTTPException(status_code=400, detail="Invalid path")
    
    try:
        if path == "/data":
            fs_path = BASE_DIR
        elif path.startswith("/data/"):
            fs_path = safe_fs_path_from_web_path(path)
        elif is_linux_mount:
            fs_path = os.path.abspath(path)
        else:
            # Windows path
            fs_path = os.path.abspath(path)
    except HTTPException:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not os.path.isdir(fs_path):
        raise HTTPException(status_code=404, detail="Directory not found")

    items = []
    base_abs = BASE_DIR # Already absolute
    try:
        for item in os.listdir(fs_path):
            if item.startswith('.'):
                continue
            
            try:
                full_path = os.path.abspath(os.path.join(fs_path, item))
                is_dir = os.path.isdir(full_path)
                
                if full_path.startswith(base_abs):
                    rel_path = os.path.relpath(full_path, base_abs).replace(os.sep, "/")
                    web_path = f"/data/{rel_path}"
                else:
                    # External path, use absolute path for browsing
                    web_path = full_path
                
                try:
                    size = os.path.getsize(full_path) if not is_dir else 0
                except:
                    size = 0

                items.append({
                    "name": str(item),  # Ensure string type
                    "path": str(web_path),  # Ensure string type
                    "is_dir": bool(is_dir),  # Ensure boolean type
                    "size": int(size)  # Ensure integer type
                })
            except Exception as item_error:
                # Skip items that cause errors (e.g., permission issues)
                logger.warning(f"Skipping item {item}: {item_error}")
                continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    items.sort(key=lambda x: (not x["is_dir"], natural_sort_key(x["name"])))
    return {"path": path, "items": items}

@router.get("/list_paged/{category}")
def list_media_paged(
    category: str, 
    offset: int = Query(default=0), 
    limit: int = Query(default=60), 
    q: str = Query(default=""), 
    rebuild: bool = Query(default=False),
    sort: str = Query(default='name'),
    genre: str = Query(default=None),
    year: str = Query(default=None)
):
    if category not in ["movies", "shows", "music", "books", "gallery", "files"]:
        raise HTTPException(status_code=400, detail="Invalid category")

    # Use cache if not rebuilding
    if not rebuild:
        cache_key = build_cache_key(category, q, offset, limit, sort, genre, year)
        return _get_paged_data_cached(category, cache_key, q, offset, limit, sort, genre, year)

    return _get_paged_data(category, q, offset, limit, sort, genre, year, rebuild)

def extract_archive_to_dir(archive_path: str, out_dir: str):
    attempts = []

    # Common Windows 7-Zip paths
    win_7z_paths = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe"
    ]
    for p in win_7z_paths:
        if os.path.exists(p):
            attempts.append((f"7z (Windows)", [p, "x", archive_path, f"-o{out_dir}", "-y"]))

    for candidate in ["7zz", "7z", "7zr"]:
        p = shutil.which(candidate)
        if p:
            attempts.append((candidate, [p, "x", "-y", "-aoa", f"-o{out_dir}", archive_path]))

    p = shutil.which("unar")
    if p:
        attempts.append(("unar", [p, "-o", out_dir, "-f", archive_path]))

    p = shutil.which("bsdtar")
    if p:
        attempts.append(("bsdtar", [p, "-xf", archive_path, "-C", out_dir]))

    if not attempts:
        print("CBR Extraction Error: No extractor tools found (checked 7zz, 7z, 7zr, unar, bsdtar, and standard Windows paths).")
        raise HTTPException(status_code=500, detail="No extractor installed for CBR. Install 7-Zip (Windows) or p7zip-full/unar (Linux).")

    last_err = None
    for tool, cmd in attempts:
        try:
            print(f"Attempting extraction with {tool}: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            print(f"Extraction successful with {tool}")
            return tool
        except subprocess.CalledProcessError as e:
            err = (e.stderr or e.stdout or "").strip()
            last_err = f"{tool} failed: {err}" if err else f"{tool} failed with exit code {e.returncode}"
            print(f"Extraction error ({tool}): {last_err}")
        except Exception as e:
            last_err = f"{tool} error: {e}"
            print(f"Extraction exception ({tool}): {e}")

    print(f"All extraction attempts failed. Last error: {last_err}")
    raise HTTPException(status_code=500, detail=last_err or "Failed to extract archive.")

@router.get("/list/{category}")
def list_media(category: str):
    paths_to_scan = get_scan_paths(category)
    files = []
    
    # Get all progress to merge
    all_progress = database.get_all_progress()

    for path in paths_to_scan:
        if not os.path.exists(path):
            continue
            
        for root, dirs, filenames in os.walk(path):
            for f in filenames:
                if f.startswith('.'):
                    continue
                
                # Filter based on category extensions
                ext = f.split('.')[-1].lower()
                if category in ['movies', 'shows'] and ext not in ['mp4', 'mkv', 'avi', 'mov', 'webm']:
                    continue
                if category == 'music' and ext not in ['mp3', 'flac', 'wav', 'm4a']:
                    continue
                if category == 'books' and ext not in ['pdf', 'epub', 'mobi', 'cbz', 'cbr']:
                    continue
                if category == 'gallery' and ext not in ['jpg', 'jpeg', 'png', 'gif', 'mp4', 'mov']:
                    continue

                full_path = os.path.join(root, f)
                try:
                    rel_path = os.path.relpath(full_path, BASE_DIR)
                    url_path = rel_path.replace(os.sep, '/')
                    web_path = f"/data/{url_path}"
                    
                    item = {
                        "name": f,
                        "path": web_path,
                        "folder": os.path.relpath(root, path).replace(os.sep, '/'),
                        "type": category,
                        "source": "external" if "external" in rel_path else "local"
                    }

                    if category == "movies":
                        item["poster"] = find_local_poster(root, f)
                    elif category == "shows":
                        item["poster"] = find_local_poster(root, f)
                        if not item["poster"]:
                            # Try show-level folder
                            parent = os.path.dirname(root)
                            if parent != path and parent != BASE_DIR:
                                item["poster"] = find_local_poster(parent)
                    
                    # Add progress if exists
                    if web_path in all_progress:
                        item["progress"] = all_progress[web_path]
                    
                    files.append(item)
                except ValueError:
                    continue

    files.sort(key=lambda x: (natural_sort_key(x.get("folder") or "."), natural_sort_key(x.get("name") or "")))
    return files

@router.post("/progress")
def set_progress(data: Dict = Body(...)):
    path = data.get("path") or data.get("file_path")
    time = data.get("current_time")
    duration = data.get("duration")
    
    if not path or time is None:
        return {"status": "error", "message": "Missing path or current_time"}
        
    try:
        database.update_progress(path, time, duration)
        
        # If progress is near the end (e.g., > 95%), mark as played
        if duration and duration > 0:
            if (time / duration) > 0.95:
                database.increment_play_count(path)
                
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error updating progress for {path}: {e}")
        return {"status": "error", "message": str(e)}

@router.post("/rename")
def rename_media(data: Dict = Body(...), background_tasks: BackgroundTasks = None):
    old_path = data.get("old_path") or data.get("path")
    new_path = data.get("new_path") or data.get("dest_path")
    if not isinstance(old_path, str) or not old_path.startswith("/data/"):
        raise HTTPException(status_code=400, detail="Invalid old_path")
    if not isinstance(new_path, str) or not new_path.startswith("/data/"):
        raise HTTPException(status_code=400, detail="Invalid new_path")

    old_fs = safe_fs_path_from_web_path(old_path)
    new_fs = safe_fs_path_from_web_path(new_path)

    if not os.path.exists(old_fs):
        raise HTTPException(status_code=404, detail="Path not found")
    if os.path.exists(new_fs):
        raise HTTPException(status_code=409, detail="Destination already exists")

    is_dir = os.path.isdir(old_fs)
    os.makedirs(os.path.dirname(new_fs), exist_ok=True)
    try:
        shutil.move(old_fs, new_fs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rename failed: {e}")

    try:
        database.rename_media_path(old_path, new_path, is_dir=is_dir)
    except Exception:
        pass

    # Trigger MiniDLNA rescan after rename
    if background_tasks:
        background_tasks.add_task(trigger_dlna_rescan)
    else:
        # Fallback if BackgroundTasks is not provided for some reason
        trigger_dlna_rescan()

    return {"status": "ok", "old_path": old_path, "new_path": new_path}

# Public wrappers for ingestion/organization
def parse_season_episode(filename: str):
    return _parse_season_episode(filename)

def parse_episode_only(filename: str):
    return _parse_episode_only(filename)

def auto_dest_rel(category: str, normalized: str, rename_files: bool = True):
    return _auto_dest_rel(category, normalized, rename_files)

def pick_unique_dest(path: str):
    return _pick_unique_dest(path)

def _sanitize_show_part(s: str):
    s = re.sub(r"[\._]+", " ", str(s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r'[<>:"/\\\\|?*]', "", s).strip()
    return s

def _infer_show_name_from_filename(path_or_name: str):
    base = os.path.basename(str(path_or_name or ""))
    name = os.path.splitext(base)[0]
    # Handle dots, underscores, hyphens as spaces for extraction
    clean_name = re.sub(r'[\._\-]+', ' ', name)
    m = re.match(r"^(.*?)(?:\bS\d{1,3}\s*E\d{1,3}\b|\b\d{1,3}x\d{1,3}\b|\bEpisode\s*\d{1,3}\b)", clean_name, flags=re.IGNORECASE)
    if not m or not m.group(1):
        # Try a more aggressive match if no standard SxxExx
        # e.g. "Family Guy 14x01" or "Family Guy S14E01"
        m = re.search(r"^(.*?)(?:\bS\d{1,3}|\b\d{1,3}x)", clean_name, flags=re.IGNORECASE)
        if not m or not m.group(1):
            return ""
    cleaned = _sanitize_show_part(m.group(1))
    return cleaned if len(cleaned) >= 2 else ""

def _parse_season_episode(filename: str):
    base = os.path.splitext(os.path.basename(filename or ""))[0]
    
    # S01E01, S1E1, S01.E01, S01_E01, S01-E01
    m = re.search(r"(?i)\bS(\d{1,3})\s*[\.\-_\s]*\s*E(\d{1,3})\b", base)
    if m:
        return int(m.group(1)), int(m.group(2))
        
    # 1x01, 01x01
    m = re.search(r"(?i)\b(\d{1,3})x(\d{1,3})\b", base)
    if m:
        return int(m.group(1)), int(m.group(2))

    # Just E01 or Episode 01 (often in season folders)
    m = re.search(r"(?i)\bE(\d{1,3})\b|\bEpisode\s*(\d{1,3})\b", base)
    if m:
        ep_val = m.group(1) or m.group(2)
        return None, int(ep_val)
        
    # Season 1 Episode 1
    m = re.search(r"(?i)\bseason\s*(\d{1,3})\s*[\.\-_\s]*\s*episode\s*(\d{1,3})\b", base)
    if m:
        return int(m.group(1)), int(m.group(2))
        
    # [1.01] or (1.01)
    m = re.search(r"[\[\(](\d{1,2})\.(\d{1,2})[\]\)]", base)
    if m:
        return int(m.group(1)), int(m.group(2))

    # 101, 1101 (Only if it's 3 or 4 digits and looks like a season/episode)
    # This is risky, but common for some scene releases
    m = re.search(r"\b(\d{1,2})(\d{2})\b", base)
    if m:
        s, e = int(m.group(1)), int(m.group(2))
        if 0 < s < 50 and 0 < e < 100:
            return s, e

    return None, None

def _parse_episode_only(filename: str):
    base = os.path.splitext(os.path.basename(filename or ""))[0]
    m = re.search(r"(?i)\bE(\d{1,3})\b", base)
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)\bepisode\s*(\d{1,3})\b", base)
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)(?:^|[ \.\-_\(\)\[\]]+)(\d{1,3})(?:$|[ \.\-_\(\)\[\]]+)", base)
    if m:
        n = int(m.group(1))
        if 0 < n <= 300:
            return n
    return None

def _sanitize_movie_part(s: str):
    s = re.sub(r"[\._]+", " ", str(s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r'[<>:"/\\\\|?*]', "", s).strip()
    return s

def _pick_unique_dest(path: str):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for i in range(2, 1000):
        p = f"{base} ({i}){ext}"
        if not os.path.exists(p):
            return p
    raise HTTPException(status_code=409, detail="Destination exists")

def _infer_season_from_parts(parts: List[str]):
    for p in parts:
        m = re.search(r"(?i)\bseason\s*(\d{1,3})\b", p)
        if m:
            return int(m.group(1))
        m = re.search(r"(?i)\bs(\d{1,3})\b", p)
        if m:
            return int(m.group(1))
    return None

def _auto_dest_rel(category: str, normalized: str, rename_files: bool = True):
    parts = [p for p in str(normalized or "").split("/") if p]
    name = parts[-1] if parts else ""
    ext = os.path.splitext(name)[1].lower()

    if category == "shows":
        show_name = ""
        if len(parts) >= 2:
            first = parts[0]
            first_l = first.lower()
            if not (first_l.startswith("season") or first_l.startswith("series") or re.match(r"^s\d{1,3}$", first_l or "")):
                show_name = first
        if not show_name:
            show_name = _infer_show_name_from_filename(name) or "Unsorted"
        show_name = _sanitize_show_part(show_name) or "Unsorted"

        season_num = _infer_season_from_parts(parts[:-1])
        se, ep = _parse_season_episode(name)
        if season_num is None and se is not None:
            season_num = se
        if ep is None:
            ep = _parse_episode_only(name)
        if season_num is None:
            season_num = 1

        season_folder = f"Season {int(season_num)}"
        dest_name = name
        if rename_files and ep is not None:
            dest_name = f"S{int(season_num):02d}E{int(ep):02d}{ext}"
        return f"{show_name}/{season_folder}/{dest_name}"

    if category == "movies":
        title_guess, year_guess = guess_title_year(name)
        title_guess = _sanitize_movie_part(title_guess) or "Movie"
        folder = f"{title_guess} ({year_guess})" if year_guess else title_guess
        folder = _sanitize_movie_part(folder) or title_guess
        base_name = folder
        dest_name = f"{base_name}{ext}" if ext else base_name
        return f"{folder}/{dest_name}"

    return normalized

@router.post("/organize/shows")
def organize_shows(dry_run: bool = Query(default=True), rename_files: bool = Query(default=True), use_omdb: bool = Query(default=True), write_poster: bool = Query(default=True), limit: int = Query(default=250)):
    show_bases = get_scan_paths("shows")
    limit = max(1, min(int(limit or 250), 5000))
    planned = []
    moved = 0
    skipped = 0
    errors = 0
    shows_processed = {}  # Track which shows we've fetched metadata for: name -> meta

    for base in show_bases:
        if not os.path.isdir(base):
            continue
            
        for root, _, filenames in os.walk(base):
            for f in filenames:
                if f.startswith("."):
                    continue
                ext = os.path.splitext(f)[1].lower()
                if ext not in [".mp4", ".mkv", ".avi", ".mov", ".webm"]:
                    continue

                src_fs = os.path.join(root, f)
                rel_under = os.path.relpath(src_fs, base).replace(os.sep, "/")
                parts = [p for p in rel_under.split("/") if p]
                if not parts:
                    continue

                show_name = ""
                season_num_from_folder = None
                if len(parts) >= 2:
                    first = parts[0]
                    first_l = first.lower()
                    
                    # Better show name extraction
                    if ' - season ' in first_l or ' season ' in first_l:
                        match = re.search(r'^(.+?)\s*[-–]\s*season\s*\d+', first, re.IGNORECASE)
                        if match:
                            show_name = match.group(1).strip()
                        else:
                            match = re.search(r'^(.+?)\s*season\s*\d+', first, re.IGNORECASE)
                            if match:
                                show_name = match.group(1).strip()
                        
                        # Also extract season number for later use if we found a match
                        s_match = re.search(r'season\s*(\d+)', first, re.IGNORECASE)
                        if s_match:
                            season_num_from_folder = int(s_match.group(1))
                    elif not (first_l.startswith("season") or first_l.startswith("series") 
                              or re.match(r"^s\d{1,3}$", first_l or "")):
                        show_name = first

                if not show_name:
                    show_name = _infer_show_name_from_filename(f) or "Unsorted"
                show_name = _sanitize_show_part(show_name) or "Unsorted"

                season_part = parts[1] if len(parts) >= 3 else ""
                season_num, episode_num = _parse_season_episode(f)
                if season_num is None:
                    if season_num_from_folder is not None:
                        season_num = season_num_from_folder
                    else:
                        season_num = _infer_season_from_parts([season_part]) or 1
                if episode_num is None:
                    episode_num = _parse_episode_only(f)

                season_folder = f"Season {int(season_num)}"
                dest_dir = os.path.join(base, show_name, season_folder)

                dest_name = f
                if rename_files and episode_num is not None:
                    dest_name = f"S{int(season_num):02d}E{int(episode_num):02d}{ext}"

                dest_fs = os.path.join(dest_dir, dest_name)

                # Correct web paths relative to BASE_DIR
                try:
                    from_web = f"/data/{os.path.relpath(src_fs, BASE_DIR).replace(os.sep, '/')}"
                    to_web = f"/data/{os.path.relpath(dest_fs, BASE_DIR).replace(os.sep, '/')}"
                except Exception:
                    from_web = f"/data/shows/{rel_under}"
                    to_web = f"/data/shows/{os.path.relpath(dest_fs, base).replace(os.sep, '/')}"

                plan = {"from": from_web, "to": to_web}
                planned.append(plan)

                if dry_run:
                    if len(planned) >= limit:
                        break
                    continue

                if os.path.abspath(src_fs) == os.path.abspath(dest_fs):
                    # Already in correct location, but we still want to ensure metadata and posters
                    dest_fs = src_fs
                else:
                    os.makedirs(dest_dir, exist_ok=True)
                    dest_fs = _pick_unique_dest(dest_fs)
                    try:
                        shutil.move(src_fs, dest_fs)
                        logger.info(f"Organized show file: {src_fs} -> {dest_fs}")
                        try:
                            # Update path in database if it was moved
                            to_web = f"/data/{os.path.relpath(dest_fs, BASE_DIR).replace(os.sep, '/')}"
                            database.rename_media_path(from_web, to_web)
                        except Exception:
                            pass
                    except Exception as e:
                        logger.error(f"Failed to move show file {src_fs}: {e}")
                        errors += 1
                        continue

                # Fetch OMDB metadata and poster for the show (once per show)
                meta = shows_processed.get(show_name)
                show_dir = os.path.join(base, show_name)
                poster_dest = os.path.join(show_dir, "poster.jpg")
                
                # Try to fetch from OMDB if needed
                if use_omdb and show_name != "Unsorted" and not meta:
                    if os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY"):
                        try:
                            # Fetch show metadata
                            meta = omdb_fetch(title=show_name, media_type="series")
                            shows_processed[show_name] = meta
                            logger.info(f"Fetched OMDB metadata for show: {show_name}")
                        except Exception as e:
                            logger.warning(f"Error fetching OMDB data for {show_name}: {e}")

                # Handle posters (either from OMDB or local folder)
                if write_poster:
                    # 1. Check if local poster.jpg already exists
                    if os.path.exists(poster_dest):
                        try:
                            if not meta: meta = {"Title": show_name}
                            meta["Poster"] = f"/data/{os.path.relpath(poster_dest, BASE_DIR).replace(os.sep, '/')}"
                        except Exception: pass
                    # 2. Otherwise try to download from OMDB if we have meta
                    elif meta and meta.get("Poster") and meta["Poster"] != "N/A":
                        try:
                            poster_url = meta["Poster"]
                            cached_poster = cache_remote_poster(poster_url)
                            if cached_poster:
                                # Also save as poster.jpg in show directory
                                cached_fs = safe_fs_path_from_web_path(cached_poster)
                                if os.path.exists(cached_fs):
                                    shutil.copy2(cached_fs, poster_dest)
                                    meta["Poster"] = f"/data/{os.path.relpath(poster_dest, BASE_DIR).replace(os.sep, '/')}"
                                    logger.info(f"Saved OMDB poster for {show_name} to local folder")
                        except Exception as e:
                            logger.warning(f"Failed to save OMDB poster for {show_name}: {e}")

                if meta:
                    try:
                        database.upsert_file_metadata(to_web, "series", meta)
                    except Exception:
                        pass

                moved += 1
                if moved >= limit:
                    break
            if (dry_run and len(planned) >= limit) or ((not dry_run) and moved >= limit):
                break
        if (dry_run and len(planned) >= limit) or ((not dry_run) and moved >= limit):
            break

    return {"status": "ok", "dry_run": bool(dry_run), "rename_files": bool(rename_files), "use_omdb": bool(use_omdb), "write_poster": bool(write_poster), "moved": moved, "skipped": skipped, "errors": errors, "shows_metadata_fetched": len(shows_processed), "planned": planned[: min(len(planned), 1000)]}

@router.post("/organize/movies")
def organize_movies(dry_run: bool = Query(default=True), use_omdb: bool = Query(default=True), write_poster: bool = Query(default=True), limit: int = Query(default=250)):
    movie_bases = get_scan_paths("movies")
    limit = max(1, min(int(limit or 250), 5000))
    planned = []
    moved = 0
    skipped = 0
    errors = 0

    for base in movie_bases:
        if not os.path.isdir(base):
            continue
            
        for root, _, filenames in os.walk(base):
            for f in filenames:
                if f.startswith("."):
                    continue
                ext = os.path.splitext(f)[1].lower()
                if ext not in [".mp4", ".mkv", ".avi", ".mov", ".webm"]:
                    continue

                src_fs = os.path.join(root, f)
                rel_under = os.path.relpath(src_fs, base).replace(os.sep, "/")

                title_guess, year_guess = guess_title_year(f)
                
                # IMPROVEMENT: If filename is generic, try parent folder
                if len(title_guess) < 3 or title_guess.lower() in ["movie", "video", "film", "index"]:
                    parts = [p for p in rel_under.split("/") if p]
                    if len(parts) >= 2: # Folder/file.mkv
                        folder_name = parts[-2]
                        f_title, f_year = guess_title_year(folder_name)
                        if len(f_title) > len(title_guess):
                            title_guess, year_guess = f_title, f_year or year_guess

                title = title_guess
                year = year_guess
                meta = None
                if use_omdb and (os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")):
                    # Try variations for common tricky titles
                    search_queries = [title_guess]
                    
                    t_low = title_guess.lower()
                    if "harry potter" in t_low:
                        if "philosopher" in t_low or "sorcerer" in t_low:
                            search_queries.insert(0, "Harry Potter and the Sorcerer's Stone")
                        elif "chamber of secrets" in t_low:
                            search_queries.insert(0, "Harry Potter and the Chamber of Secrets")
                        elif "prisoner of azkaban" in t_low:
                            search_queries.insert(0, "Harry Potter and the Prisoner of Azkaban")
                        elif "goblet of fire" in t_low:
                            search_queries.insert(0, "Harry Potter and the Goblet of Fire")
                        elif "order of the phoenix" in t_low:
                            search_queries.insert(0, "Harry Potter and the Order of the Phoenix")
                        elif "half blood prince" in t_low:
                            search_queries.insert(0, "Harry Potter and the Half-Blood Prince")
                        elif "deathly hallows" in t_low:
                            if "1" in t_low or "part 1" in t_low or "i" in t_low:
                                search_queries.insert(0, "Harry Potter and the Deathly Hallows: Part 1")
                            elif "2" in t_low or "part 2" in t_low or "ii" in t_low:
                                search_queries.insert(0, "Harry Potter and the Deathly Hallows: Part 2")

                    if "toy story" in t_low:
                        if "2" in t_low or "ii" in t_low: search_queries.insert(0, "Toy Story 2")
                        elif "3" in t_low or "iii" in t_low: search_queries.insert(0, "Toy Story 3")
                        elif "4" in t_low or "iv" in t_low: search_queries.insert(0, "Toy Story 4")

                    # Try fetching
                    for query in search_queries:
                        try:
                            meta = omdb_fetch(title=query, year=year_guess, media_type="movie")
                            break
                        except Exception:
                            try:
                                # Try without year if it failed with year
                                if year_guess:
                                    meta = omdb_fetch(title=query, media_type="movie")
                                    break
                            except Exception:
                                continue
                    
                    # Final fallback: Search
                    if not meta:
                        try:
                            search_res = omdb_search(title_guess, year=year_guess, media_type="movie")
                            if search_res.get("Search"):
                                meta = omdb_fetch(imdb_id=search_res["Search"][0].get("imdbID"))
                        except Exception:
                            pass

                    if meta:
                        t = meta.get("Title")
                        y = meta.get("Year")
                        if isinstance(t, str) and t.strip():
                            title = t.strip()
                        if isinstance(y, str) and y.strip():
                            # Clean year (sometimes "2010–2015")
                            y_match = re.search(r"\b(19\d{2}|20\d{2})\b", y)
                            if y_match:
                                year = y_match.group(1)
                            else:
                                year = y.strip()

                title = _sanitize_movie_part(title) or "Movie"
                folder = f"{title} ({year})" if year else title
                folder = _sanitize_movie_part(folder) or title
                dest_dir = os.path.join(base, folder)
                dest_name = f"{folder}{ext}"
                dest_fs = os.path.join(dest_dir, dest_name)

                # Correct web paths relative to BASE_DIR
                try:
                    from_web = f"/data/{os.path.relpath(src_fs, BASE_DIR).replace(os.sep, '/')}"
                    to_web = f"/data/{os.path.relpath(dest_fs, BASE_DIR).replace(os.sep, '/')}"
                except Exception:
                    # Fallback if relpath fails (e.g. different drives on Windows)
                    from_web = f"/data/movies/{rel_under}"
                    to_web = f"/data/movies/{folder}/{dest_name}"
                
                plan = {"from": from_web, "to": to_web}
                planned.append(plan)

                if dry_run:
                    if len(planned) >= limit:
                        break
                    continue

                if os.path.abspath(src_fs) == os.path.abspath(dest_fs):
                    # Already in correct location, but we still want to ensure metadata and posters
                    dest_fs = src_fs
                else:
                    os.makedirs(dest_dir, exist_ok=True)
                    dest_fs = _pick_unique_dest(dest_fs)
                    try:
                        shutil.move(src_fs, dest_fs)
                        logger.info(f"Organized movie file: {src_fs} -> {dest_fs}")
                        try:
                            # Update path in database if it was moved
                            to_web = f"/data/{os.path.relpath(dest_fs, BASE_DIR).replace(os.sep, '/')}"
                            database.rename_media_path(from_web, to_web)
                        except Exception:
                            pass
                    except Exception as e:
                        logger.error(f"Failed to move movie file {src_fs}: {e}")
                        errors += 1
                        continue

                # Correct to_web after potential move/unique dest
                try:
                    to_web = f"/data/{os.path.relpath(dest_fs, BASE_DIR).replace(os.sep, '/')}"
                except Exception:
                    to_web = from_web

                # Handle posters (either from OMDB or local folder)
                if write_poster:
                    poster_out = os.path.join(dest_dir, "poster.jpg")
                    # 1. Check if local poster.jpg already exists in destination
                    if os.path.exists(poster_out):
                        try:
                            if not meta: meta = {"Title": title, "Year": year}
                            meta["Poster"] = f"/data/{os.path.relpath(poster_out, BASE_DIR).replace(os.sep, '/')}"
                        except Exception: pass
                    # 2. Otherwise try to download from OMDB if we have meta
                    elif meta and meta.get("Poster") and meta["Poster"] != "N/A":
                        try:
                            poster_url = meta["Poster"]
                            cached = cache_remote_poster(poster_url)
                            if cached and cached.startswith("/data/"):
                                cached_fs = safe_fs_path_from_web_path(cached)
                                if os.path.isfile(cached_fs):
                                    shutil.copy2(cached_fs, poster_out)
                                    meta["Poster"] = f"/data/{os.path.relpath(poster_out, BASE_DIR).replace(os.sep, '/')}"
                                    logger.info(f"Saved OMDB poster for {title} to local folder")
                        except Exception: pass

                if meta:
                    try:
                        database.upsert_file_metadata(to_web, "movie", meta)
                    except Exception:
                        pass

                moved += 1
                if moved >= limit:
                    break

            if (dry_run and len(planned) >= limit) or ((not dry_run) and moved >= limit):
                break
        if (dry_run and len(planned) >= limit) or ((not dry_run) and moved >= limit):
            break

    return {"status": "ok", "dry_run": bool(dry_run), "use_omdb": bool(use_omdb), "write_poster": bool(write_poster), "moved": moved, "skipped": skipped, "errors": errors, "planned": planned[: min(len(planned), 1000)]}

import psutil
import subprocess
import platform

def trigger_dlna_rescan():
    """Trigger a MiniDLNA rescan if on Linux"""
    if platform.system() == "Linux":
        try:
            # We try to use the same logic as system.py
            subprocess.run(["sudo", "/usr/sbin/minidlnad", "-R"], check=False)
            subprocess.run(["sudo", "/usr/bin/systemctl", "restart", "minidlna"], check=False)
            logger.info("Triggered MiniDLNA rescan")
        except Exception as e:
            logger.error(f"Failed to trigger MiniDLNA rescan: {e}")

def trigger_auto_organize():
    """Trigger automated organization of shows and movies"""
    try:
        # We can call the organization functions with dry_run=False
        # Note: We don't want to use OMDB every time as it might be slow/hit limits
        # But for new uploads it's probably fine.
        organize_shows(dry_run=False, rename_files=True, use_omdb=True, write_poster=True)
        organize_movies(dry_run=False, use_omdb=True, write_poster=True)
        logger.info("Automated media organization completed")
        # Trigger DLNA rescan after organization is done
        trigger_dlna_rescan()
    except Exception as e:
        logger.error(f"Automated organization failed: {e}")

@router.post("/upload/{category}")
async def upload_file(category: str, background_tasks: BackgroundTasks, files: UploadFile = File(...)):
    # Note: 'files' param name matches frontend FormData.append('files', ...)
    # But since we send one by one, it receives a single UploadFile if not defined as List
    # To support both, we can use List and handle it, or just stick to List.
    # Frontend sends: formData.append('files', file);
    # FastAPI expects: files: List[UploadFile] or files: UploadFile
    
    # If we want to support the loop in frontend sending one file at a time:
    # The frontend does: formData.append('files', file)
    # So the field name is 'files'.
    
    path = os.path.join(BASE_DIR, category)
    os.makedirs(path, exist_ok=True)
    
    # We'll treat it as a list for compatibility, even if it's size 1
    file_list = [files] if not isinstance(files, list) else files
    
    saved_files = []
    for file in file_list:
        incoming_name = (file.filename or "").replace("\\", "/")
        normalized = posixpath.normpath(incoming_name).lstrip("/")
        if normalized.startswith("..") or normalized == ".":
            raise HTTPException(status_code=400, detail="Invalid filename")

        dest_rel = _auto_dest_rel(category, normalized, rename_files=True)
        file_location = os.path.join(path, *dest_rel.split("/"))
        os.makedirs(os.path.dirname(file_location), exist_ok=True)
        
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
        saved_files.append(dest_rel)
        try:
            st = os.stat(file_location)
            rel_path = os.path.relpath(file_location, BASE_DIR).replace(os.sep, "/")
            web_path = f"/data/{rel_path}"
            folder = os.path.relpath(os.path.dirname(file_location), path).replace(os.sep, "/")
            database.upsert_library_index_item({
                "path": web_path,
                "category": category,
                "name": os.path.basename(file_location),
                "folder": folder if folder else ".",
                "source": "local",
                "poster": None,
                "mtime": float(getattr(st, "st_mtime", 0.0) or 0.0),
                "size": int(getattr(st, "st_size", 0) or 0),
            })
        except Exception:
            pass
    
    # Trigger background tasks for rescan and auto-organization
    background_tasks.add_task(trigger_dlna_rescan)
    if category in ["shows", "movies"]:
        background_tasks.add_task(trigger_auto_organize)
    
    return {"info": f"Uploaded {len(saved_files)} files to {category}", "files": saved_files}

import aiofiles

@router.post("/upload_stream/{category}")
async def upload_stream(category: str, request: Request, background_tasks: BackgroundTasks, path: str = Query(default="")):
    incoming_name = path or request.headers.get("x-file-path", "")
    incoming_name = (incoming_name or "").replace("\\", "/")
    normalized = posixpath.normpath(incoming_name).lstrip("/")
    if not normalized or normalized.startswith("..") or normalized == ".":
        raise HTTPException(status_code=400, detail="Invalid filename")

    base_path = os.path.join(BASE_DIR, category)
    os.makedirs(base_path, exist_ok=True)

    dest_rel = _auto_dest_rel(category, normalized, rename_files=True)
    file_location = os.path.join(base_path, *dest_rel.split("/"))
    os.makedirs(os.path.dirname(file_location), exist_ok=True)

    try:
        async with aiofiles.open(file_location, "wb") as out:
            # Consuming the stream directly is often faster than manual buffering in Python
            # as aiofiles and the underlying stream handler already have their own buffers.
            async for chunk in request.stream():
                if chunk:
                    await out.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    try:
        st = os.stat(file_location)
        rel_path = os.path.relpath(file_location, BASE_DIR).replace(os.sep, "/")
        web_path = f"/data/{rel_path}"
        folder = os.path.relpath(os.path.dirname(file_location), base_path).replace(os.sep, "/")
        database.upsert_library_index_item({
            "path": web_path,
            "category": category,
            "name": os.path.basename(file_location),
            "folder": folder if folder else ".",
            "source": "local",
            "poster": None,
            "mtime": float(getattr(st, "st_mtime", 0.0) or 0.0),
            "size": int(getattr(st, "st_size", 0) or 0),
        })
    except Exception:
        pass

    # Trigger background tasks for rescan and auto-organization
    background_tasks.add_task(trigger_dlna_rescan)
    if category in ["shows", "movies"]:
        background_tasks.add_task(trigger_auto_organize)

    return {"info": "Uploaded 1 file", "files": [dest_rel]}

@router.delete("/delete")
def delete_media(path: str, background_tasks: BackgroundTasks):
    fs_path = safe_fs_path_from_web_path(path)
    if not os.path.exists(fs_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        # Get metadata before deleting from DB to find poster
        meta = database.get_file_metadata(path)
        
        logger.info(f"Attempting to delete {fs_path} (from web path {path})")
        
        if os.path.isdir(fs_path):
            shutil.rmtree(fs_path)
        else:
            os.remove(fs_path)
            
        logger.info(f"Successfully deleted {fs_path}")
            
        # Clean up database (now also cleans metadata and progress)
        database.delete_library_index_item(path)
        
        # Clean up cached poster if it exists
        if meta and meta.get("poster"):
            poster_url = meta.get("poster")
            if poster_url.startswith("/data/cache/posters/"):
                try:
                    poster_fs = safe_fs_path_from_web_path(poster_url)
                    if os.path.exists(poster_fs):
                        os.remove(poster_fs)
                except:
                    pass

        # If it's a media file, check if we should remove the parent folder if empty or only contains posters
        parent = os.path.dirname(fs_path)
        if os.path.exists(parent) and parent != BASE_DIR:
            remaining = os.listdir(parent)
            # If only common metadata files remain, clean them up too
            junk = {"poster.jpg", "poster.jpeg", "poster.png", "folder.jpg", "folder.png", "cover.jpg", "cover.png", "fanart.jpg", "movie.nfo"}
            if all(f.lower() in junk for f in remaining):
                try:
                    shutil.rmtree(parent)
                except:
                    pass
                
        # Trigger MiniDLNA rescan after deletion
        background_tasks.add_task(trigger_dlna_rescan)
                
        return {"status": "ok", "deleted": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")

@router.post("/system/prepare_drive")
def prepare_drive(path: str):
    """Create standard media folders on the specified drive path."""
    if not os.path.exists(path):
         raise HTTPException(status_code=404, detail="Drive path not found")
    
    created = []
    for folder in ["movies", "shows", "music", "books", "gallery"]:
        target = os.path.join(path, folder)
        if not os.path.exists(target):
            try:
                os.makedirs(target, exist_ok=True)
                created.append(folder)
            except Exception as e:
                print(f"Failed to create {folder} on {path}: {e}")
    
    return {"status": "ok", "created": created, "message": f"Created {len(created)} folders on drive."}

@router.post("/organize")
def manual_organize(background_tasks: BackgroundTasks):
    """Manually trigger automated media organization"""
    background_tasks.add_task(trigger_auto_organize)
    return {"status": "ok", "message": "Automated organization started in background"}

@router.post("/scan")
def scan_library(background_tasks: BackgroundTasks):
    def run_scan():
        # Scan all categories
        for cat in ["movies", "shows", "music", "books", "gallery", "files"]:
             try:
                 build_library_index(cat)
             except Exception as e:
                 print(f"Scan error {cat}: {e}")
        # Also trigger MiniDLNA rescan and auto-organization
        trigger_dlna_rescan()
        trigger_auto_organize()
        
    background_tasks.add_task(run_scan)
    return {"status": "ok", "message": "Library scan and organization started in background."}

def find_file_poster(web_path: str):
    try:
        fs_path = safe_fs_path_from_web_path(web_path)
    except HTTPException:
        return None
    except Exception as e:
        logger.warning(f"Unexpected error in find_file_poster for {web_path}: {e}")
        return None
    
    dir_path = os.path.dirname(fs_path)
    candidates = ["poster.jpg", "poster.jpeg", "poster.png", "folder.jpg", "folder.png", "cover.jpg", "cover.png"]
    
    # Check current directory
    for name in candidates:
        p = os.path.join(dir_path, name)
        if os.path.isfile(p):
            rel = os.path.relpath(p, BASE_DIR).replace(os.sep, "/")
            return f"/data/{rel}"
            
    # If it's a show episode, check parent directory (show level)
    parent_dir = os.path.dirname(dir_path)
    if "/shows/" in web_path.lower():
        for name in candidates:
            p = os.path.join(parent_dir, name)
            if os.path.isfile(p):
                rel = os.path.relpath(p, BASE_DIR).replace(os.sep, "/")
                return f"/data/{rel}"
    
    return None

@router.get("/resume")
def resume(limit: int = 12):
    all_progress = database.get_all_progress()
    items = []
    for web_path, prog in all_progress.items():
        try:
            t = float(prog.get("current_time") or 0)
            d = float(prog.get("duration") or 0)
        except Exception:
            continue
        if not (t > 60 and d > 0 and (d - t) > 60):
            continue

        try:
            fs_path = safe_fs_path_from_web_path(web_path)
        except HTTPException:
            continue
        if not os.path.isfile(fs_path):
            continue

        name = os.path.basename(fs_path)
        rel = os.path.relpath(fs_path, BASE_DIR).replace(os.sep, "/")
        parts = rel.split("/")
        media_type = parts[0] if parts else "media"
        items.append({
            "name": name, 
            "path": web_path, 
            "type": media_type, 
            "progress": prog,
            "poster": find_file_poster(web_path)
        })

    def last_played(item):
        lp = item.get("progress", {}).get("last_played")
        if isinstance(lp, str) and lp:
            return lp
        return ""

    items.sort(key=last_played, reverse=True)
    return {"items": items[: max(1, min(int(limit), 50))]}

@router.get("/books/comic/pages")
def comic_pages(path: str):
    fs_path = safe_fs_path_from_web_path(path)
    if not os.path.isfile(fs_path):
        raise HTTPException(status_code=404, detail="File not found")

    ext = os.path.splitext(fs_path)[1].lower().lstrip(".")
    if ext not in ["cbz", "cbr"]:
        raise HTTPException(status_code=400, detail="Only CBZ/CBR are supported for viewing")

    try:
        file_stat = os.stat(fs_path)
        cache_key = hashlib.sha1(f"{fs_path}:{file_stat.st_mtime}".encode("utf-8")).hexdigest()
        cache_root = os.path.join(BASE_DIR, ".cache", "comics", cache_key)
        raw_root = os.path.join(cache_root, "_raw")
        pages_root = os.path.join(cache_root, "pages")
        marker = os.path.join(cache_root, ".ok")
        if not os.path.exists(marker):
            if os.path.exists(cache_root):
                shutil.rmtree(cache_root, ignore_errors=True)
            os.makedirs(cache_root, exist_ok=True)
            os.makedirs(raw_root, exist_ok=True)
            os.makedirs(pages_root, exist_ok=True)

            if ext == "cbz":
                with zipfile.ZipFile(fs_path) as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        name = (info.filename or "").replace("\\", "/")
                        normalized = posixpath.normpath(name).lstrip("/")
                        if normalized.startswith("..") or normalized == ".":
                            continue
                        ext2 = os.path.splitext(normalized)[1].lower()
                        if ext2 not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                            continue

                        target = os.path.abspath(os.path.join(pages_root, *normalized.split("/")))
                        if os.path.commonpath([os.path.abspath(pages_root), target]) != os.path.abspath(pages_root):
                            continue
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with zf.open(info) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
            else:
                extract_archive_to_dir(fs_path, raw_root)

                for root, _, filenames in os.walk(raw_root):
                    for f in filenames:
                        ext2 = os.path.splitext(f)[1].lower()
                        if ext2 not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                            continue
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, raw_root).replace(os.sep, "/")
                        normalized = posixpath.normpath(rel).lstrip("/")
                        if normalized.startswith("..") or normalized == ".":
                            continue

                        target = os.path.abspath(os.path.join(pages_root, *normalized.split("/")))
                        if os.path.commonpath([os.path.abspath(pages_root), target]) != os.path.abspath(pages_root):
                            continue
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        shutil.copy2(full, target)
                shutil.rmtree(raw_root, ignore_errors=True)

            with open(marker, "w", encoding="utf-8") as f:
                f.write("ok")

        pages = []
        for root, _, filenames in os.walk(pages_root):
            for f in filenames:
                ext3 = os.path.splitext(f)[1].lower()
                if ext3 not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                    continue
                full = os.path.join(root, f)
                rel_from_data = os.path.relpath(full, BASE_DIR).replace(os.sep, "/")
                pages.append({"name": f, "path": f"/data/{rel_from_data}"})

        pages.sort(key=lambda p: natural_sort_key(p["path"]))
        return {"pages": pages}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read comic: {e}")


