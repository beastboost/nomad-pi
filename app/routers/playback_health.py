"""Runtime readiness diagnostics for the Nomad Pi playback engine."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

from fastapi import APIRouter, Depends
import psutil

from app.routers.auth import get_current_user_id
from app.routers import playback_core as core
from app.services.playback.abr import abr_available, abr_policy
from app.services.playback.encoders import (
    ALL_KNOWN_HARDWARE_ENCODERS,
    HARDWARE_VIDEO_ENCODERS,
    SOFTWARE_VIDEO_ENCODERS,
    hardware_policy,
    video_encoder_candidates,
)


router = APIRouter()

RELEVANT_VIDEO_ENCODERS = set(SOFTWARE_VIDEO_ENCODERS.values()) | ALL_KNOWN_HARDWARE_ENCODERS
RELEVANT_AUDIO_ENCODERS = {"aac", "libopus", "libmp3lame", "libvorbis", "alac"}


def _run(args: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def _ffmpeg_encoders(ffmpeg: str) -> set[str]:
    rc, text = _run([ffmpeg, "-hide_banner", "-encoders"], timeout=12)
    if rc != 0:
        return set()
    found = set()
    for line in text.splitlines():
        match = re.match(r"^\s*[A-Z\.]{6}\s+([^\s]+)", line)
        if match:
            found.add(match.group(1))
    return found


def _ffmpeg_hwaccels(ffmpeg: str) -> list[str]:
    rc, text = _run([ffmpeg, "-hide_banner", "-hwaccels"], timeout=8)
    if rc != 0:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [line for line in lines if not line.lower().startswith("hardware acceleration")]


def _gstreamer_omx() -> dict:
    """Report vendor OMX elements exposed by Radxa/Allwinner images.

    Nomad's primary executor is FFmpeg.  A733 Radxa images often expose the
    vendor VPU through GStreamer/OpenMAX even when distro FFmpeg has no OMX
    wrapper, so report that distinction rather than saying the board has no
    hardware codec support at all.
    """
    gst_inspect = shutil.which("gst-inspect-1.0")
    if not gst_inspect:
        return {"available": False, "path": None, "omx_elements": [], "h264_encoder": False}
    rc, text = _run([gst_inspect], timeout=15)
    if rc != 0:
        return {"available": False, "path": gst_inspect, "omx_elements": [], "h264_encoder": False}
    elements = []
    for line in text.splitlines():
        lower = line.lower()
        if "omx" not in lower:
            continue
        # Typical gst-inspect listing: omx:  omxh264videoenc: OpenMAX H.264 Video Encoder
        match = re.search(r"\b(omx[a-z0-9_]+)\s*:", line, re.I)
        if match:
            elements.append(match.group(1))
    unique = sorted(set(elements))
    return {
        "available": bool(unique),
        "path": gst_inspect,
        "omx_elements": unique,
        "h264_encoder": "omxh264videoenc" in unique,
        "h264_decoder": "omxh264dec" in unique,
        "hevc_decoder": "omxhevcvideodec" in unique,
        "vp9_decoder": "omxvp9videodec" in unique,
    }


def _model_name() -> str:
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            return Path(path).read_text(encoding="utf-8", errors="ignore").replace("\x00", "").strip()
        except OSError:
            pass
    return platform.node() or platform.machine()


def _cache_writable() -> tuple[bool, str | None]:
    root = Path("data/.nomad_cache")
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="playback-health-", dir=root, delete=True) as handle:
            handle.write(b"ok")
            handle.flush()
        return True, None
    except OSError as exc:
        return False, str(exc)


def _check(name: str, ok: bool, detail: str, severity: str = "fail") -> dict:
    return {
        "name": name,
        "status": "ok" if ok else severity,
        "detail": detail,
    }


@router.get("/health")
def playback_health(user_id: int = Depends(get_current_user_id)):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    checks = []

    checks.append(_check(
        "ffmpeg",
        bool(ffmpeg),
        ffmpeg or "ffmpeg not found; remux/transcode playback is unavailable",
    ))
    checks.append(_check(
        "ffprobe",
        bool(ffprobe),
        ffprobe or "ffprobe not found; capability planning and track discovery are unavailable",
    ))

    encoders: set[str] = set()
    hwaccels: list[str] = []
    executable_video = {}
    h264_candidates: list[str] = []
    hevc_candidates: list[str] = []
    hw_policy = hardware_policy()
    if ffmpeg:
        encoders = _ffmpeg_encoders(ffmpeg)
        hwaccels = _ffmpeg_hwaccels(ffmpeg)
        executable_video = {
            codec: encoder in encoders
            for codec, encoder in SOFTWARE_VIDEO_ENCODERS.items()
            if codec in {"h264", "hevc", "vp9", "av1"}
        }
        h264_candidates = video_encoder_candidates("h264", available=encoders, policy=hw_policy)
        hevc_candidates = video_encoder_candidates("hevc", available=encoders, policy=hw_policy)
        h264_hw = [x for x in h264_candidates if x in ALL_KNOWN_HARDWARE_ENCODERS]
        checks.append(_check(
            "H.264 encoder path",
            bool(h264_candidates),
            (
                f"Nomad will try {h264_candidates[0]}"
                + (f" and fall back to {h264_candidates[1]}" if len(h264_candidates) > 1 else "")
            ) if h264_candidates else
            "No H.264 encoder is available under the current hardware policy",
            severity="warn",
        ))
        if h264_hw:
            checks.append(_check(
                "SBC hardware acceleration",
                True,
                f"FFmpeg hardware encoder eligible for execution: {h264_hw[0]}",
                severity="warn",
            ))
        checks.append(_check(
            "AAC encoder",
            "aac" in encoders,
            "AAC encoder available" if "aac" in encoders else "AAC encoder missing; incompatible audio cannot be converted for browser HLS",
            severity="warn",
        ))

    gst_omx = _gstreamer_omx()
    if gst_omx.get("h264_encoder"):
        checks.append(_check(
            "A733/OpenMAX video engine",
            True,
            "GStreamer exposes omxh264videoenc; vendor H.264 hardware encoding is installed",
            severity="warn",
        ))
    elif "A733" in _model_name() or "Cubie A7" in _model_name():
        checks.append(_check(
            "A733/OpenMAX video engine",
            False,
            "A733 detected but omxh264videoenc was not found via gst-inspect-1.0",
            severity="warn",
        ))

    abr_ok, abr_reason, abr_candidates = abr_available(
        available_encoders=encoders,
        policy=abr_policy(),
    ) if ffmpeg else (False, "ffmpeg is unavailable", [])
    checks.append(_check(
        "adaptive bitrate",
        bool(abr_ok and "aac" in encoders),
        abr_reason if abr_ok and "aac" in encoders else (
            "AAC encoder missing; adaptive HLS requires AAC audio" if abr_ok else abr_reason
        ),
        severity="warn",
    ))

    writable, write_error = _cache_writable()
    checks.append(_check(
        "transcode cache",
        writable,
        "data/.nomad_cache is writable" if writable else f"cache is not writable: {write_error}",
    ))

    db_ok = True
    db_error = None
    try:
        core.session_store.ensure_schema()
    except Exception as exc:
        db_ok = False
        db_error = str(exc)
    checks.append(_check(
        "playback session database",
        db_ok,
        "playback_sessions schema ready" if db_ok else f"session schema failed: {db_error}",
    ))

    hls_js = Path("app/static/vendor/hls/hls.min.js").is_file()
    checks.append(_check(
        "offline Hls.js",
        hls_js,
        "vendored Hls.js is present"
        if hls_js else "Hls.js is not vendored yet; Safari native HLS can work, but other browsers need the vendor-assets step or internet fallback",
        severity="warn",
    ))

    statuses = {item["status"] for item in checks}
    overall = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "ok"
    memory = psutil.virtual_memory()
    any_video_encoder = bool(h264_candidates or hevc_candidates or executable_video.get("vp9") or executable_video.get("av1"))
    executable_hardware = sorted({
        encoder
        for codec in ("h264", "hevc")
        for encoder in video_encoder_candidates(codec, available=encoders, policy=hw_policy)
        if encoder in ALL_KNOWN_HARDWARE_ENCODERS
    }) if ffmpeg else []

    return {
        "status": overall,
        "system": {
            "model": _model_name(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": psutil.cpu_count(logical=True),
            "memory_mb": round(memory.total / (1024 * 1024)),
        },
        "ffmpeg": {
            "path": ffmpeg,
            "ffprobe_path": ffprobe,
            "video_encoders": sorted(encoders & RELEVANT_VIDEO_ENCODERS),
            "audio_encoders": sorted(encoders & RELEVANT_AUDIO_ENCODERS),
            "hardware_encoders_detected": sorted(encoders & ALL_KNOWN_HARDWARE_ENCODERS),
            "hardware_accels_detected": sorted(set(hwaccels)),
            "executor_video_codecs": executable_video,
            "hardware_policy": hw_policy,
            "hardware_acceleration_enabled": bool(executable_hardware and hw_policy != "off"),
            "executor_hardware_encoders": executable_hardware,
            "h264_encoder_candidates": h264_candidates,
            "hevc_encoder_candidates": hevc_candidates,
            "supported_sbc_hardware_families": {
                codec: list(values) for codec, values in HARDWARE_VIDEO_ENCODERS.items()
                if codec in {"h264", "hevc"}
            },
        },
        "gstreamer_openmax": {
            **gst_omx,
            "executor_enabled": False,
            "note": (
                "Vendor OMX hardware is detected. Nomad uses it directly when FFmpeg exposes h264_omx; "
                "otherwise it is reported here for the dedicated A733 executor path."
            ),
        },
        "adaptive_bitrate": {
            "policy": abr_policy(),
            "available": bool(abr_ok and "aac" in encoders and writable),
            "reason": abr_reason,
            "encoder_candidates": abr_candidates,
            "software_opt_in": str(os.environ.get("NOMAD_ABR_SOFTWARE", "0")).strip().lower() in {"1", "true", "yes", "on"},
            "ladder": ["1080p", "720p", "480p"],
        },
        "playback_modes": {
            "direct_play": True,
            "remux": bool(ffmpeg and writable),
            "audio_transcode": bool(ffmpeg and writable and "aac" in encoders),
            "video_transcode": bool(ffmpeg and writable and any_video_encoder),
            "adaptive_hls": bool(ffmpeg and writable and abr_ok and "aac" in encoders),
        },
        "checks": checks,
    }
