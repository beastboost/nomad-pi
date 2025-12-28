from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Request, Query, BackgroundTasks
from typing import List, Dict
import os
import posixpath
import re
import shutil
import zipfile
import hashlib
import subprocess
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from collections import OrderedDict
import threading
from app import database

router = APIRouter()

BASE_DIR = "data"
POSTER_CACHE_DIR = os.path.join(BASE_DIR, ".cache", "posters")
INDEX_TTL = timedelta(hours=12)
_index_lock = threading.Lock()
_index_building = {}

# Initialize DB on module load (or main startup)
database.init_db()

def get_scan_paths(category: str):
    paths = [os.path.join(BASE_DIR, category)]
    external_dir = os.path.join(BASE_DIR, "external")
    if os.path.exists(external_dir):
        try:
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
    return paths

def safe_fs_path_from_web_path(web_path: str):
    if not isinstance(web_path, str) or not web_path.startswith("/data/"):
        raise HTTPException(status_code=400, detail="Invalid path")

    rel = posixpath.normpath(web_path[len("/data/"):]).lstrip("/")
    if rel.startswith("..") or rel == ".":
        raise HTTPException(status_code=400, detail="Invalid path")

    base_abs = os.path.abspath(BASE_DIR)
    fs_path = os.path.abspath(os.path.join(BASE_DIR, *rel.split("/")))
    if os.path.commonpath([base_abs, fs_path]) != base_abs:
        raise HTTPException(status_code=400, detail="Invalid path")
    return fs_path

def natural_sort_key(s: str):
    parts = re.split(r'(\d+)', s)
    out = []
    for p in parts:
        if p.isdigit():
            out.append(int(p))
        else:
            out.append(p.lower())
    return out

def guess_title_year(name: str):
    s = os.path.splitext(os.path.basename(name or ""))[0]
    s = re.sub(r'[\._]+', ' ', s)
    s = re.sub(r'[\[\(].*?[\]\)]', ' ', s)
    s = re.sub(r'\b(480p|720p|1080p|2160p|4k|hdr|hevc|x265|x264|h265|h264|aac|ac3|dts|web[- ]dl|webrip|bluray|brrip|dvdrip|remux)\b', ' ', s, flags=re.I)
    s = re.sub(r'\s+', ' ', s).strip()
    year = None
    m = re.search(r'\b(19\d{2}|20\d{2})\b', s)
    if m:
        year = m.group(1)
        s = re.sub(r'\b(19\d{2}|20\d{2})\b', ' ', s).strip()
        s = re.sub(r'\s+', ' ', s).strip()
    return s, year

def normalize_title(s: str):
    s = re.sub(r'[\._]+', ' ', str(s or ''))
    s = re.sub(r'[\W_]+', ' ', s, flags=re.UNICODE)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s

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

def build_library_index(category: str):
    paths_to_scan = get_scan_paths(category)
    count = 0
    batch = []

    database.clear_library_index_category(category)

    poster_cache = OrderedDict()
    poster_cache_max = 2048
    def find_local_poster(dir_path: str):
        if dir_path in poster_cache:
            v = poster_cache.pop(dir_path)
            poster_cache[dir_path] = v
            return v
        candidates = ["poster.jpg", "poster.jpeg", "poster.png", "folder.jpg", "folder.png", "cover.jpg", "cover.png"]
        v = None
        for name in candidates:
            p = os.path.join(dir_path, name)
            if os.path.isfile(p):
                rel_from_data = os.path.relpath(p, BASE_DIR).replace(os.sep, "/")
                v = f"/data/{rel_from_data}"
                break
        poster_cache[dir_path] = v
        if len(poster_cache) > poster_cache_max:
            poster_cache.popitem(last=False)
        return v

    allowed = None
    if category in ['movies', 'shows']:
        allowed = {'.mp4', '.mkv', '.avi', '.mov', '.webm'}
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

                item = {
                    "path": web_path,
                    "category": category,
                    "name": f,
                    "folder": folder,
                    "source": "external" if "external" in rel_path else "local",
                    "poster": find_local_poster(root) if category == "movies" else None,
                    "mtime": float(getattr(st, "st_mtime", 0.0) or 0.0),
                    "size": int(getattr(st, "st_size", 0) or 0),
                }
                batch.append(item)
                if len(batch) >= 100:
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
                        organize_shows(dry_run=False, rename_files=True, limit=50)
                    else:
                        organize_movies(dry_run=False, use_omdb=True, write_poster=True, limit=50)
                except Exception as e:
                    print(f"Auto-organize error for {category}: {e}")
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

    poster_cache = {}
    def find_local_poster(dir_path: str):
        if dir_path in poster_cache:
            return poster_cache[dir_path]
        candidates = ["poster.jpg", "poster.jpeg", "poster.png", "folder.jpg", "folder.png", "cover.jpg", "cover.png"]
        for name in candidates:
            p = os.path.join(dir_path, name)
            if os.path.isfile(p):
                rel_from_data = os.path.relpath(p, BASE_DIR).replace(os.sep, "/")
                poster_cache[dir_path] = f"/data/{rel_from_data}"
                return poster_cache[dir_path]
        poster_cache[dir_path] = None
        return None

    allowed = None
    if category in ['movies', 'shows']:
        allowed = {'.mp4', '.mkv', '.avi', '.mov', '.webm'}
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

                item = {
                    "name": f,
                    "path": web_path,
                    "folder": folder,
                    "type": category,
                    "source": "external" if "external" in rel_path else "local",
                }
                if category == "movies":
                    item["poster"] = find_local_poster(root)

                matched.append(item)
                try:
                    st = os.stat(full_path)
                    database.upsert_library_index_item({
                        "path": web_path,
                        "category": category,
                        "name": f,
                        "folder": folder,
                        "source": item["source"],
                        "poster": item.get("poster"),
                        "mtime": float(getattr(st, "st_mtime", 0.0) or 0.0),
                        "size": int(getattr(st, "st_size", 0) or 0),
                    })
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

@router.get("/meta")
def get_metadata(path: str = Query(...), fetch: bool = Query(default=False), force: bool = Query(default=False), media_type: str = Query(default="movie")):
    if not isinstance(path, str) or not path.startswith("/data/"):
        raise HTTPException(status_code=400, detail="Invalid path")

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
                    return {"configured": True, "cached": True, **cached}
            except Exception:
                pass

    try:
        fs_path = safe_fs_path_from_web_path(path)
    except HTTPException:
        fs_path = None

    title_guess, year_guess = guess_title_year(os.path.basename(fs_path or path))
    try:
        meta = omdb_fetch(title=title_guess, year=year_guess, media_type=media_type)
    except HTTPException as e:
        if e.status_code != 404:
            raise
        search = omdb_search(query=title_guess, year=year_guess, media_type=media_type)
        results = search.get("Search") or []
        if not isinstance(results, list) or not results:
            raise

        want = normalize_title(title_guess)
        best = None
        best_score = -1
        for r in results[:10]:
            t = r.get("Title")
            y = r.get("Year")
            if not t:
                continue
            score = 0
            if normalize_title(t) == want:
                score += 10
            if year_guess and y and str(y).startswith(str(year_guess)):
                score += 5
            if best is None or score > best_score:
                best = r
                best_score = score
        imdb_id = best.get("imdbID") if isinstance(best, dict) else None
        if imdb_id:
            meta = omdb_fetch(imdb_id=imdb_id, media_type=media_type)
        else:
            meta = omdb_fetch(title=title_guess, year=year_guess, media_type=media_type)

    cached_poster = cache_remote_poster(meta.get("Poster"))
    if cached_poster:
        meta["Poster"] = cached_poster
    database.upsert_file_metadata(path, media_type, meta)
    stored = database.get_file_metadata(path)
    return {"configured": True, "cached": True, **(stored or {})}

@router.get("/list_paged/{category}")
def list_media_paged(category: str, offset: int = Query(default=0), limit: int = Query(default=60), q: str = Query(default=""), rebuild: bool = Query(default=False)):
    if category not in ["movies", "shows", "music", "books", "gallery", "files"]:
        raise HTTPException(status_code=400, detail="Invalid category")

    idx_info = maybe_start_index_build(category, force=bool(rebuild))
    items, total = database.query_library_index(category, q, offset, limit)

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
        if category == "movies" and r.get("poster"):
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
    poster_cache = {}

    def find_poster(dir_path: str):
        if dir_path in poster_cache:
            return poster_cache[dir_path]
        candidates = ["poster.jpg", "poster.jpeg", "poster.png", "folder.jpg", "folder.png", "cover.jpg", "cover.png"]
        for name in candidates:
            p = os.path.join(dir_path, name)
            if os.path.isfile(p):
                rel_from_data = os.path.relpath(p, BASE_DIR).replace(os.sep, "/")
                poster_cache[dir_path] = f"/data/{rel_from_data}"
                return poster_cache[dir_path]
        poster_cache[dir_path] = None
        return None

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
                        item["poster"] = find_poster(root)
                    
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
    if path and time is not None:
        database.update_progress(path, time, duration)
    return {"status": "ok"}

@router.post("/rename")
def rename_media(data: Dict = Body(...)):
    old_path = data.get("old_path") or data.get("path")
    new_path = data.get("new_path") or data.get("dest_path")
    if not isinstance(old_path, str) or not old_path.startswith("/data/"):
        raise HTTPException(status_code=400, detail="Invalid old_path")
    if not isinstance(new_path, str) or not new_path.startswith("/data/"):
        raise HTTPException(status_code=400, detail="Invalid new_path")

    old_fs = safe_fs_path_from_web_path(old_path)
    new_fs = safe_fs_path_from_web_path(new_path)

    if not os.path.isfile(old_fs):
        raise HTTPException(status_code=404, detail="File not found")
    if os.path.exists(new_fs):
        raise HTTPException(status_code=409, detail="Destination already exists")

    os.makedirs(os.path.dirname(new_fs), exist_ok=True)
    try:
        shutil.move(old_fs, new_fs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rename failed: {e}")

    try:
        database.rename_media_path(old_path, new_path)
    except Exception:
        pass

    return {"status": "ok", "old_path": old_path, "new_path": new_path}

def _sanitize_show_part(s: str):
    s = re.sub(r"[\._]+", " ", str(s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r'[<>:"/\\\\|?*]', "", s).strip()
    return s

def _infer_show_name_from_filename(path_or_name: str):
    base = os.path.basename(str(path_or_name or ""))
    name = os.path.splitext(base)[0]
    m = re.match(r"^(.*?)(?:\bS\d{1,3}\s*E\d{1,3}\b|\b\d{1,3}x\d{1,3}\b|\bEpisode\s*\d{1,3}\b)", name, flags=re.IGNORECASE)
    if not m or not m.group(1):
        return ""
    cleaned = _sanitize_show_part(m.group(1))
    return cleaned if len(cleaned) >= 2 else ""

def _parse_season_episode(filename: str):
    base = os.path.splitext(os.path.basename(filename or ""))[0]
    m = re.search(r"(?i)\bS(\d{1,3})\s*[\.\-_\s]*\s*E(\d{1,3})\b", base)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(?i)\b(\d{1,3})x(\d{1,3})\b", base)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(?i)\bseason\s*(\d{1,3})\s*[\.\-_\s]*\s*episode\s*(\d{1,3})\b", base)
    if m:
        return int(m.group(1)), int(m.group(2))
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
def organize_shows(dry_run: bool = Query(default=True), rename_files: bool = Query(default=True), limit: int = Query(default=250)):
    base = os.path.join(BASE_DIR, "shows")
    if not os.path.isdir(base):
        raise HTTPException(status_code=404, detail="Shows folder not found")

    limit = max(1, min(int(limit or 250), 5000))
    planned = []
    moved = 0
    skipped = 0
    errors = 0

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
            if len(parts) >= 2:
                first = parts[0]
                first_l = first.lower()
                season_like = first_l.startswith("season") or first_l.startswith("series") or re.match(r"^s\d{1,3}$", first_l or "")
                if not season_like:
                    show_name = first

            if not show_name:
                show_name = _infer_show_name_from_filename(f) or "Unsorted"
            show_name = _sanitize_show_part(show_name) or "Unsorted"

            season_part = parts[1] if len(parts) >= 3 else ""
            season_num, episode_num = _parse_season_episode(f)
            if season_num is None:
                season_num = _infer_season_from_parts([season_part]) or 1
            if episode_num is None:
                episode_num = _parse_episode_only(f)

            season_folder = f"Season {int(season_num)}"
            dest_dir = os.path.join(base, show_name, season_folder)

            dest_name = f
            if rename_files and episode_num is not None:
                dest_name = f"S{int(season_num):02d}E{int(episode_num):02d}{ext}"

            dest_fs = os.path.join(dest_dir, dest_name)
            dest_fs = _pick_unique_dest(dest_fs) if not dry_run else dest_fs

            if os.path.abspath(src_fs) == os.path.abspath(dest_fs):
                skipped += 1
                continue

            plan = {"from": f"/data/shows/{rel_under}", "to": f"/data/shows/{os.path.relpath(dest_fs, base).replace(os.sep, '/')}"}
            planned.append(plan)

            if dry_run:
                if len(planned) >= limit:
                    break
                continue

            if os.path.exists(dest_fs):
                errors += 1
                continue

            os.makedirs(dest_dir, exist_ok=True)
            try:
                shutil.move(src_fs, dest_fs)
                print(f"Organized show file: {src_fs} -> {dest_fs}")
            except Exception as e:
                print(f"Failed to move show file {src_fs}: {e}")
                errors += 1
                continue

            try:
                database.rename_media_path(plan["from"], plan["to"])
            except Exception:
                pass

            moved += 1
            if moved >= limit:
                break
        if (dry_run and len(planned) >= limit) or ((not dry_run) and moved >= limit):
            break

    return {"status": "ok", "dry_run": bool(dry_run), "rename_files": bool(rename_files), "moved": moved, "skipped": skipped, "errors": errors, "planned": planned[: min(len(planned), 1000)]}

@router.post("/organize/movies")
def organize_movies(dry_run: bool = Query(default=True), use_omdb: bool = Query(default=True), write_poster: bool = Query(default=True), limit: int = Query(default=250)):
    base = os.path.join(BASE_DIR, "movies")
    if not os.path.isdir(base):
        raise HTTPException(status_code=404, detail="Movies folder not found")

    limit = max(1, min(int(limit or 250), 5000))
    planned = []
    moved = 0
    skipped = 0
    errors = 0

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
            title = title_guess
            year = year_guess
            meta = None
            if use_omdb and (os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")):
                try:
                    meta = omdb_fetch(title=title_guess, year=year_guess, media_type="movie")
                    t = meta.get("Title")
                    y = meta.get("Year")
                    if isinstance(t, str) and t.strip():
                        title = t.strip()
                    if isinstance(y, str) and y.strip():
                        year = y.strip()
                except Exception:
                    meta = None

            title = _sanitize_movie_part(title) or "Movie"
            folder = f"{title} ({year})" if year else title
            folder = _sanitize_movie_part(folder) or title
            dest_dir = os.path.join(base, folder)
            dest_name = f"{folder}{ext}"
            dest_fs = os.path.join(dest_dir, dest_name)

            if os.path.abspath(src_fs) == os.path.abspath(dest_fs):
                skipped += 1
                continue

            plan = {"from": f"/data/movies/{rel_under}", "to": f"/data/movies/{folder}/{dest_name}"}
            planned.append(plan)

            if dry_run:
                if len(planned) >= limit:
                    break
                continue

            os.makedirs(dest_dir, exist_ok=True)
            dest_fs = _pick_unique_dest(dest_fs)

            try:
                shutil.move(src_fs, dest_fs)
                print(f"Organized movie file: {src_fs} -> {dest_fs}")
            except Exception as e:
                print(f"Failed to move movie file {src_fs}: {e}")
                errors += 1
                continue

            to_web = f"/data/movies/{os.path.relpath(dest_fs, base).replace(os.sep, '/')}"
            try:
                database.rename_media_path(plan["from"], to_web)
            except Exception:
                pass

            if meta and write_poster:
                try:
                    cached = cache_remote_poster(meta.get("Poster"))
                    if cached and cached.startswith("/data/"):
                        meta["Poster"] = cached
                        cached_fs = safe_fs_path_from_web_path(cached)
                        poster_out = os.path.join(dest_dir, "poster.jpg")
                        if os.path.isfile(cached_fs) and not os.path.exists(poster_out):
                            shutil.copy2(cached_fs, poster_out)
                except Exception:
                    pass

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

    return {"status": "ok", "dry_run": bool(dry_run), "use_omdb": bool(use_omdb), "write_poster": bool(write_poster), "moved": moved, "skipped": skipped, "errors": errors, "planned": planned[: min(len(planned), 1000)]}

@router.post("/upload/{category}")
async def upload_file(category: str, files: UploadFile = File(...)):
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
    
    return {"info": f"Uploaded {len(saved_files)} files to {category}", "files": saved_files}

import aiofiles

@router.post("/upload_stream/{category}")
async def upload_stream(category: str, request: Request, path: str = Query(default="")):
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
            # Buffer 1MB to reduce context switching overhead
            buffer = bytearray()
            buffer_size = 1024 * 1024
            async for chunk in request.stream():
                buffer.extend(chunk)
                if len(buffer) >= buffer_size:
                    await out.write(buffer)
                    buffer = bytearray()
            if buffer:
                await out.write(buffer)
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

    return {"info": "Uploaded 1 file", "files": [dest_rel]}

@router.delete("/delete")
def delete_media(path: str):
    fs_path = safe_fs_path_from_web_path(path)
    if not os.path.exists(fs_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        if os.path.isdir(fs_path):
            shutil.rmtree(fs_path)
        else:
            os.remove(fs_path)
            
        # Clean up database
        database.delete_library_index_item(path)
        
        # If it's a media file, check if we should remove the parent folder if empty
        parent = os.path.dirname(fs_path)
        if os.path.exists(parent) and not os.listdir(parent) and parent != BASE_DIR:
            try:
                os.rmdir(parent)
            except:
                pass
                
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

@router.post("/scan")
def scan_library(background_tasks: BackgroundTasks):
    def run_scan():
        # Scan all categories
        for cat in ["movies", "shows", "music", "books", "gallery", "files"]:
             try:
                 build_library_index(cat)
             except Exception as e:
                 print(f"Scan error {cat}: {e}")
    background_tasks.add_task(run_scan)
    return {"status": "ok", "message": "Library scan started in background."}

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
        items.append({"name": name, "path": web_path, "type": media_type, "progress": prog})

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


@router.get("/shows/library")
def shows_library():
    all_progress = database.get_all_progress()
    shows: Dict[str, Dict[str, List[Dict]]] = {}

    def parse_season_number(season: str):
        m = re.search(r'(?i)(?:season|series)\s*(\d{1,3})', season)
        if m:
            return int(m.group(1))
        m = re.search(r'(?i)\bs(\d{1,3})\b', season)
        if m:
            return int(m.group(1))
        m = re.search(r'(\d{1,3})', season)
        if m:
            return int(m.group(1))
        return None

    def parse_episode_number(filename: str):
        _, ep = _parse_season_episode(filename)
        if ep is not None:
            return ep
        return _parse_episode_only(filename)

    paths_to_scan = get_scan_paths("shows")
    show_poster_cache: Dict[str, str] = {}

    def find_show_poster(show_name: str):
        if show_name in show_poster_cache:
            return show_poster_cache[show_name]
        candidates = ["poster.jpg", "poster.jpeg", "poster.png", "folder.jpg", "folder.png", "cover.jpg", "cover.png"]
        for base in paths_to_scan:
            show_dir = os.path.join(base, show_name)
            if not os.path.isdir(show_dir):
                continue
            for name in candidates:
                p = os.path.join(show_dir, name)
                if os.path.isfile(p):
                    rel_from_data = os.path.relpath(p, BASE_DIR).replace(os.sep, "/")
                    show_poster_cache[show_name] = f"/data/{rel_from_data}"
                    return show_poster_cache[show_name]
        show_poster_cache[show_name] = None
        return None

    idx_info = maybe_start_index_build("shows", force=False)
    offset = 0
    limit = 500
    total = 0
    while True:
        rows, total = database.query_library_index("shows", "", offset, limit)
        if not rows:
            break
        for r in rows:
            web_path = r.get("path")
            if not web_path:
                continue
            folder = (r.get("folder") or ".").replace("\\", "/")
            name = r.get("name") or os.path.basename(web_path)

            folder_parts = [p for p in folder.split("/") if p and p != "."]
            if len(folder_parts) >= 2:
                show_name = folder_parts[0]
                season_name = folder_parts[1]
            elif len(folder_parts) == 1:
                show_name = folder_parts[0]
                season_name = "Season 1"
            else:
                show_name = "Unsorted"
                season_name = "Season 1"

            episode = {
                "name": name,
                "path": web_path,
                "folder": folder if folder else ".",
                "source": r.get("source") or ("external" if "external" in (web_path or "") else "local"),
                "episode_number": parse_episode_number(name),
            }
            if web_path in all_progress:
                episode["progress"] = all_progress[web_path]
            shows.setdefault(show_name, {}).setdefault(season_name, []).append(episode)
        offset += len(rows)
        if offset >= int(total or 0):
            break

    if not shows and int(total or 0) == 0:
        for path in paths_to_scan:
            if not os.path.exists(path):
                continue
            for root, _, filenames in os.walk(path):
                for f in filenames:
                    if f.startswith('.'):
                        continue
                    ext = f.split('.')[-1].lower()
                    if ext not in ['mp4', 'mkv', 'avi', 'mov', 'webm']:
                        continue

                    full_path = os.path.join(root, f)
                    rel_under_category = os.path.relpath(full_path, path).replace(os.sep, "/")
                    parts = [p for p in rel_under_category.split("/") if p]

                    if len(parts) >= 3:
                        show_name = parts[0]
                        season_name = parts[1]
                    elif len(parts) == 2:
                        show_name = parts[0]
                        season_name = "Season 1"
                    else:
                        show_name = "Unsorted"
                        season_name = "Season 1"

                    rel_from_data = os.path.relpath(full_path, BASE_DIR).replace(os.sep, "/")
                    web_path = f"/data/{rel_from_data}"

                    episode = {
                        "name": f,
                        "path": web_path,
                        "folder": "/".join(parts[:-1]) if len(parts) > 1 else ".",
                        "source": "external" if "external" in rel_from_data else "local",
                        "episode_number": parse_episode_number(f)
                    }
                    if web_path in all_progress:
                        episode["progress"] = all_progress[web_path]

                    shows.setdefault(show_name, {}).setdefault(season_name, []).append(episode)

    library = []
    for show_name in sorted(shows.keys(), key=lambda s: s.lower()):
        seasons = []
        season_items = []
        for season_name in shows[show_name].keys():
            season_items.append((parse_season_number(season_name), season_name))

        season_items.sort(key=lambda t: (t[0] is None, t[0] or 0, t[1].lower()))
        for season_number, season_name in season_items:
            episodes = sorted(
                shows[show_name][season_name],
                key=lambda e: (e.get("episode_number") is None, e.get("episode_number") or 0, e["name"].lower())
            )
            seasons.append({"name": season_name, "season_number": season_number, "episodes": episodes})
        library.append({"name": show_name, "poster": find_show_poster(show_name) if show_name != "Unsorted" else None, "seasons": seasons})

    return {"shows": library, "index": idx_info}
