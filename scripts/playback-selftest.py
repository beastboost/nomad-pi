#!/usr/bin/env python3
"""Nomad Pi playback-core readiness and optional real FFmpeg smoke test.

Usage:
    python3 scripts/playback-selftest.py
    python3 scripts/playback-selftest.py --smoke-hls
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

# Allow execution from scripts/ without installing Nomad as a package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.routers.playback_health import playback_health
from app.services.playback.hls import HLSManager
from app.services.playback.probe import probe_media


def run(args: list[str], timeout: int = 45) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def smoke_hls() -> dict:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        return {
            "status": "fail",
            "stage": "prerequisites",
            "detail": "ffmpeg and ffprobe are required",
        }

    with tempfile.TemporaryDirectory(prefix="nomad-playback-selftest-") as tmp:
        root = Path(tmp)
        source = root / "source.mkv"
        cache = root / "hls"

        # Generate a tiny legal synthetic source. Using the same H.264/AAC
        # encoders the browser playback path expects makes this a useful test
        # of the actual FFmpeg package installed on the SBC, not just PATH.
        generate = run([
            ffmpeg,
            "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000",
            "-t", "2",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k",
            "-shortest",
            str(source),
        ])
        if generate.returncode != 0:
            return {
                "status": "fail",
                "stage": "generate_fixture",
                "detail": (generate.stderr or generate.stdout or "ffmpeg fixture generation failed")[-4000:],
            }

        try:
            probed = probe_media(str(source))
        except Exception as exc:
            return {"status": "fail", "stage": "ffprobe", "detail": str(exc)}

        manager = HLSManager(root=str(cache))
        session_id = "selftest"
        try:
            manager.ensure_job(
                session_id=session_id,
                source_path=str(source),
                mode="remux",
                target_video_codec=None,
                target_audio_codec=None,
                source_width=probed.width,
                source_height=probed.height,
                start_position=0,
            )
            playlist = manager.wait_until_ready(session_id, timeout=12)
        except Exception as exc:
            return {
                "status": "fail",
                "stage": "hls",
                "detail": str(exc),
                "ffmpeg_log": manager.log_tail(session_id),
            }

        session_dir = manager.session_dir(session_id)
        segments = sorted(session_dir.glob("segment_*.m4s"))
        init = session_dir / "init.mp4"
        text = playlist.read_text(encoding="utf-8", errors="replace") if playlist.exists() else ""
        ok = bool(
            playlist.is_file()
            and playlist.stat().st_size > 0
            and init.is_file()
            and init.stat().st_size > 0
            and segments
            and "#EXTM3U" in text
        )
        manager.stop(session_id, remove_cache=True)
        return {
            "status": "ok" if ok else "fail",
            "stage": "complete" if ok else "verify_output",
            "probe": {
                "container": probed.container,
                "video_codec": probed.video_codec,
                "audio_codec": probed.audio_codec,
                "width": probed.width,
                "height": probed.height,
            },
            "playlist": bool(playlist),
            "init_segment": init.name,
            "media_segments": len(segments),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Nomad Pi playback-core readiness")
    parser.add_argument(
        "--smoke-hls",
        action="store_true",
        help="generate a 2-second synthetic video and exercise real FFmpeg HLS output",
    )
    args = parser.parse_args()

    report = playback_health(user_id=0)
    result = {"readiness": report}
    if args.smoke_hls:
        result["hls_smoke_test"] = smoke_hls()

    print(json.dumps(result, indent=2))
    readiness_failed = report.get("status") == "fail"
    smoke_failed = args.smoke_hls and result["hls_smoke_test"].get("status") != "ok"
    return 1 if readiness_failed or smoke_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
