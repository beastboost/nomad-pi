"""Small ffprobe adapter used by the playback planner.

Only extracts information needed to decide direct-play/remux/transcode. Richer
track metadata will be layered on later without coupling the planner to ffprobe
JSON or FastAPI.
"""

import json
import os
import subprocess
from pathlib import Path

from .planner import MediaProbe


class ProbeError(RuntimeError):
    pass


def probe_media(path: str, timeout: int = 30) -> MediaProbe:
    if not os.path.isfile(path):
        raise ProbeError("media file does not exist")

    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_entries", "format=format_name,bit_rate",
        "-show_entries", "stream=codec_type,codec_name,width,height,bit_rate",
        path,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ProbeError("ffprobe is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("ffprobe timed out") from exc
    except OSError as exc:
        raise ProbeError(f"could not start ffprobe: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffprobe failed").strip()
        raise ProbeError(detail[:500])

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProbeError("ffprobe returned invalid JSON") from exc

    video = None
    audio = None
    for stream in data.get("streams") or []:
        stream_type = str(stream.get("codec_type") or "").lower()
        if stream_type == "video" and video is None:
            video = stream
        elif stream_type == "audio" and audio is None:
            audio = stream

    fmt = data.get("format") or {}
    container = _container_name(path, str(fmt.get("format_name") or ""))

    return MediaProbe(
        container=container,
        video_codec=(video or {}).get("codec_name"),
        audio_codec=(audio or {}).get("codec_name"),
        width=_positive_int((video or {}).get("width")),
        height=_positive_int((video or {}).get("height")),
        bitrate=(
            _positive_int(fmt.get("bit_rate"))
            or _positive_int((video or {}).get("bit_rate"))
            or _positive_int((audio or {}).get("bit_rate"))
        ),
    )


def _container_name(path: str, ffprobe_name: str) -> str:
    """Return the user-facing container name the capability model expects."""
    extension = Path(path).suffix.lower().lstrip(".")
    aliases = {
        "mkv": "mkv",
        "m4v": "mp4",
        "m4a": "m4a",
        "mov": "mov",
        "mp4": "mp4",
        "webm": "webm",
        "avi": "avi",
        "ts": "ts",
        "m2ts": "m2ts",
        "flac": "flac",
        "mp3": "mp3",
        "ogg": "ogg",
        "opus": "opus",
        "wav": "wav",
    }
    if extension in aliases:
        return aliases[extension]

    first = (ffprobe_name.split(",", 1)[0] if ffprobe_name else "").strip().lower()
    ffprobe_aliases = {
        "matroska": "mkv",
        "mov": "mp4",
        "mpegts": "ts",
    }
    return ffprobe_aliases.get(first, first or extension)


def _positive_int(value):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None
