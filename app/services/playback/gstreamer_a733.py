"""Radxa/Allwinner A733 GStreamer hardware-transcode support.

Radxa's supported Debian media path for A733 is GStreamer + OpenMAX.  This
module keeps that vendor stack separate from FFmpeg capability detection and
only advertises the backend when the exact elements Nomad needs are present and
the hardware encoder passes a real encode smoke test.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import os
import shutil
import subprocess
from typing import Optional

from app.services.platform_info import platform_info


_REQUIRED_ELEMENTS = (
    "uridecodebin",
    "hlssink2",
    "avenc_aac",
    "h264parse",
    "omxh264videoenc",
)


def _run(args: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


@lru_cache(maxsize=1)
def a733_gstreamer_status() -> dict:
    system = platform_info()
    inspect = shutil.which("gst-inspect-1.0")
    launch = shutil.which("gst-launch-1.0")
    status = {
        "platform": bool(system.get("is_allwinner_a733")),
        "gst_inspect": inspect,
        "gst_launch": launch,
        "elements": {},
        "encoder_usable": False,
        "usable": False,
        "detail": "",
    }
    if not status["platform"]:
        status["detail"] = "not an Allwinner A733 host"
        return status
    if not inspect or not launch:
        status["detail"] = "GStreamer tools are not installed"
        return status

    elements: dict[str, bool] = {}
    for name in _REQUIRED_ELEMENTS:
        rc, _ = _run([inspect, name], timeout=8)
        elements[name] = rc == 0
    status["elements"] = elements
    missing = [name for name, ok in elements.items() if not ok]
    if missing:
        status["detail"] = "missing GStreamer elements: " + ", ".join(missing)
        return status

    # This is essentially Radxa's documented OMX encode test, shortened to a
    # few frames and terminating in fakesink so it works on a headless server.
    rc, output = _run([
        launch, "-q", "-e",
        "videotestsrc", "num-buffers=4", "!",
        "video/x-raw,width=320,height=240,framerate=1/1", "!",
        "omxh264videoenc", "!", "h264parse", "!", "fakesink",
    ], timeout=12)
    status["encoder_usable"] = rc == 0
    status["usable"] = rc == 0
    status["detail"] = (
        "omxh264videoenc passed a runtime encode test"
        if rc == 0 else
        (output.strip()[-1000:] or f"omxh264videoenc test exited with {rc}")
    )
    return status


def build_a733_hls_command(
    *,
    source_path: str,
    output_dir: Path,
    start_position: float = 0,
    width: Optional[int] = None,
    height: Optional[int] = None,
    max_bitrate: Optional[int] = None,
) -> list[str]:
    """Build the system-Python worker command for A733 OMX -> MPEG-TS HLS."""
    root = Path(__file__).resolve().parents[3]
    worker = root / "scripts" / "gst-a733-hls.py"
    python = "/usr/bin/python3" if Path("/usr/bin/python3").is_file() else (shutil.which("python3") or "python3")
    cmd = [
        "/usr/bin/env" if Path("/usr/bin/env").is_file() else (shutil.which("env") or "env"),
        # Prefer the vendor decoders when uridecodebin can use them. Missing
        # decoder elements are harmless; GStreamer ignores unknown rank names.
        "GST_PLUGIN_FEATURE_RANK=omxh264dec:MAX,omxhevcvideodec:MAX,omxvp9videodec:MAX",
        python,
        str(worker),
        "--source", source_path,
        "--output", str(Path(output_dir)),
        "--start", f"{max(0.0, float(start_position or 0)):.3f}",
    ]
    if width and height:
        cmd += ["--width", str(int(width)), "--height", str(int(height))]
    if max_bitrate:
        cmd += ["--bitrate", str(max(250_000, int(max_bitrate)))]
    return cmd


def a733_backend_allowed(
    *,
    target_video_codec: Optional[str],
    audio_stream_index: Optional[int],
    subtitle_stream_index: Optional[int],
) -> bool:
    """Return whether this playback request can safely use the first A733 path.

    The initial backend intentionally handles the common/default A/V case.  A
    user-selected alternate audio stream or image-subtitle burn-in stays on the
    FFmpeg path until the GStreamer stream-selection/burn-in implementation can
    preserve those semantics exactly.
    """
    policy = str(os.environ.get("NOMAD_A733_GSTREAMER", "auto")).strip().lower()
    if policy in {"off", "0", "false", "no"}:
        return False
    if str(target_video_codec or "h264").lower() not in {"h264", "avc"}:
        return False
    if audio_stream_index is not None or subtitle_stream_index is not None:
        return False
    return bool(a733_gstreamer_status().get("usable"))
