"""Hardware-aware FFmpeg encoder selection for Nomad playback.

The playback engine deliberately treats hardware acceleration as an
optimization, not a requirement. Only encoder families that can be invoked by
Nomad's current software-frame pipeline are eligible. A software encoder is
always retained as the fallback candidate when present.
"""

from __future__ import annotations

from functools import lru_cache
import os
import re
import shutil
import subprocess
from typing import Iterable, Optional

from app.services.platform_info import platform_info


SOFTWARE_VIDEO_ENCODERS = {
    "h264": "libx264",
    "avc": "libx264",
    "hevc": "libx265",
    "h265": "libx265",
    "vp9": "libvpx-vp9",
    "av1": "libaom-av1",
}

# Conservative hardware candidates that can accept the ordinary decoded-frame
# path used by Nomad. OpenMAX H.264 is included because Allwinner/Radxa images
# may expose the A733 encoder through FFmpeg as h264_omx; if the advertised
# encoder is unusable at runtime HLSManager automatically falls back.
HARDWARE_VIDEO_ENCODERS = {
    "h264": ("h264_v4l2m2m", "h264_rkmpp", "h264_omx"),
    "avc": ("h264_v4l2m2m", "h264_rkmpp", "h264_omx"),
    "hevc": ("hevc_v4l2m2m", "hevc_rkmpp"),
    "h265": ("hevc_v4l2m2m", "hevc_rkmpp"),
}

ALL_KNOWN_HARDWARE_ENCODERS = {
    "h264_v4l2m2m", "hevc_v4l2m2m", "h264_rkmpp", "hevc_rkmpp", "h264_omx",
    "h264_vaapi", "hevc_vaapi", "h264_nvenc", "hevc_nvenc",
    "h264_qsv", "hevc_qsv", "h264_videotoolbox", "hevc_videotoolbox",
}


def _parse_encoders(text: str) -> set[str]:
    found: set[str] = set()
    for line in (text or "").splitlines():
        match = re.match(r"^\s*[A-Z\.]{6}\s+([^\s]+)", line)
        if match:
            found.add(match.group(1))
    return found


@lru_cache(maxsize=2)
def available_ffmpeg_encoders(ffmpeg_path: Optional[str] = None) -> frozenset[str]:
    ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg:
        return frozenset()
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    if result.returncode != 0:
        return frozenset()
    return frozenset(_parse_encoders((result.stdout or "") + (result.stderr or "")))


def _best_hardware_candidate(candidates: list[str], model: Optional[str] = None) -> Optional[str]:
    """Pick the single hardware encoder most appropriate to this machine.

    HLSManager intentionally keeps one hardware attempt plus one software
    fallback. Choosing one hardware candidate here guarantees that a machine
    advertising several wrappers cannot exhaust the fallback slot before
    reaching libx264/libx265.
    """
    if not candidates:
        return None

    if model is None:
        info = platform_info()
        family = str(info.get("family") or "").lower()
        model_text = " ".join((
            str(info.get("model") or ""),
            str(info.get("raw_model") or ""),
            str(info.get("compatible") or ""),
        )).lower()
    else:
        family = ""
        model_text = str(model).lower()

    is_a733 = family == "allwinner-a733" or any(
        token in model_text for token in ("a733", "sun60iw2", "cubie a7", "cubie-a7")
    )

    # Radxa/Allwinner vendor images may expose OpenMAX as the native A733 path.
    # If it is absent, the generic V4L2 M2M wrapper remains eligible below.
    if is_a733 and "h264_omx" in candidates:
        return "h264_omx"

    # Prefer the platform-specific wrapper over generic V4L2 when both are
    # exposed on Rockchip machines.
    if family == "rockchip" or "rockchip" in model_text:
        for name in candidates:
            if name.endswith("_rkmpp"):
                return name

    # On other boards preserve the configured candidate order. For an A733
    # without FFmpeg OMX this means h264_v4l2m2m/hevc_v4l2m2m is tried first.
    return candidates[0]


def hardware_policy() -> str:
    """Return off/auto/force from NOMAD_HW_ACCEL, defaulting safely to auto."""
    value = str(os.environ.get("NOMAD_HW_ACCEL", "auto")).strip().lower()
    return value if value in {"off", "auto", "force"} else "auto"


def video_encoder_candidates(
    codec: Optional[str],
    *,
    available: Optional[Iterable[str]] = None,
    policy: Optional[str] = None,
    model: Optional[str] = None,
) -> list[str]:
    """Return the execution order: one best hardware encoder, then software.

    ``auto`` tries the board-appropriate hardware path first and always keeps a
    software fallback. ``force`` uses only the best detected hardware path.
    ``off`` disables hardware entirely.
    """
    normalized = str(codec or "h264").strip().lower()
    encoders = set(available if available is not None else available_ffmpeg_encoders())
    selected_policy = (policy or hardware_policy()).lower()
    software = SOFTWARE_VIDEO_ENCODERS.get(normalized, "libx264")
    hardware = [
        encoder for encoder in HARDWARE_VIDEO_ENCODERS.get(normalized, ())
        if encoder in encoders
    ]
    best_hardware = _best_hardware_candidate(hardware, model=model)

    if selected_policy == "off":
        return [software]
    if selected_policy == "force":
        return [best_hardware] if best_hardware else []

    candidates = [best_hardware] if best_hardware else []
    if software not in candidates:
        candidates.append(software)
    return candidates


def is_hardware_encoder(name: Optional[str]) -> bool:
    return bool(name and name in ALL_KNOWN_HARDWARE_ENCODERS)


def video_encoder_args(encoder: str, *, max_bitrate: Optional[int] = None) -> list[str]:
    """Return rate-control/preset arguments appropriate to an encoder."""
    if encoder == "libx264":
        args = ["-preset", "veryfast", "-crf", "23"]
    elif encoder == "libx265":
        args = ["-preset", "veryfast", "-crf", "27"]
    elif encoder in {"h264_v4l2m2m", "hevc_v4l2m2m", "h264_rkmpp", "hevc_rkmpp", "h264_omx"}:
        # Hardware SBC encoders are bitrate-driven rather than CRF-driven.
        bitrate = max(500_000, int(max_bitrate or 6_000_000))
        args = ["-b:v", str(bitrate)]
    else:
        args = []

    if max_bitrate:
        bitrate = max(250_000, int(max_bitrate))
        # Avoid duplicating -b:v for hardware paths; maxrate/bufsize are useful
        # for both software and hardware encoders when accepted by the build.
        args += ["-maxrate", str(bitrate), "-bufsize", str(bitrate * 2)]
    return args
