"""Track discovery for Nomad Pi playback sessions."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Dict, List

from .probe import ProbeError


TEXT_SUBTITLE_CODECS = {
    "subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text", "ttml"
}


def probe_tracks(path: str, timeout: int = 30) -> Dict[str, List[dict]]:
    if not os.path.isfile(path):
        raise ProbeError("media file does not exist")

    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_entries",
        "stream=index,codec_type,codec_name,channels,channel_layout,width,height:stream_tags=language,title:stream_disposition=default,forced,hearing_impaired,visual_impaired",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
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

    output = {"video": [], "audio": [], "subtitles": []}
    ordinals = {"video": 0, "audio": 0, "subtitle": 0}
    for stream in data.get("streams") or []:
        kind = str(stream.get("codec_type") or "").lower()
        if kind not in ordinals:
            continue
        tags = stream.get("tags") or {}
        disposition = stream.get("disposition") or {}
        item = {
            "stream_index": int(stream.get("index", -1)),
            "ordinal": ordinals[kind],
            "codec": str(stream.get("codec_name") or "unknown").lower(),
            "language": str(tags.get("language") or "und"),
            "title": str(tags.get("title") or ""),
            "default": bool(disposition.get("default")),
            "forced": bool(disposition.get("forced")),
        }
        ordinals[kind] += 1

        if kind == "audio":
            item.update({
                "channels": int(stream.get("channels") or 0),
                "channel_layout": str(stream.get("channel_layout") or ""),
                "hearing_impaired": bool(disposition.get("hearing_impaired")),
                "visual_impaired": bool(disposition.get("visual_impaired")),
            })
            output["audio"].append(item)
        elif kind == "subtitle":
            item["text_supported"] = item["codec"] in TEXT_SUBTITLE_CODECS
            output["subtitles"].append(item)
        else:
            item.update({
                "width": int(stream.get("width") or 0),
                "height": int(stream.get("height") or 0),
            })
            output["video"].append(item)

    return output
