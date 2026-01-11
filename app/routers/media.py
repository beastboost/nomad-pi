from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Request, Query, BackgroundTasks, Depends
from app.routers.auth import get_current_user_id
from fastapi.responses import FileResponse
from pydantic import BaseModel, validator
from typing import List, Dict, Optional
import os
import posixpath
import pathlib
import platform
import re
import shutil
import zipfile
import hashlib
import subprocess
import json
import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from collections import OrderedDict
from functools import lru_cache
from hashlib import md5
import threading
import shutil
from app import database

logger = logging.getLogger(__name__)

router = APIRouter()
public_router = APIRouter()

BASE_DIR = os.path.abspath("data")
POSTER_CACHE_DIR = os.path.join(BASE_DIR, "cache", "posters")
os.makedirs(POSTER_CACHE_DIR, exist_ok=True)

@lru_cache(maxsize=100)
def _get_paged_data_cached(category: str, q: str, offset: int, limit: int, sort: str, genre: str, year: str, user_id: int):
    """Internal cached version of paged data retrieval"""
    return _get_paged_data(category, q, offset, limit, sort, genre, year, False, user_id)

def _get_paged_data(category: str, q: str, offset: int, limit: int, sort: str, genre: str, year: str, rebuild: bool, user_id: int):
    idx_info = maybe_start_index_build(category, force=bool(rebuild))
    items, total = database.query_library_index(category, q, offset, limit, sort=sort, genre=genre, year=year, user_id=user_id)

    all_progress = database.get_all_progress(user_id)
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

INDEX_TTL = timedelta(hours=12)
_index_lock = threading.Lock()
_index_building = {}

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
        for mount_root in ["/media/pi", "/media", "/mnt"]:
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

                             # Check for category folder with more synonyms
                             synonyms = [category, category.capitalize(), category.upper()]
                             if category == "shows":
                                 synonyms += ["TV Shows", "TV", "Series", "TV Series", "tvshows", "tv"]
                             elif category == "movies":
                                 synonyms += ["Films", "Cinema", "My Movies", "movies"]
                             elif category == "music":
                                 synonyms += ["My Music", "Audio", "Songs"]
                             elif category == "books":
                                 synonyms += ["Comics", "Ebooks", "Magazines"]

                             found_cat = False
                             for cat_name in synonyms:
                                cat_path = os.path.join(base_to_use, cat_name)
                                if os.path.exists(cat_path):
                                    if cat_path not in paths:
                                        paths.append(cat_path)
                                    found_cat = True
                                    break
                             
                             # If no category folder found, but the drive name matches the category, scan the whole drive
                             if not found_cat:
                                 drive_lower = drive.lower()
                                 if category in drive_lower or (category == "shows" and ("tv" in drive_lower or "series" in drive_lower)):
                                     if base_to_use not in paths:
                                         paths.append(base_to_use)
                except Exception:
                    pass
    return paths

def safe_fs_path_from_web_path(web_path: str):
    if not isinstance(web_path, str) or not web_path:
        raise HTTPException(status_code=400, detail="Invalid path")

    # 1. Handle absolute paths for Windows (e.g., C:/...)
    if platform.system() == "Windows" and len(web_path) >= 2 and web_path[1] == ":":
        p = pathlib.Path(web_path).resolve()
        # For Windows, we still want to ensure it's within a known media drive or the app's data dir
        # For simplicity, we check if it's within BASE_DIR or if it's an absolute path that exists.
        # But to be secure, we should only allow specific roots.
        # Let's check if it's within BASE_DIR or an allowed external root.
        base_abs = pathlib.Path(BASE_DIR).resolve()
        try:
            p.relative_to(base_abs)
            return str(p)
        except ValueError:
            # Check external drives symlinked in data/external
            ext_root = base_abs / "external"
            if ext_root.exists():
                for item in ext_root.iterdir():
                    if item.is_symlink():
                        target = item.resolve()
                        try:
                            p.relative_to(target)
                            return str(p)
                        except ValueError:
                            continue
            raise HTTPException(status_code=400, detail="Access denied to external path")

    # 2. Handle Linux absolute paths to /media and /mnt
    if platform.system() == "Linux" and (web_path.startswith("/media") or web_path.startswith("/mnt")):
        p = pathlib.Path(web_path).resolve()
        if any(str(p).startswith(prefix) for prefix in ["/media", "/mnt"]):
            return str(p)
        raise HTTPException(status_code=400, detail="Access denied to system path")

    # 3. Standard /data/ paths
    if not web_path.startswith("/data/"):
        raise HTTPException(status_code=400, detail="Invalid path format")

    rel = posixpath.normpath(web_path[len("/data/"):]).lstrip("/")
    
    # SPECIAL HANDLING FOR EXTERNAL DRIVES ON LINUX
    # If the path starts with "external/" but the symlink doesn't exist, 
    # try to map it directly to /media/pi/ or /media/
    if platform.system() == "Linux" and rel.startswith("external/"):
        parts = rel.split("/")
        if len(parts) >= 2:
            drive_name = parts[1]
            rest = "/".join(parts[2:])
            for mount_root in ["/media/pi", "/media", "/mnt"]:
                potential_path = os.path.join(mount_root, drive_name, rest)
                if os.path.exists(potential_path):
                    return potential_path

    if rel.startswith("..") or rel == ".":
        raise HTTPException(status_code=400, detail="Invalid path traversal")

    base_abs = pathlib.Path(BASE_DIR).resolve()
    fs_path = (base_abs / rel).resolve()
    
    # Check if the resolved path is within the base directory
    try:
        fs_path.relative_to(base_abs)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path - traversal detected")
        
    return str(fs_path)

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
    year = None
    # Look for year preceded by space, dot, underscore or bracket
    m = re.search(r'[\s\.\(\[_\-](19\d{2}|20\d{2})[\s\.\)\]_\-]', s)
    if not m:
        # Fallback to year at end of string
        m = re.search(r'[\s\.\(\[_\-](19\d{2}|20\d{2})$', s)
    
    if m:
        year = m.group(1)
        # Title is everything before the year
        title_part = s[:m.start()]
    else:
        title_part = s

    # 4. Final cleanup of title
    # We DON'T call os.path.splitext(title_part) here because title_part is already 
    # derived from s (which had the extension removed at the start). 
    # Calling it again would treat dots in titles (like 'Big.Mouth') as extensions!
    title = title_part
    
    # Remove quality/source tags from the title part
    for tag in tags:
        title = re.sub(rf'\b{tag}\b', ' ', title, flags=re.I)
    
    # Preserve hyphens if they are part of words (e.g. Kick-Ass)
    # But remove them if they are separators (e.g. Title - Quality)
    title = re.sub(r'(?<![a-zA-Z0-9])[\-_]+|[\-_]+(?![a-zA-Z0-9])', ' ', title)
    
    # Replace dots/underscores with spaces
    title = re.sub(r'[\._]+', ' ', title)
    
    # Remove empty brackets/parentheses
    title = re.sub(r'[\(\[\{]\s*[\)\]\}]', ' ', title)
    # Remove content within brackets/parentheses if it looks like junk (tags)
    title = re.sub(r'[\(\[\{][^a-zA-Z0-9]*[a-zA-Z0-9]+[^a-zA-Z0-9]*[\)\]\}]', lambda m: ' ' if any(t in m.group(0).lower() for t in tags) else m.group(0), title)

    # Final trim and space normalization
    title = re.sub(r'\s+', ' ', title).strip(' -_()[]')
    
    # Special case: If title became empty or too short, revert to original filename (sans extension)
    if len(title) < 2:
        title = os.path.splitext(title_part)[0].strip()

    return title, year

def normalize_title(s: str):
    s = re.sub(r'[\._]+', ' ', str(s or ''))
    s = re.sub(r'[\W_]+', ' ', s, flags=re.UNICODE)
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s

def _strip_show_root_prefix(folder: str) -> str:
    parts = [p for p in (folder or "").split("/") if p and p != "."]
    if not parts:
        return "."
    synonyms = {
        "shows", "show", "tv shows", "tv", "series", "tv series", "tvshows", "television", "telly",
        "media",
    }
    lowered = [p.strip().lower() for p in parts]
    cut = None
    for i, seg in enumerate(lowered):
        if seg in synonyms:
            cut = i + 1
            break
    if cut is not None:
        parts = parts[cut:]
    return "/".join(parts) if parts else "."

def _guess_show_dir_from_episode_path(ep_fs: str) -> str:
    season_dir = os.path.dirname(ep_fs)
    base = os.path.basename(season_dir).strip().lower()
    if re.match(r"^(season|series)\s*\d{1,3}$", base) or re.match(r"^s\d{1,3}$", base) or base in {"specials", "extra", "extras"}:
        return os.path.dirname(season_dir)
    return season_dir

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
                v = fs_path_to_web_path(p)
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

async def omdb_fetch(title: str = None, year: str = None, imdb_id: str = None, media_type: str = None):
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

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("https://www.omdbapi.com/", params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"OMDb request failed: {e}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="Invalid OMDb response")

    if str(data.get("Response") or "").lower() == "false":
        raise HTTPException(status_code=404, detail=str(data.get("Error") or "Not found"))
    return data

async def omdb_search(query: str, year: str = None, media_type: str = None):
    api_key = os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="OMDb not configured")

    params = {"apikey": api_key, "s": query}
    if year:
        params["y"] = str(year)
    if media_type:
        params["type"] = media_type

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("https://www.omdbapi.com/", params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"OMDb request failed: {e}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="Invalid OMDb response")

    if str(data.get("Response") or "").lower() == "false":
        raise HTTPException(status_code=404, detail=str(data.get("Error") or "Not found"))
    return data

async def cache_remote_poster(poster_url: str):
    if not poster_url or poster_url == "N/A":
        return None
    
    # Basic URL validation
    if not (poster_url.startswith("http://") or poster_url.startswith("https://")):
        return None

    os.makedirs(POSTER_CACHE_DIR, exist_ok=True)
    key = hashlib.sha256(poster_url.encode("utf-8", errors="ignore")).hexdigest()
    out_fs = os.path.join(POSTER_CACHE_DIR, f"{key}.jpg")
    
    if os.path.isfile(out_fs) and os.path.getsize(out_fs) > 0:
        rel = os.path.relpath(out_fs, BASE_DIR).replace(os.sep, "/")
        return f"/data/{rel}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(poster_url, timeout=10.0, headers={"User-Agent": "NomadPi/1.0"})
            response.raise_for_status()
            data = response.content
            if len(data) > 5_000_000: # Limit to 5MB
                return None
        except Exception:
            return None

    try:
        # Use aiofiles if we want to be fully async, but for small files this is okay
        with open(out_fs, "wb") as f:
            f.write(data)
    except Exception:
        return None

    rel = os.path.relpath(out_fs, BASE_DIR).replace(os.sep, "/")
    return f"/data/{rel}"

@router.get("/shows/library")
async def get_shows_library(user_id: int = Depends(get_current_user_id)):
    items, total = database.query_library_index("shows", limit=1000000, user_id=user_id)
    all_progress = database.get_all_progress(user_id)
    
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
                "genres": set(),
                "years": set(),
                "mtime": 0,
                "path": os.path.join("/data/shows", show_name).replace(os.sep, '/'),
                "_sample_path": web_path
            }
        
        # Aggregate genres and years
        if r.get("genre"):
            for g in r.get("genre").split(','):
                shows_dict[show_name]["genres"].add(g.strip())
        if r.get("year"):
            shows_dict[show_name]["years"].add(str(r.get("year")))
        
        # Track most recent modification time
        mtime = r.get("mtime") or 0
        if mtime > shows_dict[show_name]["mtime"]:
            shows_dict[show_name]["mtime"] = mtime
        
        # Track last played
        prog = all_progress.get(web_path)
        if prog and prog.get("last_played"):
            lp = prog.get("last_played")
            if not shows_dict[show_name].get("last_played") or lp > shows_dict[show_name]["last_played"]:
                shows_dict[show_name]["last_played"] = lp

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

    show_poster_cache = {}
    omdb_configured = bool(os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY"))
    for show_name, show in shows_dict.items():
        if show.get("poster"):
            continue

        sample = show.get("_sample_path")
        if not isinstance(sample, str) or not sample.startswith("/data/"):
            continue

        if sample in show_poster_cache:
            show["poster"] = show_poster_cache[sample]
            continue

        show_title = show_name
        show_year = None
        m = re.search(r"\((\d{4})\)", show_title)
        if m:
            show_year = m.group(1)
            show_title = show_title.replace(m.group(0), "").strip()
        show_title = re.sub(r"\s+", " ", show_title).strip()

        try:
            ep_fs = safe_fs_path_from_web_path(sample)
            show_dir_fs = _guess_show_dir_from_episode_path(ep_fs)
        except Exception:
            continue

        p = find_local_poster(show_dir_fs)
        if not p and omdb_configured and show_title != "Unsorted":
            meta = None
            try:
                try:
                    meta = await omdb_fetch(title=show_title, year=show_year, media_type="series")
                except Exception:
                    search = await omdb_search(query=show_title, year=show_year, media_type="series")
                    results = search.get("Search") or []
                    if results:
                        best = results[0]
                        best_score = _get_similarity(show_title, best.get("Title", ""))
                        for r in results:
                            score = _get_similarity(show_title, r.get("Title", ""))
                            if score > best_score:
                                best_score = score
                                best = r
                        if best_score > 0.5 and best.get("imdbID"):
                            meta = await omdb_fetch(imdb_id=best.get("imdbID"), media_type="series")
            except Exception:
                meta = None

            if meta and meta.get("Poster") and meta.get("Poster") != "N/A":
                cached = await cache_remote_poster(meta["Poster"])
                if cached:
                    try:
                        poster_dest = os.path.join(show_dir_fs, "poster.jpg")
                        cached_fs = safe_fs_path_from_web_path(cached)
                        if os.path.isfile(cached_fs):
                            os.makedirs(os.path.dirname(poster_dest), exist_ok=True)
                            shutil.copy2(cached_fs, poster_dest)
                            p = fs_path_to_web_path(poster_dest)
                    except Exception:
                        p = cached

        if p:
            show["poster"] = p
            for season in show.get("seasons", {}).values():
                if season and not season.get("poster"):
                    season["poster"] = p
            show_poster_cache[sample] = p
        
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
        # Convert sets to sorted lists
        show["genres"] = sorted(list(show.get("genres", [])))
        show["years"] = sorted(list(show.get("years", [])))
        show.pop("_sample_path", None)
        out.append(show)
        
    return {"shows": out}

@router.get("/shows/next")
def get_next_show_episode(path: str = Query(...), user_id: int = Depends(get_current_user_id)):
    if not isinstance(path, str) or "/shows/" not in path:
        return {"next": None}

    def parse_ep_num(name: str) -> int:
        if not name:
            return 999
        m = re.search(r"(?i)\bE(\d{1,3})\b", name)
        if m:
            return int(m.group(1))
        m = re.search(r"(?i)\b\d+x(\d{1,3})\b", name)
        if m:
            return int(m.group(1))
        m = re.search(r"(?i)S\d{1,3}E(\d{1,3})\b", name)
        if m:
            return int(m.group(1))
        m = re.search(r"(?i)\b(\d{1,3})\b", name)
        if m:
            return int(m.group(1))
        return 999

    def parse_season_num(season_name: str) -> int:
        if not season_name:
            return 0
        m = re.search(r"(?i)\b(?:season|series)\s*(\d{1,3})\b", season_name)
        if m:
            return int(m.group(1))
        m = re.search(r"(?i)\bs(\d{1,3})\b", season_name)
        if m:
            return int(m.group(1))
        m = re.search(r"(\d{1,3})", season_name)
        if m:
            return int(m.group(1))
        return 0

    conn = database.get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT path, name, folder, poster FROM library_index WHERE category = 'shows' AND path = ? LIMIT 1",
            (path,),
        )
        cur = c.fetchone()
        if not cur:
            return {"next": None}

        folder = (cur.get("folder") or "").strip()
        parts = folder.split("/") if folder else []
        show_name = parts[0] if len(parts) >= 1 else ""
        season_name = parts[1] if len(parts) >= 2 else ""
        if not show_name or not folder:
            return {"next": None}

        current_ep = parse_ep_num(cur.get("name") or "")

        c.execute(
            "SELECT path, name, poster FROM library_index WHERE category = 'shows' AND folder = ?",
            (folder,),
        )
        season_rows = [dict(r) for r in c.fetchall()]
        season_eps = [
            {
                "name": r.get("name"),
                "path": r.get("path"),
                "poster": r.get("poster"),
                "ep_num": parse_ep_num(r.get("name") or ""),
            }
            for r in season_rows
        ]
        season_eps.sort(key=lambda x: (x["ep_num"], database.natural_sort_key_list(x.get("name") or "")))

        cur_index = next((i for i, ep in enumerate(season_eps) if ep.get("path") == path), -1)
        if cur_index == -1:
            cur_index = next((i for i, ep in enumerate(season_eps) if ep.get("ep_num") == current_ep), -1)

        if 0 <= cur_index < len(season_eps) - 1:
            next_ep = season_eps[cur_index + 1]
            next_ep["show"] = show_name
            next_ep["season"] = season_name
            return {"next": next_ep}

        c.execute(
            "SELECT DISTINCT folder FROM library_index WHERE category = 'shows' AND folder LIKE ?",
            (f"{show_name}/%",),
        )
        season_folders = [r["folder"] for r in c.fetchall() if r.get("folder")]
        seasons = []
        for f in season_folders:
            f_parts = f.split("/")
            if len(f_parts) < 2:
                continue
            s_name = f_parts[1]
            seasons.append(
                {
                    "folder": f,
                    "season": s_name,
                    "season_num": parse_season_num(s_name),
                }
            )

        if not seasons:
            return {"next": None}

        seasons.sort(key=lambda s: (s["season_num"], database.natural_sort_key_list(s["season"])))
        cur_season_num = parse_season_num(season_name)
        next_season = None
        for s in seasons:
            if s["folder"] == folder:
                continue
            if s["season_num"] > cur_season_num:
                next_season = s
                break

        if not next_season:
            return {"next": None}

        c.execute(
            "SELECT path, name, poster FROM library_index WHERE category = 'shows' AND folder = ?",
            (next_season["folder"],),
        )
        next_rows = [dict(r) for r in c.fetchall()]
        next_eps = [
            {
                "name": r.get("name"),
                "path": r.get("path"),
                "poster": r.get("poster"),
                "ep_num": parse_ep_num(r.get("name") or ""),
            }
            for r in next_rows
        ]
        next_eps.sort(key=lambda x: (x["ep_num"], database.natural_sort_key_list(x.get("name") or "")))
        if not next_eps:
            return {"next": None}

        first = next_eps[0]
        first["show"] = show_name
        first["season"] = next_season["season"]
        return {"next": first}
    finally:
        database.return_db(conn)

@router.get("/stats")
def get_media_stats(user_id: int = Depends(get_current_user_id)):
    stats = {
        "movies": 0,
        "shows": 0,
        "music": 0,
        "books": 0
    }
    
    for category in stats.keys():
        try:
            # Check library index
            items, total = database.query_library_index(category, limit=1, user_id=user_id)
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
def rebuild_library(background_tasks: BackgroundTasks, user_id: int = Depends(get_current_user_id)):
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
                    # Check if full_path is within BASE_DIR
                    abs_full = os.path.abspath(full_path)
                    abs_base_dir = os.path.abspath(BASE_DIR)
                    
                    if abs_full.startswith(abs_base_dir):
                        rel_path = os.path.relpath(full_path, BASE_DIR)
                        url_path = rel_path.replace(os.sep, '/')
                        web_path = f"/data/{url_path}"
                    else:
                        # Outside BASE_DIR (e.g. external drive)
                        # Find which drive it's on
                        drive_info = None
                        for mount_root in ["/media/pi", "/media", "/mnt"]:
                            if full_path.startswith(mount_root):
                                rel_to_mount = os.path.relpath(full_path, mount_root)
                                parts = rel_to_mount.split(os.sep)
                                drive_name = parts[0]
                                rest = os.path.join(*parts[1:]) if len(parts) > 1 else ""
                                web_path = f"/data/external/{drive_name}/{rest}".replace(os.sep, '/')
                                drive_info = True
                                break
                        
                        if not drive_info:
                            # Fallback to relpath if possible, though it might have ..
                            rel_path = os.path.relpath(full_path, BASE_DIR)
                            url_path = rel_path.replace(os.sep, '/')
                            web_path = f"/data/{url_path}"
                        
                        # Ensure rel_path is defined even for external drives
                        # We use the web_path (minus the /data/ prefix) as a virtual rel_path
                        rel_path = web_path.replace("/data/", "").replace("/", os.sep)
                except Exception as e:
                    logger.error(f"Error calculating paths for {full_path}: {e}")
                    continue

                try:
                    # Smarter folder calculation for 'shows'
                    rel_folder = os.path.relpath(root, base).replace(os.sep, '/')
                    
                    if category == "shows":
                        base_name = os.path.basename(base)
                        synonyms = ["shows", "tv shows", "tv", "series", "tv series", "tvshows", "media", "external"]
                        if base_name.lower() not in synonyms:
                            if rel_folder == ".":
                                folder = base_name
                            else:
                                folder = f"{base_name}/{rel_folder}"
                        else:
                            folder = rel_folder
                        folder = _strip_show_root_prefix(folder)
                    else:
                        folder = rel_folder
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

                # Priority 4: Database-cached poster (from previous OMDb fetches)
                if not p_url:
                    meta = database.get_file_metadata(web_path)
                    if meta and meta.get("poster"):
                        p_url = meta.get("poster")
                    elif meta and meta.get("meta"):
                        # Check nested OMDB data if available
                        m_data = meta.get("meta")
                        if isinstance(m_data, dict) and m_data.get("Poster") and m_data["Poster"] != "N/A":
                            p_url = m_data["Poster"]

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
    
    # On low-resource Pi Zero, we ONLY want to build if:
    # 1. User explicitly requested it (force=True)
    # 2. The index is completely empty (state is None or item_count is 0)
    # We DO NOT want to build automatically on a timer as it kills performance.
    
    has_items = state and state.get("item_count", 0) > 0
    
    if has_items and not force:
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
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    if category == "shows":
                        loop.run_until_complete(organize_shows(dry_run=False, rename_files=True, use_omdb=True, write_poster=True, limit=50))
                    else:
                        loop.run_until_complete(organize_movies(dry_run=False, use_omdb=True, write_poster=True, limit=50))
                except Exception as e:
                    logger.error(f"Auto-organize error for {category}: {e}")
        finally:
            with _index_lock:
                _index_building[category] = False
            # Clear cache after rebuild
            _get_paged_data_cached.cache_clear()

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
                web_path = None
                rel_path = None
                try:
                    web_path = fs_path_to_web_path(full_path)
                except Exception:
                    web_path = None

                if isinstance(web_path, str) and web_path.startswith("/data/"):
                    rel_path = web_path.replace("/data/", "").replace("/", os.sep)
                else:
                    try:
                        rel_path = os.path.relpath(full_path, BASE_DIR)
                        if rel_path.startswith(".."):
                            continue
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
def get_genres(category: str = Query(...), user_id: int = Depends(get_current_user_id)):
    return database.get_unique_genres(category)

@router.get("/years")
def get_years(category: str = Query(...), user_id: int = Depends(get_current_user_id)):
    return database.get_unique_years(category)

@router.post("/play_count")
def increment_play_count(path: str = Body(..., embed=True), user_id: int = Depends(get_current_user_id)):
    database.increment_play_count(user_id, path)
    return {"status": "success"}

@router.get("/similar")
def get_similar_media(path: str = Query(...), user_id: int = Depends(get_current_user_id)):
    """Get similar media items for a given path."""
    items = database.get_similar_media(path)
    # Add progress information for the user
    all_progress = database.get_all_progress(user_id)
    for item in items:
        if item['path'] in all_progress:
            item['progress'] = all_progress[item['path']]
    return items

@router.get("/library/{category}")
def get_library(
    category: str, 
    q: str = Query(default=None), 
    offset: int = Query(default=0), 
    limit: int = Query(default=50),
    sort: str = Query(default='name'),
    genre: str = Query(default=None),
    year: str = Query(default=None),
    user_id: int = Depends(get_current_user_id)
):
    # Handle FastAPI Query objects if passed directly in tests
    if hasattr(q, 'default'): q = q.default
    if hasattr(offset, 'default'): offset = offset.default
    if hasattr(limit, 'default'): limit = limit.default
    if hasattr(sort, 'default'): sort = sort.default
    if hasattr(genre, 'default'): genre = genre.default
    if hasattr(year, 'default'): year = year.default

    # Ensure integer types for numeric params
    try:
        offset = int(offset or 0)
        limit = int(limit or 50)
    except (ValueError, TypeError):
        offset = 0
        limit = 50

    # Validation
    allowed_categories = ['movies', 'shows', 'music', 'books', 'gallery', 'files']
    if category not in allowed_categories:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
        
    allowed_sorts = ['name', 'newest', 'oldest', 'year_desc', 'year_asc', 'recently_played', 'top_watched']
    if sort not in allowed_sorts:
        sort = 'name'

    # Try to use database index if available
    try:
        if category == 'shows':
            items, total = database.query_shows(q=q, offset=offset, limit=limit, sort=sort, genre=genre, year=year, user_id=user_id)
        else:
            items, total = database.query_library_index(category, q=q, offset=offset, limit=limit, sort=sort, genre=genre, year=year, user_id=user_id)
            
        if total > 0 or q or genre or year:
            # Add progress information for the user
            all_progress = database.get_all_progress(user_id)
            for item in items:
                if item.get('path') in all_progress:
                    item['progress'] = all_progress[item['path']]

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
    
    # Add progress information even for filesystem results if possible
    try:
        all_progress = database.get_all_progress(user_id)
        for item in items:
            if item.get('path') in all_progress:
                item['progress'] = all_progress[item['path']]
    except Exception:
        pass

    return {
        "items": items, 
        "total": len(items), 
        "next_offset": offset + len(items),
        "has_more": len(items) >= limit,
        "source": "filesystem"
    }

def fs_path_to_web_path(fs_path: str) -> str:
    """Convert a filesystem path back to a web path."""
    base_abs = os.path.abspath(BASE_DIR)
    fs_abs = os.path.abspath(fs_path)
    
    if fs_abs.startswith(base_abs):
        rel_path = os.path.relpath(fs_abs, base_abs).replace(os.sep, "/")
        return f"/data/{rel_path}"

    if platform.system() == "Linux":
        ext_root = os.path.join(base_abs, "external")
        if fs_abs.startswith(os.path.abspath(ext_root) + os.sep):
            rel = os.path.relpath(fs_abs, ext_root).replace(os.sep, "/")
            parts = rel.split("/", 1)
            drive = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            return f"/data/external/{drive}/{rest}".rstrip("/")

        for mount_root in ["/media/pi", "/media", "/mnt"]:
            mount_abs = os.path.abspath(mount_root)
            if fs_abs.startswith(mount_abs + os.sep):
                rel = os.path.relpath(fs_abs, mount_abs).replace(os.sep, "/")
                parts = rel.split("/", 1)
                drive = parts[0]
                rest = parts[1] if len(parts) > 1 else ""
                try:
                    os.makedirs(ext_root, exist_ok=True)
                    link_path = os.path.join(ext_root, drive)
                    target = os.path.join(mount_root, drive)
                    if not os.path.exists(link_path) and os.path.exists(target):
                        os.symlink(target, link_path)
                except Exception:
                    pass
                return f"/data/external/{drive}/{rest}".rstrip("/")

    return fs_abs

def find_subtitles(media_fs_path: str) -> List[Dict[str, str]]:
    """Find subtitle files for a given media file."""
    if not os.path.isfile(media_fs_path):
        return []
    
    subs = []
    dir_path = os.path.dirname(media_fs_path)
    base_name = os.path.splitext(os.path.basename(media_fs_path))[0]
    
    # Common subtitle extensions
    sub_exts = {".srt", ".vtt", ".ass", ".ssa"}
    
    # 1. Look in the same directory
    try:
        for item in os.listdir(dir_path):
            item_path = os.path.join(dir_path, item)
            if not os.path.isfile(item_path):
                continue
            
            ext = os.path.splitext(item)[1].lower()
            if ext in sub_exts:
                # Check if it starts with the same name or is just a sub file in the same dir
                if item.lower().startswith(base_name.lower()) or len(os.listdir(dir_path)) < 10:
                    label = item
                    # Try to extract language from name (e.g. movie.en.srt)
                    lang_match = re.search(r"\.([a-z]{2,3})\.(srt|vtt|ass|ssa)$", item, re.I)
                    if lang_match:
                        label = lang_match.group(1).upper()
                    
                    subs.append({
                        "label": label,
                        "path": fs_path_to_web_path(item_path),
                        "ext": ext[1:]
                    })
    except Exception as e:
        logger.warning(f"Error scanning for subtitles in {dir_path}: {e}")

    # 2. Look in 'subs' or 'subtitles' subfolder
    for sub_dir_name in ["subs", "subtitles", "Subs", "Subtitles"]:
        sub_dir = os.path.join(dir_path, sub_dir_name)
        if os.path.isdir(sub_dir):
            try:
                for item in os.listdir(sub_dir):
                    item_path = os.path.join(sub_dir, item)
                    if not os.path.isfile(item_path):
                        continue
                    
                    ext = os.path.splitext(item)[1].lower()
                    if ext in sub_exts:
                        label = f"{sub_dir_name}/{item}"
                        lang_match = re.search(r"\.([a-z]{2,3})\.(srt|vtt|ass|ssa)$", item, re.I)
                        if lang_match:
                            label = f"{lang_match.group(1).upper()} ({item})"
                            
                        subs.append({
                            "label": label,
                            "path": fs_path_to_web_path(item_path),
                            "ext": ext[1:]
                        })
            except Exception as e:
                logger.warning(f"Error scanning for subtitles in {sub_dir}: {e}")
                
    return subs

def find_trailers(media_fs_path: str) -> List[Dict[str, str]]:
    """Find trailer files for a given media file."""
    if not os.path.isfile(media_fs_path):
        return []
    
    trailers = []
    dir_path = os.path.dirname(media_fs_path)
    
    # Common video extensions
    video_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
    
    # 1. Look in the same directory for files with 'trailer' in name
    try:
        for item in os.listdir(dir_path):
            if item == os.path.basename(media_fs_path):
                continue
                
            item_path = os.path.join(dir_path, item)
            if not os.path.isfile(item_path):
                continue
            
            ext = os.path.splitext(item)[1].lower()
            if ext in video_exts and "trailer" in item.lower():
                trailers.append({
                    "name": item,
                    "path": fs_path_to_web_path(item_path)
                })
    except Exception as e:
        logger.warning(f"Error scanning for trailers in {dir_path}: {e}")

    # 2. Look in 'trailers' subfolder
    for trailer_dir_name in ["trailers", "Trailers"]:
        trailer_dir = os.path.join(dir_path, trailer_dir_name)
        if os.path.isdir(trailer_dir):
            try:
                for item in os.listdir(trailer_dir):
                    item_path = os.path.join(trailer_dir, item)
                    if not os.path.isfile(item_path):
                        continue
                    
                    ext = os.path.splitext(item)[1].lower()
                    if ext in video_exts:
                        trailers.append({
                            "name": f"Trailer: {item}",
                            "path": fs_path_to_web_path(item_path)
                        })
            except Exception as e:
                logger.warning(f"Error scanning for trailers in {trailer_dir}: {e}")
                
    return trailers

@router.get("/meta")
async def get_metadata(path: str = Query(...), fetch: bool = Query(default=False), force: bool = Query(default=False), media_type: str = Query(default=None), user_id: int = Depends(get_current_user_id)):
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
    
    # Always check for local subtitles and trailers even if metadata is cached
    local_extras = {"subtitles": [], "trailers": []}
    try:
        fs_path = safe_fs_path_from_web_path(path)
        if fs_path:
            local_extras["subtitles"] = find_subtitles(fs_path)
            local_extras["trailers"] = find_trailers(fs_path)
    except Exception:
        pass

    if cached and not fetch:
        return {
            "configured": bool(os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")), 
            "cached": True, 
            **cached,
            **local_extras
        }

    if not fetch:
        return {
            "configured": bool(os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")), 
            "cached": False, 
            "path": path,
            **local_extras
        }

    if cached and not force:
        fetched_at = cached.get("fetched_at")
        if isinstance(fetched_at, str) and fetched_at:
            try:
                ts = datetime.fromisoformat(fetched_at)
                if datetime.now() - ts < timedelta(days=30):
                    return {
                        "configured": bool(os.environ.get("OMDB_API_KEY") or os.environ.get("OMDB_KEY")), 
                        "cached": True, 
                        **cached,
                        **local_extras
                    }
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
            meta = await omdb_fetch(title=q_title, year=q_year, media_type=media_type)
            if meta:
                # Sanity check: Ensure returned title isn't completely different (fuzzy match)
                ret_title = meta.get("Title", "").lower()
                q_low = q_title.lower()
                # If neither contains the other, it might be a bad match (e.g. 'Big' vs 'The Big Bang Theory')
                if q_low not in ret_title and ret_title not in q_low:
                    # But don't reject if the query is very short (could be a legit short title)
                    if len(q_low) > 3:
                        # Use similarity score for better check
                        if _get_similarity(q_title, meta.get("Title", "")) < 0.4:
                            logger.warning(f"OMDB returned suspicious match for '{q_title}': '{meta.get('Title')}'")
                            meta = None
                            continue
                break
        except HTTPException as e:
            if e.status_code != 404:
                last_error = e
                continue
            
            # If we tried series and failed, try movie just in case
            if media_type == "series":
                try:
                    meta = await omdb_fetch(title=q_title, year=q_year, media_type="movie")
                    if meta: break
                except: pass

            # Try search if direct fetch fails
            try:
                search = await omdb_search(query=q_title, year=q_year, media_type=media_type)
                results = search.get("Search") or []
                if results:
                    # Score and pick best
                    best = None
                    best_score = -1
                    for r in results[:10]: # Increase to top 10 for better coverage
                        t = r.get("Title")
                        y = r.get("Year")
                        if not t: continue
                        
                        score = _get_similarity(q_title, t) * 50
                        
                        # Year matching is very important
                        if q_year and y:
                            # Handle "2001–2004" or "2001-" year formats from OMDb
                            y_str = str(y)
                            if str(q_year) in y_str:
                                score += 30
                            elif any(char.isdigit() for char in y_str):
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
                    
                    if best and best_score >= 20: # Reasonable threshold (lowered slightly from 25)
                        meta = await omdb_fetch(imdb_id=best.get("imdbID"), media_type=media_type)
                        break
            except Exception:
                continue

    if not meta:
        # One last ditch effort: search without media_type if we haven't already
        try:
            search = await omdb_search(query=title_guess)
            results = search.get("Search") or []
            if results:
                best = None
                best_score = -1
                for r in results:
                    score = _get_similarity(title_guess, r.get("Title", ""))
                    if score > best_score:
                        best_score = score
                        best = r
                
                if best and best_score > 0.5:
                    meta = await omdb_fetch(imdb_id=best.get("imdbID"))
        except:
            pass

    if not meta:
        if last_error: raise last_error
        raise HTTPException(status_code=404, detail="Could not find metadata for this file. Try renaming it to a cleaner title.")


    # Cache poster if available
    if meta.get("Poster") and meta["Poster"] != "N/A":
        cached_poster = await cache_remote_poster(meta["Poster"])
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
    return {
        "configured": True, 
        "cached": True, 
        **(stored or {}),
        **local_extras
    }


from fastapi.responses import FileResponse, StreamingResponse
import mimetypes

@router.get("/info")
def get_media_info(path: str = Query(...), user_id: int = Depends(get_current_user_id)):
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
async def stream_media(path: str = Query(...), token: str = Query(None), download: bool = Query(False), user_id: int = Depends(get_current_user_id)):
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

    # If download=true, force browser to download with proper headers
    if download:
        filename = os.path.basename(fs_path)
        return FileResponse(
            fs_path,
            media_type='application/octet-stream',
            filename=filename
        )

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
def browse_files(path: str = Query(default="/data"), user_id: int = Depends(get_current_user_id)):
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
    year: str = Query(default=None),
    user_id: int = Depends(get_current_user_id)
):
    if category not in ["movies", "shows", "music", "books", "gallery", "files"]:
        raise HTTPException(status_code=400, detail="Invalid category")

    # Use cache if not rebuilding
    if not rebuild:
        cache_key = build_cache_key(category, q, offset, limit, sort, genre, year)
        return _get_paged_data_cached(category, q, offset, limit, sort, genre, year, user_id)

    return _get_paged_data(category, q, offset, limit, sort, genre, year, rebuild, user_id)

def extract_archive_to_dir(archive_path: str, out_dir: str):
    """Extract CBR/RAR archives using available system tools.

    Tries multiple extraction tools in order of preference:
    1. 7-Zip variants (7zz, 7z, 7zr)
    2. unar (The Unarchiver)
    3. bsdtar (libarchive-tools)
    """
    attempts = []

    # Common Windows 7-Zip paths
    win_7z_paths = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe"
    ]
    for p in win_7z_paths:
        if os.path.exists(p):
            attempts.append((f"7z (Windows)", [p, "x", archive_path, f"-o{out_dir}", "-y"]))

    # Try 7-Zip variants (most reliable for CBR/RAR files)
    for candidate in ["7zz", "7z", "7zr"]:
        p = shutil.which(candidate)
        if p:
            # -aoa: Overwrite all existing files without prompt
            attempts.append((candidate, [p, "x", "-y", "-aoa", f"-o{out_dir}", archive_path]))

    # Try unrar (Official RAR extractor)
    p = shutil.which("unrar")
    if p:
        # x: Extract with full path, -y: Assume Yes on all queries, -o+: Overwrite existing files
        attempts.append(("unrar", [p, "x", "-y", "-o+", archive_path, out_dir + os.sep]))

    # Try unar (The Unarchiver - very good with various formats)
    p = shutil.which("unar")
    if p:
        # -f: Force overwrite, -o: Output directory
        attempts.append(("unar", [p, "-f", "-o", out_dir, archive_path]))

    # Try bsdtar (from libarchive-tools)
    p = shutil.which("bsdtar")
    if p:
        attempts.append(("bsdtar", [p, "-xf", archive_path, "-C", out_dir]))

    if not attempts:
        error_msg = (
            "❌ CBR/RAR extraction tools not found!\n\n"
            "📦 Required packages are missing. To fix this:\n\n"
            "1️⃣ SSH into your Raspberry Pi\n"
            "2️⃣ Run: sudo apt-get update && sudo apt-get install -y p7zip-full unar libarchive-tools\n"
            "3️⃣ Restart Nomad Pi service\n\n"
            "📝 Note: These packages should have been installed by setup.sh. "
            "If you recently ran a system update, they may have been removed by apt autoremove.\n\n"
            "💡 Tip: CBZ (ZIP) files work without these tools. Only CBR (RAR) files require them."
        )
        print("CBR Extraction Error: No extractor tools found (checked 7zz, 7z, 7zr, unar, bsdtar, and standard Windows paths).")
        raise HTTPException(status_code=500, detail=error_msg)

    last_err = None
    for tool, cmd in attempts:
        try:
            logger.info(f"Attempting extraction with {tool}: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                logger.info(f"Extraction successful with {tool}")
                return tool
            else:
                err = (result.stderr or result.stdout or "").strip()
                last_err = f"{tool} failed (exit {result.returncode}): {err}"
                logger.warning(f"Extraction error ({tool}): {last_err}")
        except subprocess.TimeoutExpired:
            last_err = f"{tool} timed out after 30s"
            logger.warning(last_err)
        except Exception as e:
            last_err = f"{tool} exception: {str(e)}"
            logger.error(f"Extraction exception ({tool}): {e}")

    logger.error(f"All extraction attempts failed. Last error: {last_err}")
    
    # If we are on Linux, suggest installing tools if everything failed
    if platform.system() == "Linux":
        missing_tools = []
        for t in ["7z", "unar", "unrar", "bsdtar"]:
            if not shutil.which(t):
                missing_tools.append(t)
        if missing_tools:
            last_err += f"\n\nMissing tools on system: {', '.join(missing_tools)}. Run 'sudo apt update && sudo apt install -y p7zip-full unar unrar libarchive-tools' to fix."

    raise HTTPException(status_code=500, detail=last_err or "Failed to extract archive.")

@router.get("/list/{category}")
def list_media(category: str, user_id: int = Depends(get_current_user_id)):
    paths_to_scan = get_scan_paths(category)
    files = []
    
    # Get all progress to merge
    all_progress = database.get_all_progress(user_id)

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
def set_progress(data: Dict = Body(...), user_id: int = Depends(get_current_user_id)):
    path = data.get("path") or data.get("file_path")
    time = data.get("current_time")
    duration = data.get("duration")
    
    if not path or time is None:
        logger.warning(f"Progress update failed: Missing path or current_time (path={path}, time={time})")
        return {"status": "error", "message": "Missing path or current_time"}
        
    try:
        logger.debug(f"Updating progress for user {user_id}: {path} at {time}/{duration}")
        database.update_progress(user_id, path, time, duration)
        
        # If progress is near the end (e.g., > 95%), mark as played
        if duration and duration > 0:
            if (time / duration) > 0.95:
                database.increment_play_count(user_id, path)
                
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error updating progress for {path}: {e}")
        return {"status": "error", "message": str(e)}

@router.post("/rename")
def rename_media(data: Dict = Body(...), background_tasks: BackgroundTasks = None, user_id: int = Depends(get_current_user_id)):
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

def _cleanup_empty_folders(bases: List[str]):
    """Recursively remove empty directories under bases, excluding bases themselves."""
    for base in bases:
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base, topdown=False):
            if root == base:
                continue
            # Check if directory is empty or only contains junk/posters
            try:
                entries = os.listdir(root)
                junk = {".ds_store", "thumbs.db", "desktop.ini", "poster.jpg", "poster.jpeg", "poster.png", "folder.jpg", "folder.png", "cover.jpg", "cover.png", "fanart.jpg", "movie.nfo", "banner.jpg", "clearart.png", "disc.png", "logo.png", "landscape.jpg", "metadata.nfo"}
                if not entries or all(e.lower() in junk for e in entries):
                    logger.info(f"Cleaning up empty/junk folder: {root}")
                    shutil.rmtree(root)
            except Exception as e:
                logger.error(f"Error cleaning up folder {root}: {e}")

@router.post("/organize/shows")
async def organize_shows(dry_run: bool = Query(default=True), rename_files: bool = Query(default=True), use_omdb: bool = Query(default=True), write_poster: bool = Query(default=True), limit: int = Query(default=250), user_id: int = Depends(get_current_user_id)):
    return await _organize_shows_internal(dry_run, rename_files, use_omdb, write_poster, limit)

def _get_similarity(a: str, b: str) -> float:
    """Simple string similarity score (0.0 to 1.0)"""
    a = a.lower().strip()
    b = b.lower().strip()
    if not a or not b: return 0.0
    if a == b: return 1.0
    
    # Very basic: ratio of common characters or common words
    a_words = set(re.findall(r'\w+', a))
    b_words = set(re.findall(r'\w+', b))
    if not a_words or not b_words: return 0.0
    
    intersection = a_words.intersection(b_words)
    union = a_words.union(b_words)
    return len(intersection) / len(union)

async def _organize_shows_internal(dry_run: bool = True, rename_files: bool = True, use_omdb: bool = True, write_poster: bool = True, limit: int = 250):
    # Clear cache when starting organization
    _get_paged_data_cached.cache_clear()
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
                
                # Extract year if present in show name
                show_year = None
                year_match = re.search(r'\((\d{4})\)', show_name)
                if year_match:
                    show_year = year_match.group(1)
                    show_name = show_name.replace(year_match.group(0), "").strip()

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
                    from_web = fs_path_to_web_path(src_fs)
                    to_web = fs_path_to_web_path(dest_fs)
                    if not (isinstance(from_web, str) and from_web.startswith("/data/")):
                        raise ValueError("Invalid from_web")
                    if not (isinstance(to_web, str) and to_web.startswith("/data/")):
                        raise ValueError("Invalid to_web")
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
                            to_web = fs_path_to_web_path(dest_fs)
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
                            try:
                                # Try direct fetch first
                                meta = await omdb_fetch(title=show_name, year=show_year, media_type="series")
                            except Exception:
                                # Try a search if direct fetch fails
                                search = await omdb_search(query=show_name, year=show_year, media_type="series")
                                results = search.get("Search") or []
                                if results:
                                    # Pick the best match from search results
                                    best_match = results[0]
                                    best_score = _get_similarity(show_name, best_match.get("Title", ""))
                                    for res in results:
                                        score = _get_similarity(show_name, res.get("Title", ""))
                                        if score > best_score:
                                            best_score = score
                                            best_match = res
                                        elif score == best_score and res.get("Year", "").startswith(str(show_year or "")):
                                            best_match = res
                                            
                                    if best_score > 0.5: # Only use if reasonably similar
                                        meta = await omdb_fetch(imdb_id=best_match["imdbID"], media_type="series")
                                else:
                                    # Try without year if we had one and it failed
                                    if show_year:
                                        try:
                                            meta = await omdb_fetch(title=show_name, media_type="series")
                                        except Exception:
                                            search = await omdb_search(query=show_name, media_type="series")
                                            results = search.get("Search") or []
                                            if results:
                                                best_match = results[0]
                                                best_score = _get_similarity(show_name, best_match.get("Title", ""))
                                                for res in results:
                                                    score = _get_similarity(show_name, res.get("Title", ""))
                                                    if score > best_score:
                                                        best_score = score
                                                        best_match = res
                                                
                                                if best_score > 0.5:
                                                    meta = await omdb_fetch(imdb_id=best_match["imdbID"], media_type="series")
                            
                            if meta:
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
                            meta["Poster"] = fs_path_to_web_path(poster_dest)
                        except Exception: pass
                    # 2. Otherwise try to download from OMDB if we have meta
                    elif meta and meta.get("Poster") and meta["Poster"] != "N/A":
                        try:
                            poster_url = meta["Poster"]
                            cached_poster = await cache_remote_poster(poster_url)
                            if cached_poster:
                                # Also save as poster.jpg in show directory
                                cached_fs = safe_fs_path_from_web_path(cached_poster)
                                if os.path.exists(cached_fs):
                                    shutil.copy2(cached_fs, poster_dest)
                                    meta["Poster"] = fs_path_to_web_path(poster_dest)
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

    if not dry_run:
        _cleanup_empty_folders(show_bases)

    return {"status": "ok", "dry_run": bool(dry_run), "rename_files": bool(rename_files), "use_omdb": bool(use_omdb), "write_poster": bool(write_poster), "moved": moved, "skipped": skipped, "errors": errors, "shows_metadata_fetched": len(shows_processed), "planned": planned[: min(len(planned), 1000)]}

@router.post("/organize/movies")
async def organize_movies(dry_run: bool = Query(default=True), use_omdb: bool = Query(default=True), write_poster: bool = Query(default=True), limit: int = Query(default=250), user_id: int = Depends(get_current_user_id)):
    return await _organize_movies_internal(dry_run, use_omdb, write_poster, limit)

async def _organize_movies_internal(dry_run: bool = True, use_omdb: bool = True, write_poster: bool = True, limit: int = 250):
    # Clear cache when starting organization
    _get_paged_data_cached.cache_clear()
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
                            meta = await omdb_fetch(title=query, year=year_guess, media_type="movie")
                            break
                        except Exception:
                            try:
                                # Try without year if it failed with year
                                if year_guess:
                                    meta = await omdb_fetch(title=query, media_type="movie")
                                    break
                            except Exception:
                                continue
                    
                    # Final fallback: Search
                    if not meta:
                        try:
                            search_res = await omdb_search(title_guess, year=year_guess, media_type="movie")
                            results = search_res.get("Search") or []
                            if results:
                                # Pick best match from search
                                best_match = results[0]
                                best_score = _get_similarity(title_guess, best_match.get("Title", ""))
                                for res in results:
                                    score = _get_similarity(title_guess, res.get("Title", ""))
                                    if score > best_score:
                                        best_score = score
                                        best_match = res
                                    elif score == best_score and res.get("Year", "") == str(year_guess or ""):
                                        best_match = res
                                
                                if best_score > 0.5:
                                    meta = await omdb_fetch(imdb_id=best_match.get("imdbID"), media_type="movie")
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

                # CHECK FOR DUPLICATES: Check if this movie already exists in the library
                # We check the final destination folder name in the base movies directory
                exists_in_library = False
                for existing_folder in os.listdir(base):
                    existing_path = os.path.join(base, existing_folder)
                    if os.path.isdir(existing_path):
                        # If a folder with this title and year already exists, skip it
                        if existing_folder.lower() == folder.lower():
                            # Check if it contains a video file
                            has_video = any(os.path.splitext(f)[1].lower() in [".mp4", ".mkv", ".avi", ".mov", ".webm"] 
                                          for f in os.listdir(existing_path))
                            if has_video:
                                exists_in_library = True
                                break
                
                if exists_in_library and os.path.abspath(src_fs) != os.path.abspath(dest_fs):
                    logger.info(f"Skipping duplicate movie: {title} already exists in library")
                    skipped += 1
                    continue

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

    if not dry_run:
        _cleanup_empty_folders(movie_bases)

    return {"status": "ok", "dry_run": bool(dry_run), "use_omdb": bool(use_omdb), "write_poster": bool(write_poster), "moved": moved, "skipped": skipped, "errors": errors, "planned": planned[: min(len(planned), 1000)]}

import psutil
import subprocess
import platform

def _get_bin_path(name: str, default: str) -> str:
    """Find binary path dynamically or use default"""
    import shutil
    return shutil.which(name) or default

def trigger_dlna_rescan():
    """Trigger a MiniDLNA rescan if on Linux"""
    if platform.system() == "Linux":
        try:
            # We try to use dynamic paths for better SBC compatibility
            minidlnad = _get_bin_path("minidlnad", "/usr/sbin/minidlnad")
            systemctl = _get_bin_path("systemctl", "/usr/bin/systemctl")
            
            subprocess.run(["sudo", minidlnad, "-R"], check=False)
            subprocess.run(["sudo", systemctl, "restart", "minidlna"], check=False)
            logger.info("Triggered MiniDLNA rescan")
        except Exception as e:
            logger.error(f"Failed to trigger MiniDLNA rescan: {e}")

async def trigger_auto_organize():
    """Trigger automated organization of shows and movies"""
    try:
        # We call the internal organization functions with dry_run=False
        await _organize_shows_internal(dry_run=False, rename_files=True, use_omdb=True, write_poster=True)
        await _organize_movies_internal(dry_run=False, use_omdb=True, write_poster=True)
        
        # Also clean up empty folders for other categories
        for cat in ["music", "books", "gallery", "files"]:
            _cleanup_empty_folders(get_scan_paths(cat))
            
        logger.info("Automated media organization and cleanup completed")
        # Trigger DLNA rescan after organization is done
        trigger_dlna_rescan()
    except Exception as e:
        logger.error(f"Automated organization failed: {e}")

@router.post("/upload/{category}")
async def upload_file(category: str, background_tasks: BackgroundTasks, files: UploadFile = File(...), user_id: int = Depends(get_current_user_id)):
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
async def upload_stream(category: str, request: Request, background_tasks: BackgroundTasks, path: str = Query(default=""), user_id: int = Depends(get_current_user_id)):
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
def delete_media(path: str, background_tasks: BackgroundTasks, user_id: int = Depends(get_current_user_id)):
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
            junk = {".ds_store", "thumbs.db", "desktop.ini", "poster.jpg", "poster.jpeg", "poster.png", "folder.jpg", "folder.png", "cover.jpg", "cover.png", "fanart.jpg", "movie.nfo", "banner.jpg", "clearart.png", "disc.png", "logo.png", "landscape.jpg", "metadata.nfo"}
            if not remaining or all(f.lower() in junk for f in remaining):
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
def prepare_drive(path: str, user_id: int = Depends(get_current_user_id)):
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
def manual_organize(background_tasks: BackgroundTasks, user_id: int = Depends(get_current_user_id)):
    """Manually trigger automated media organization"""
    background_tasks.add_task(trigger_auto_organize)
    return {"status": "ok", "message": "Automated organization started in background"}

@router.post("/scan")
def scan_library(background_tasks: BackgroundTasks, user_id: int = Depends(get_current_user_id)):
    async def run_scan():
        # Scan all categories
        for cat in ["movies", "shows", "music", "books", "gallery", "files"]:
             try:
                 build_library_index(cat)
             except Exception as e:
                 print(f"Scan error {cat}: {e}")
        # Also trigger MiniDLNA rescan and auto-organization
        trigger_dlna_rescan()
        await trigger_auto_organize()
        
    background_tasks.add_task(run_scan)
    return {"status": "ok", "message": "Library scan and organization started in background."}

@router.post("/fix_duplicates")
def fix_duplicates(background_tasks: BackgroundTasks, user_id: int = Depends(get_current_user_id)):
    """Find and delete duplicate files/content across the library."""
    def run_fix():
        logger.info("Starting mass duplicate fix...")
        
        # 1. Fix duplicate files (same name and size)
        file_dupes = database.fix_duplicate_files()
        # 2. Fix duplicate content (same IMDb ID)
        content_dupes = database.fix_duplicate_content()
        
        # Merge and remove duplicates from the list
        all_to_delete = list(set(file_dupes + content_dupes))
        deleted_count = 0
        
        for path in all_to_delete:
            try:
                fs_path = safe_fs_path_from_web_path(path)
                if os.path.exists(fs_path):
                    logger.info(f"Duplicate fix: Deleting {fs_path}")
                    if os.path.isdir(fs_path):
                        shutil.rmtree(fs_path)
                    else:
                        os.remove(fs_path)
                    
                    # Clean up database
                    database.delete_library_index_item(path)
                    deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete duplicate {path}: {e}")
        
        logger.info(f"Mass duplicate fix completed. Deleted {deleted_count} items.")
        
        # Also clean up empty folders after mass deletion
        for cat in ["movies", "shows", "music", "books", "gallery", "files"]:
            _cleanup_empty_folders(get_scan_paths(cat))
        
        # Trigger rescan to ensure library is up to date
        for cat in ["movies", "shows", "music", "books", "gallery", "files"]:
            try:
                build_library_index(cat)
            except: pass
        trigger_dlna_rescan()

    background_tasks.add_task(run_fix)
    return {"status": "ok", "message": "Mass duplicate fix started in background."}

@router.get("/duplicates")
def get_duplicates(user_id: int = Depends(get_current_user_id)):
    """Find and return duplicate files and media content."""
    try:
        file_dupes = database.find_duplicate_files()
        meta_dupes = database.find_duplicate_metadata()
        
        # Format file duplicates
        formatted_files = []
        for d in file_dupes:
            paths = d["paths"].split("|")
            formatted_files.append({
                "name": d["name"],
                "size": d["size"],
                "category": d["category"],
                "count": d["count"],
                "paths": paths
            })
            
        # Format metadata duplicates
        formatted_meta = []
        for d in meta_dupes:
            paths = d["paths"].split("|")
            formatted_meta.append({
                "imdb_id": d["imdb_id"],
                "title": d["title"],
                "media_type": d["media_type"],
                "count": d["count"],
                "paths": paths
            })
            
        return {
            "file_duplicates": formatted_files,
            "content_duplicates": formatted_meta
        }
    except Exception as e:
        logger.error(f"Error finding duplicates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
def resume(limit: int = 12, user_id: int = Depends(get_current_user_id)):
    all_progress = database.get_all_progress(user_id)
    items = []
    for web_path, prog in all_progress.items():
        try:
            t = float(prog.get("current_time") or 0)
            d = float(prog.get("duration") or 0)
        except Exception:
            continue
        if not (t > 10 and d > 0 and (d - t) > 10):
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
def comic_pages(path: str, user_id: int = Depends(get_current_user_id)):
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
