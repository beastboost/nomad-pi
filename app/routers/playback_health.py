"""Runtime readiness diagnostics for the Nomad Pi playback engine."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from fastapi import APIRouter, Depends

from app.routers.auth import get_current_user_id
from app.routers import playback_core as core
from app.services.platform_info import platform_info
from app.services.playback.abr import abr_available, abr_policy
from app.services.playback.encoders import (
    ALL_KNOWN_HARDWARE_ENCODERS,
    HARDWARE_VIDEO_ENCODERS,
    SOFTWARE_VIDEO_ENCODERS,
    hardware_policy,
    video_encoder_candidates,
)
from app.services.playback.gstreamer_a733 import a733_gstreamer_status


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


@lru_cache(maxsize=16)
def _validate_video_encoder(ffmpeg: str, encoder: str) -> dict:
    """Actually open an encoder and process one tiny software frame.

    `ffmpeg -encoders` only proves the wrapper was compiled in. SBC vendor
    kernels can advertise V4L2 M2M/OMX wrappers without exposing a usable codec
    device, so diagnostics must distinguish advertised from executable.
    """
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-f", "lavfi",
        "-i", "color=c=black:s=320x240:r=1",
        "-frames:v", "1",
        "-pix_fmt", "yuv420p",
        "-c:v", encoder,
        "-f", "null",
        "-",
    ]
    rc, text = _run(cmd, timeout=10)
    detail = text.strip()
    if len(detail) > 800:
        detail = detail[-800:]
    return {
        "advertised": True,
        "usable": rc == 0,
        "returncode": rc,
        "detail": detail,
    }


def _video_nodes() -> list[dict]:
    nodes: list[dict] = []
    root = Path("/sys/class/video4linux")
    if not root.is_dir():
        return nodes
    for entry in sorted(root.glob("video*"), key=lambda p: p.name):
        try:
            name = (entry / "name").read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            name = ""
        nodes.append({"device": f"/dev/{entry.name}", "name": name})
    return nodes


def _gstreamer_omx() -> dict:
    """Report vendor OMX elements exposed by Radxa/Allwinner images."""
    gst_inspect = shutil.which("gst-inspect-1.0")
    if not gst_inspect:
        return {"available": False, "path": None, "omx_elements": [], "h264_encoder": False}
    rc, text = _run([gst_inspect], timeout=15)
    if rc != 0:
        return {"available": False, "path": gst_inspect, "omx_elements": [], "h264_encoder": False}
    elements = []
    for line in text.splitlines():
        if "omx" not in line.lower():
            continue
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
    system = dict(platform_info())

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
    hardware_validation: dict[str, dict] = {}
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

        advertised_hardware = sorted(encoders & ALL_KNOWN_HARDWARE_ENCODERS)
        for encoder in advertised_hardware:
            # Validate only hardware wrappers Nomad can currently select for
            # H.264/HEVC execution, not unrelated NVENC/QSV wrappers on a host.
            if encoder in set(HARDWARE_VIDEO_ENCODERS.get("h264", ())) | set(HARDWARE_VIDEO_ENCODERS.get("hevc", ())):
                hardware_validation[encoder] = _validate_video_encoder(ffmpeg, encoder)

        h264_hw = [x for x in h264_candidates if x in ALL_KNOWN_HARDWARE_ENCODERS]
        checks.append(_check(
            "H.264 FFmpeg encoder path",
            bool(h264_candidates),
            (
                f"FFmpeg can try {h264_candidates[0]}"
                + (f" and fall back to {h264_candidates[1]}" if len(h264_candidates) > 1 else "")
            ) if h264_candidates else
            "No H.264 encoder is available under the current hardware policy",
            severity="warn",
        ))
        if h264_hw:
            candidate = h264_hw[0]
            validation = hardware_validation.get(candidate, {})
            usable = bool(validation.get("usable"))
            checks.append(_check(
                "FFmpeg SBC hardware acceleration",
                usable,
                (
                    f"{candidate} successfully encoded a test frame"
                    if usable else
                    f"{candidate} is advertised by FFmpeg but failed the runtime encoder test"
                ),
                severity="warn",
            ))
        checks.append(_check(
            "AAC encoder",
            "aac" in encoders,
            "AAC encoder available" if "aac" in encoders else "AAC encoder missing; incompatible audio cannot be converted for browser HLS",
            severity="warn",
        ))

    gst_omx = _gstreamer_omx()
    gst_backend = a733_gstreamer_status() if system.get("is_allwinner_a733") else {
        "platform": False,
        "usable": False,
        "encoder_usable": False,
        "elements": {},
        "detail": "not an Allwinner A733 host",
    }

    if system.get("is_allwinner_a733"):
        if gst_backend.get("usable"):
            checks.append(_check(
                "A733 hardware video path",
                True,
                "Radxa GStreamer/OpenMAX omxh264videoenc passed a runtime test and is enabled for compatible H.264 HLS transcodes",
                severity="warn",
            ))
        else:
            v4l2_usable = bool(hardware_validation.get("h264_v4l2m2m", {}).get("usable"))
            checks.append(_check(
                "A733 hardware video path",
                v4l2_usable,
                (
                    "A733 V4L2 M2M H.264 encoding passed; GStreamer/OpenMAX is unavailable"
                    if v4l2_usable else
                    f"A733 hardware backend is not validated: {gst_backend.get('detail') or 'no working OMX/V4L2 encoder'}"
                ),
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
    any_video_encoder = bool(
        gst_backend.get("usable")
        or h264_candidates
        or hevc_candidates
        or executable_video.get("vp9")
        or executable_video.get("av1")
    )
    executable_hardware = sorted({
        encoder
        for codec in ("h264", "hevc")
        for encoder in video_encoder_candidates(codec, available=encoders, policy=hw_policy)
        if encoder in ALL_KNOWN_HARDWARE_ENCODERS
    }) if ffmpeg else []
    validated_hardware = sorted(
        encoder for encoder, result in hardware_validation.items() if result.get("usable")
    )

    if gst_backend.get("usable"):
        h264_execution_path = ["gst:omxh264videoenc", "libx264"]
    else:
        h264_execution_path = list(h264_candidates)

    return {
        "status": overall,
        "system": system,
        "ffmpeg": {
            "path": ffmpeg,
            "ffprobe_path": ffprobe,
            "video_encoders": sorted(encoders & RELEVANT_VIDEO_ENCODERS),
            "audio_encoders": sorted(encoders & RELEVANT_AUDIO_ENCODERS),
            "hardware_encoders_detected": sorted(encoders & ALL_KNOWN_HARDWARE_ENCODERS),
            "hardware_accels_detected": sorted(set(hwaccels)),
            "hardware_validation": hardware_validation,
            "validated_hardware_encoders": validated_hardware,
            "video_devices": _video_nodes(),
            "executor_video_codecs": executable_video,
            "hardware_policy": hw_policy,
            "hardware_acceleration_enabled": bool(
                gst_backend.get("usable") or (executable_hardware and hw_policy != "off")
            ),
            "executor_hardware_encoders": executable_hardware,
            "h264_encoder_candidates": h264_candidates,
            "h264_execution_path": h264_execution_path,
            "hevc_encoder_candidates": hevc_candidates,
            "supported_sbc_hardware_families": {
                codec: list(values) for codec, values in HARDWARE_VIDEO_ENCODERS.items()
                if codec in {"h264", "hevc"}
            },
        },
        "gstreamer_openmax": {
            **gst_omx,
            "executor_enabled": bool(gst_backend.get("usable")),
            "backend": gst_backend,
            "note": (
                "Validated A733 OMX is used for compatible H.264 HLS transcodes; FFmpeg/libx264 remains the fallback."
                if gst_backend.get("usable") else
                "The A733 vendor backend is not currently validated; FFmpeg paths remain available as fallback."
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
