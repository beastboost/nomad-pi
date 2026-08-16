"""Low-overhead debrid release ranking for Nomad Pi.

The media server should spend its limited CPU serving bytes, not fixing avoidable
codec/container choices after download.  This runtime policy keeps Torrentio
search broad enough for manual fallback, but annotates and ranks releases for a
Pi-friendly default profile:

* 1080p H.264/AVC/x264
* sensible file size
* MP4 + AAC preferred when Torrentio exposes enough naming information
* HEVC/x265/AV1/4K/remux/10-bit/HDR pushed to the bottom
* Dolby Digital/DTS/TrueHD releases treated as audio-conversion fallbacks

The browser UI can then hide non-lite results by default while still offering an
explicit "show all" escape hatch.
"""

from __future__ import annotations

import math
import os
import re
import threading
from typing import Optional

from app.services import debrid as debrid_module


_INSTALLED = False
_LOCK = threading.Lock()
_ORIGINAL_SEARCH = debrid_module.search_torrentio


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _size_bytes(value: str) -> int:
    text = str(value or "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)", text, re.IGNORECASE)
    if not match:
        return 0
    number = float(match.group(1))
    unit = match.group(2).upper()
    scale = {
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
        "TB": 1024 ** 4,
    }[unit]
    return int(number * scale)


def _release_text(item: dict) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("name", "details", "source", "codec", "quality")
    ).lower()


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _audio_hint(text: str) -> str:
    """Infer the release audio family from common scene/P2P naming shorthand.

    In particular, ``DD5.1`` and ``DD 5.1`` are extremely common names for
    Dolby Digital (AC-3).  Missing those made an H.264 MP4 appear Pi-safe even
    though Safari needed Nomad to create an AAC HLS fallback.
    """
    if _contains(text, ("truehd", "true-hd")):
        return "truehd"
    if _contains(text, ("eac3", "e-ac-3", "e-ac3", "ddp", "dd+", "dolby digital plus")):
        return "eac3"
    if _contains(text, ("dts-hd", "dtshd", "dts")):
        return "dts"
    if _contains(text, ("ac3", "ac-3", "dolby digital")) or re.search(
        r"(?:^|[\s._-])dd(?:[\s._-]*\d(?:\.\d)?)?(?:$|[\s._-])",
        text,
        re.IGNORECASE,
    ):
        return "ac3"
    if _contains(text, ("aac", "mp4a")):
        return "aac"
    return ""


def _analyse_release(item: dict, media_type: str) -> dict:
    text = _release_text(item)
    quality = str(item.get("quality") or "").strip().lower()
    codec = str(item.get("codec") or "").strip().lower()
    size = _size_bytes(item.get("size") or "")

    movie = str(media_type or "movie").lower() != "series"
    max_gb = _env_float(
        "NOMAD_DEBRID_MAX_MOVIE_GB" if movie else "NOMAD_DEBRID_MAX_EPISODE_GB",
        8.0 if movie else 3.0,
        0.5,
        50.0,
    )
    max_bytes = int(max_gb * (1024 ** 3))
    target_gb = 3.5 if movie else 1.2
    target_bytes = int(target_gb * (1024 ** 3))

    is_1080 = quality == "1080p" or "1080p" in text
    is_h264 = codec == "h264" or _contains(text, ("h264", "h.264", "x264", "avc"))
    is_mp4 = bool(re.search(r"(?:^|[\s._-])mp4(?:$|[\s._-])|\.mp4(?:$|[\s._-])", text))
    is_mkv = bool(re.search(r"(?:^|[\s._-])mkv(?:$|[\s._-])|\.mkv(?:$|[\s._-])", text))
    audio_hint = _audio_hint(text)
    is_aac = audio_hint == "aac"
    incompatible_audio = audio_hint in {"ac3", "eac3", "dts", "truehd"}

    heavy_terms = []
    checks = (
        ("4K", ("2160p", " 4k", ".4k", "uhd")),
        ("HEVC", ("hevc", "h265", "h.265", "x265")),
        ("AV1", ("av1",)),
        ("REMUX", ("remux",)),
        ("10-bit", ("10bit", "10-bit", "yuv420p10")),
        ("HDR", ("hdr10", " hdr", ".hdr", "dolby vision", "dovi", " dv ")),
        ("CAM", ("hdcam", " cam ", ".cam.")),
    )
    for label, terms in checks:
        if _contains(text, terms):
            heavy_terms.append(label)

    oversize = bool(size and size > max_bytes)
    if oversize:
        heavy_terms.append(f">{max_gb:g}GB")

    # "Pi-safe" means the release does not advertise a codec that forces live
    # audio/video conversion on our tiny-memory default.  H.264 with AC-3/DTS is
    # still a useful cheap fallback, but it is intentionally not presented as
    # equally safe as AAC/direct media.
    base_h264 = bool(is_1080 and is_h264 and not heavy_terms)
    audio_fallback = bool(base_h264 and incompatible_audio)
    compatible = bool(base_h264 and not incompatible_audio)
    direct_candidate = bool(compatible and is_mp4 and is_aac)

    score = 0.0
    if compatible:
        score += 100
    if direct_candidate:
        score += 80
    elif audio_fallback:
        score += 20
    elif is_mp4:
        score += 35
    elif is_mkv:
        score -= 5
    if is_aac:
        score += 20
    if incompatible_audio:
        score -= 40
    if size:
        # Prefer sensible encodes instead of enormous remuxes or implausibly tiny
        # files. This is intentionally gentle: compatibility matters more.
        distance = abs(size - target_bytes) / max(1, target_bytes)
        score += max(-20.0, 18.0 - (distance * 12.0))
    seeders = int(item.get("seeders") or 0)
    score += min(20.0, math.log2(max(1, seeders) + 1) * 3.0)
    score -= len(heavy_terms) * 80

    reasons = []
    if not is_1080:
        reasons.append("not 1080p")
    if not is_h264:
        reasons.append("not H.264")
    reasons.extend(heavy_terms)
    if audio_fallback:
        reasons.append(f"{audio_hint.upper()} audio needs AAC conversion")
    if compatible and not is_mp4:
        reasons.append("MP4 not identified")
    if compatible and not is_aac:
        reasons.append("AAC not identified")

    return {
        "lite_compatible": compatible,
        "lite_direct_candidate": direct_candidate,
        "lite_audio_fallback": audio_fallback,
        "lite_score": round(score, 2),
        "lite_reasons": reasons,
        "lite_size_bytes": size,
        "lite_max_size_bytes": max_bytes,
        "lite_max_size_gb": max_gb,
        "container_hint": "mp4" if is_mp4 else "mkv" if is_mkv else "",
        "audio_hint": audio_hint,
    }


def _lite_search(
    query: str,
    media_type: str = "movie",
    imdb_id: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> list[dict]:
    results = _ORIGINAL_SEARCH(
        query,
        media_type=media_type,
        imdb_id=imdb_id,
        season=season,
        episode=episode,
    )
    enriched: list[dict] = []
    for source in results:
        item = dict(source)
        item.update(_analyse_release(item, media_type))
        enriched.append(item)

    enriched.sort(
        key=lambda item: (
            0 if item.get("lite_direct_candidate") else
            1 if item.get("lite_compatible") else
            2 if item.get("lite_audio_fallback") else 3,
            -float(item.get("lite_score") or 0),
            -int(item.get("seeders") or 0),
            int(item.get("lite_size_bytes") or (1 << 62)),
            str(item.get("name") or "").lower(),
        )
    )
    return enriched


def install_debrid_lite_search_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    with _LOCK:
        if _INSTALLED:
            return
        debrid_module.search_torrentio = _lite_search
        _INSTALLED = True
