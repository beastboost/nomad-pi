"""Cached library quality/intelligence scanner for Nomad Pi.

The scanner is intentionally incremental: file size/mtime are the cache key,
so subsequent health passes only ffprobe new or changed media. Potential exact
duplicates get a quick first/last-chunk fingerprint only when sizes collide.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
from typing import Dict, Iterable, List, Optional, Tuple

from app import database
from app.routers import media


VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".ts", ".m2ts",
    ".mts", ".wmv", ".flv", ".mpg", ".mpeg", ".vob", ".3gp",
}
SCAN_TTL_SECONDS = 12 * 60 * 60

QUALITY_TOKENS = {
    "2160p", "1080p", "1080i", "720p", "576p", "480p", "4k", "uhd", "hdr", "hdr10",
    "dv", "dolbyvision", "bluray", "blu-ray", "bdrip", "brrip", "webrip", "web-dl", "webdl",
    "hdtv", "dvdrip", "remux", "x264", "x265", "h264", "h265", "hevc", "av1", "vp9",
    "aac", "ac3", "eac3", "dts", "truehd", "atmos", "10bit", "8bit", "proper", "repack",
}

_state = {
    "running": False,
    "discovered": 0,
    "processed": 0,
    "probed": 0,
    "cached": 0,
    "errors": 0,
    "message": "idle",
    "started_at": None,
    "completed_at": None,
}
_state_lock = threading.Lock()
_schema_lock = threading.Lock()
_schema_ready = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    path = database.DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS library_quality_files (
                    path TEXT PRIMARY KEY,
                    fs_path TEXT NOT NULL,
                    category TEXT NOT NULL,
                    name TEXT NOT NULL,
                    media_key TEXT NOT NULL DEFAULT '',
                    show_name TEXT NOT NULL DEFAULT '',
                    season INTEGER,
                    episode INTEGER,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    mtime_ns INTEGER NOT NULL DEFAULT 0,
                    quick_hash TEXT,
                    duration REAL NOT NULL DEFAULT 0,
                    container TEXT NOT NULL DEFAULT '',
                    video_codec TEXT NOT NULL DEFAULT '',
                    audio_codec TEXT NOT NULL DEFAULT '',
                    width INTEGER,
                    height INTEGER,
                    bitrate INTEGER,
                    probe_ok INTEGER NOT NULL DEFAULT 1,
                    probe_error TEXT,
                    issues_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_library_quality_category
                    ON library_quality_files(category, media_key);
                CREATE INDEX IF NOT EXISTS idx_library_quality_size
                    ON library_quality_files(file_size);
                CREATE INDEX IF NOT EXISTS idx_library_quality_show_episode
                    ON library_quality_files(show_name, season, episode);
                """
            )
            conn.commit()
            _schema_ready = True
        finally:
            conn.close()


def _web_path(fs_path: str) -> str:
    absolute = os.path.abspath(fs_path)
    base = os.path.abspath(media.BASE_DIR)
    try:
        if os.path.commonpath([absolute, base]) == base:
            return "/data/" + os.path.relpath(absolute, base).replace(os.sep, "/")
    except ValueError:
        pass
    return absolute


def _discover() -> List[Tuple[str, str, str, str]]:
    found = {}
    for category in ("movies", "shows"):
        for root in media.get_scan_paths(category):
            if not root or not os.path.isdir(root):
                continue
            try:
                for dirpath, _dirs, names in os.walk(root, followlinks=True):
                    for name in names:
                        if Path(name).suffix.lower() not in VIDEO_EXTENSIONS:
                            continue
                        fs_path = os.path.join(dirpath, name)
                        real = os.path.realpath(fs_path)
                        found.setdefault(real, (real, _web_path(fs_path), category, root))
            except OSError:
                continue
    return list(found.values())


def _episode_identity(fs_path: str, root: str) -> Tuple[str, Optional[int], Optional[int]]:
    name = Path(fs_path).name
    match = re.search(r"(?i)(?:^|[^a-z0-9])s(\d{1,2})[ ._-]*e(\d{1,3})(?:[^a-z0-9]|$)", name)
    if not match:
        match = re.search(r"(?i)(?:^|[^a-z0-9])(\d{1,2})x(\d{1,3})(?:[^a-z0-9]|$)", name)
    season = int(match.group(1)) if match else None
    episode = int(match.group(2)) if match else None
    try:
        rel = Path(os.path.relpath(fs_path, root))
        show = rel.parts[0] if len(rel.parts) > 1 else ""
    except Exception:
        show = ""
    if not show and match:
        show = name[:match.start()].replace(".", " ").replace("_", " ").strip(" -_")
    return show.strip(), season, episode


def _normalise_key(fs_path: str, category: str, root: str) -> Tuple[str, str, Optional[int], Optional[int]]:
    stem = Path(fs_path).stem
    year_match = re.search(r"(?:19|20)\d{2}", stem)
    year = year_match.group(0) if year_match else ""
    show, season, episode = _episode_identity(fs_path, root) if category == "shows" else ("", None, None)
    if category == "shows" and season is not None and episode is not None:
        show_key = re.sub(r"[^a-z0-9]+", " ", show.lower()).strip()
        return f"{show_key}|s{season:02d}e{episode:03d}", show, season, episode

    cleaned = re.sub(r"[\[\](){}]", " ", stem.lower())
    words = re.split(r"[^a-z0-9]+", cleaned)
    kept = []
    for word in words:
        if not word or word in QUALITY_TOKENS:
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", word):
            continue
        if re.fullmatch(r"\d{3,4}p", word):
            continue
        kept.append(word)
    key = " ".join(kept).strip() or stem.lower()
    if year:
        key = f"{key}|{year}"
    return key, show, season, episode


def _positive_int(value) -> Optional[int]:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _probe(fs_path: str) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is not installed")
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-print_format", "json",
            "-show_entries", "format=format_name,bit_rate,duration",
            "-show_entries", "stream=codec_type,codec_name,width,height,bit_rate",
            fs_path,
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "ffprobe failed").strip()[:800])
    data = json.loads(result.stdout or "{}")
    fmt = data.get("format") or {}
    video = next((s for s in data.get("streams") or [] if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams") or [] if s.get("codec_type") == "audio"), {})
    try:
        duration = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    return {
        "duration": max(0, duration),
        "container": str(fmt.get("format_name") or "").split(",", 1)[0].lower(),
        "video_codec": str(video.get("codec_name") or "").lower(),
        "audio_codec": str(audio.get("codec_name") or "").lower(),
        "width": _positive_int(video.get("width")),
        "height": _positive_int(video.get("height")),
        "bitrate": _positive_int(fmt.get("bit_rate")) or _positive_int(video.get("bit_rate")),
    }


def _issues(probe: dict, category: str) -> List[str]:
    issues = []
    width, height = probe.get("width"), probe.get("height")
    codec = probe.get("video_codec") or ""
    if not codec:
        issues.append("no_video_stream")
    if height and height < 720:
        issues.append("low_resolution")
    if codec and codec not in {"h264", "hevc", "h265", "av1", "vp9"}:
        issues.append("legacy_video_codec")
    if not probe.get("audio_codec"):
        issues.append("no_audio_stream")
    if probe.get("duration", 0) <= 0:
        issues.append("unknown_duration")
    return issues


def _quick_hash(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        h.update(handle.read(chunk_size))
        if size > chunk_size:
            handle.seek(max(0, size - chunk_size))
            h.update(handle.read(chunk_size))
    h.update(str(size).encode())
    return h.hexdigest()


def _fresh(row, size: int, mtime_ns: int) -> bool:
    return bool(row and int(row["file_size"] or 0) == size and int(row["mtime_ns"] or 0) == mtime_ns)


def _scan_worker(force: bool = False) -> None:
    ensure_schema()
    with _state_lock:
        if _state["running"]:
            return
        _state.update({
            "running": True, "discovered": 0, "processed": 0, "probed": 0,
            "cached": 0, "errors": 0, "message": "discovering media",
            "started_at": _now(), "completed_at": None,
        })
    try:
        files = _discover()
        with _state_lock:
            _state["discovered"] = len(files)
            _state["message"] = "checking media quality"
        conn = _connect()
        live = set()
        try:
            for fs_path, web_path, category, root in files:
                live.add(web_path)
                try:
                    st = os.stat(fs_path)
                    existing = conn.execute("SELECT * FROM library_quality_files WHERE path=?", (web_path,)).fetchone()
                    if not force and _fresh(existing, st.st_size, st.st_mtime_ns):
                        with _state_lock: _state["cached"] += 1
                    else:
                        key, show, season, episode = _normalise_key(fs_path, category, root)
                        try:
                            probe = _probe(fs_path)
                            probe_ok, error = 1, None
                            issues = _issues(probe, category)
                        except Exception as exc:
                            probe = {"duration": 0, "container": "", "video_codec": "", "audio_codec": "", "width": None, "height": None, "bitrate": None}
                            probe_ok, error = 0, str(exc)[:1000]
                            issues = ["probe_failed"]
                            with _state_lock: _state["errors"] += 1
                        conn.execute(
                            """
                            INSERT INTO library_quality_files (
                                path,fs_path,category,name,media_key,show_name,season,episode,
                                file_size,mtime_ns,quick_hash,duration,container,video_codec,audio_codec,
                                width,height,bitrate,probe_ok,probe_error,issues_json,updated_at
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(path) DO UPDATE SET
                                fs_path=excluded.fs_path,category=excluded.category,name=excluded.name,
                                media_key=excluded.media_key,show_name=excluded.show_name,season=excluded.season,
                                episode=excluded.episode,file_size=excluded.file_size,mtime_ns=excluded.mtime_ns,
                                quick_hash=NULL,duration=excluded.duration,container=excluded.container,
                                video_codec=excluded.video_codec,audio_codec=excluded.audio_codec,
                                width=excluded.width,height=excluded.height,bitrate=excluded.bitrate,
                                probe_ok=excluded.probe_ok,probe_error=excluded.probe_error,
                                issues_json=excluded.issues_json,updated_at=excluded.updated_at
                            """,
                            (
                                web_path,fs_path,category,os.path.basename(fs_path),key,show,season,episode,
                                st.st_size,st.st_mtime_ns,None,probe["duration"],probe["container"],
                                probe["video_codec"],probe["audio_codec"],probe["width"],probe["height"],
                                probe["bitrate"],probe_ok,error,json.dumps(issues),_now(),
                            ),
                        )
                        conn.commit()
                        with _state_lock: _state["probed"] += 1
                except Exception:
                    with _state_lock: _state["errors"] += 1
                finally:
                    with _state_lock: _state["processed"] += 1

            # Drop vanished files.
            rows = conn.execute("SELECT path FROM library_quality_files").fetchall()
            stale = [row["path"] for row in rows if row["path"] not in live]
            conn.executemany("DELETE FROM library_quality_files WHERE path=?", [(p,) for p in stale])
            conn.commit()

            # Hash only same-size candidates; unchanged hashes are reused.
            size_groups = conn.execute(
                "SELECT file_size, COUNT(*) count FROM library_quality_files WHERE probe_ok=1 GROUP BY file_size HAVING count>1"
            ).fetchall()
            for group in size_groups:
                rows = conn.execute(
                    "SELECT path,fs_path,quick_hash FROM library_quality_files WHERE file_size=?",
                    (group["file_size"],),
                ).fetchall()
                for row in rows:
                    if row["quick_hash"]:
                        continue
                    try:
                        digest = _quick_hash(row["fs_path"])
                        conn.execute("UPDATE library_quality_files SET quick_hash=? WHERE path=?", (digest,row["path"]))
                    except OSError:
                        pass
            conn.commit()
        finally:
            conn.close()
        with _state_lock:
            _state["message"] = "ready"
            _state["completed_at"] = _now()
    finally:
        with _state_lock:
            _state["running"] = False


def start_scan(force: bool = False) -> bool:
    ensure_schema()
    with _state_lock:
        if _state["running"]:
            return False
        completed = _state.get("completed_at")
        if not force and completed:
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(completed)
                if age.total_seconds() < SCAN_TTL_SECONDS:
                    return False
            except Exception:
                pass
    threading.Thread(target=_scan_worker, kwargs={"force": force}, daemon=True, name="nomad-library-intelligence").start()
    return True


def status() -> dict:
    ensure_schema()
    with _state_lock:
        return dict(_state)


def _row(row) -> dict:
    value = dict(row)
    try: value["issues"] = json.loads(value.pop("issues_json") or "[]")
    except Exception: value["issues"] = []
    value["probe_ok"] = bool(value.get("probe_ok"))
    value.pop("fs_path", None)
    value.pop("quick_hash", None)
    return value


def summary() -> dict:
    ensure_schema()
    start_scan(False)
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM library_quality_files").fetchall()
        items = [_row(r) for r in rows]
        exact = conn.execute(
            """
            SELECT quick_hash, COUNT(*) count FROM library_quality_files
            WHERE quick_hash IS NOT NULL AND quick_hash<>'' GROUP BY quick_hash HAVING count>1
            """
        ).fetchall()
        versions = conn.execute(
            """
            SELECT media_key, COUNT(*) count FROM library_quality_files
            WHERE media_key<>'' GROUP BY media_key HAVING count>1
            """
        ).fetchall()
    finally:
        conn.close()
    resolutions = Counter()
    codecs = Counter()
    issue_counts = Counter()
    total_bytes = 0
    broken = 0
    for item in items:
        total_bytes += int(item.get("file_size") or 0)
        h = item.get("height") or 0
        resolutions["4K"] += int(h >= 2000)
        resolutions["1080p"] += int(1000 <= h < 2000)
        resolutions["720p"] += int(700 <= h < 1000)
        resolutions["SD"] += int(0 < h < 700)
        if item.get("video_codec"): codecs[item["video_codec"]] += 1
        if not item.get("probe_ok"): broken += 1
        issue_counts.update(item.get("issues") or [])
    missing = missing_episodes()
    return {
        "files": len(items),
        "bytes": total_bytes,
        "broken": broken,
        "exact_duplicate_groups": len(exact),
        "version_groups": len(versions),
        "missing_episode_count": sum(len(g["missing"]) for g in missing),
        "issue_counts": dict(issue_counts),
        "resolutions": dict(resolutions),
        "video_codecs": dict(codecs),
        "scan": status(),
    }


def duplicates() -> dict:
    ensure_schema()
    conn = _connect()
    try:
        exact_groups = []
        hashes = conn.execute(
            "SELECT quick_hash FROM library_quality_files WHERE quick_hash IS NOT NULL AND quick_hash<>'' GROUP BY quick_hash HAVING COUNT(*)>1"
        ).fetchall()
        for row in hashes:
            files = conn.execute("SELECT * FROM library_quality_files WHERE quick_hash=? ORDER BY path", (row["quick_hash"],)).fetchall()
            exact_groups.append({"fingerprint": row["quick_hash"][:12], "files": [_row(f) for f in files]})
        version_groups = []
        keys = conn.execute(
            "SELECT media_key FROM library_quality_files WHERE media_key<>'' GROUP BY media_key HAVING COUNT(*)>1"
        ).fetchall()
        for row in keys:
            files = conn.execute("SELECT * FROM library_quality_files WHERE media_key=? ORDER BY height DESC, bitrate DESC", (row["media_key"],)).fetchall()
            # Suppress groups that are exclusively the exact same duplicate; exact list already covers them.
            version_groups.append({"media_key": row["media_key"], "files": [_row(f) for f in files]})
        return {"exact": exact_groups, "versions": version_groups}
    finally:
        conn.close()


def missing_episodes() -> List[dict]:
    ensure_schema()
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT show_name,season,episode,path FROM library_quality_files
            WHERE category='shows' AND show_name<>'' AND season IS NOT NULL AND episode IS NOT NULL AND season>0
            ORDER BY show_name,season,episode
            """
        ).fetchall()
    finally:
        conn.close()
    grouped: Dict[Tuple[str,int], set] = defaultdict(set)
    for row in rows:
        grouped[(row["show_name"], int(row["season"]))].add(int(row["episode"]))
    output = []
    for (show, season), episodes in sorted(grouped.items()):
        if len(episodes) < 2:
            continue
        first, last = min(episodes), max(episodes)
        missing = [ep for ep in range(first, last + 1) if ep not in episodes]
        if missing:
            output.append({"show": show, "season": season, "first": first, "last": last, "present": len(episodes), "missing": missing})
    return output


def issues(kind: str = "", limit: int = 500) -> List[dict]:
    ensure_schema()
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM library_quality_files ORDER BY updated_at DESC LIMIT ?", (max(1,min(2000,int(limit))),)).fetchall()
    finally:
        conn.close()
    output = []
    for row in rows:
        item = _row(row)
        if not item.get("issues"):
            continue
        if kind and kind not in item["issues"]:
            continue
        output.append(item)
    return output
