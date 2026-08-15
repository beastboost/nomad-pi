"""Runtime readiness diagnostics for the Nomad Pi playback engine."""

from __future__ import annotations

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


router = APIRouter()

SOFTWARE_VIDEO_ENCODERS = {
    "h264": "libx264",
    "hevc": "libx265",
    "vp9": "libvpx-vp9",
    "av1": "libaom-av1",
}
RELEVANT_VIDEO_ENCODERS = set(SOFTWARE_VIDEO_ENCODERS.values()) | {
    "h264_v4l2m2m", "hevc_v4l2m2m", "h264_vaapi", "hevc_vaapi",
    "h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv",
    "h264_videotoolbox", "hevc_videotoolbox",
}
RELEVANT_AUDIO_ENCODERS = {"aac", "libopus", "libmp3lame", "libvorbis", "alac"}
HARDWARE_ENCODERS = {
    "h264_v4l2m2m", "hevc_v4l2m2m", "h264_vaapi", "hevc_vaapi",
    "h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv",
    "h264_videotoolbox", "hevc_videotoolbox",
}


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
    if ffmpeg:
        encoders = _ffmpeg_encoders(ffmpeg)
        hwaccels = _ffmpeg_hwaccels(ffmpeg)
        executable_video = {
            codec: encoder in encoders
            for codec, encoder in SOFTWARE_VIDEO_ENCODERS.items()
        }
        checks.append(_check(
            "H.264 software encoder",
            executable_video.get("h264", False),
            "libx264 is available and matches the current HLS executor"
            if executable_video.get("h264") else
            "libx264 is missing; the current executor cannot produce H.264 even if separate hardware encoders are detected",
            severity="warn",
        ))
        checks.append(_check(
            "AAC encoder",
            "aac" in encoders,
            "AAC encoder available" if "aac" in encoders else "AAC encoder missing; incompatible audio cannot be converted for browser HLS",
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
    any_video_encoder = any(executable_video.values())

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
            "hardware_encoders_detected": sorted(encoders & HARDWARE_ENCODERS),
            "hardware_accels_detected": sorted(set(hwaccels)),
            "executor_video_codecs": executable_video,
            "hardware_acceleration_enabled": False,
        },
        "playback_modes": {
            "direct_play": True,
            "remux": bool(ffmpeg and writable),
            "audio_transcode": bool(ffmpeg and writable and "aac" in encoders),
            "video_transcode": bool(ffmpeg and writable and any_video_encoder),
        },
        "checks": checks,
    }
