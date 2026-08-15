#!/usr/bin/env python3
"""Nomad Pi playback-core readiness and real FFmpeg smoke tests.

Usage:
    python3 scripts/playback-selftest.py
    python3 scripts/playback-selftest.py --smoke-hls
    python3 scripts/playback-selftest.py --smoke-abr
    python3 scripts/playback-selftest.py --smoke-hls --smoke-abr
"""

from __future__ import annotations

import argparse
import json
import os
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
from app.services.playback.abr import ABRManager, ABRRendition
from app.services.playback.hls import HLSManager
from app.services.playback.probe import probe_media


def run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _generate_fixture(path: Path, *, width: int, height: int, seconds: int = 2) -> tuple[bool, str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg is required"
    generate = run([
        ffmpeg,
        "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000",
        "-t", str(seconds),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k",
        "-shortest",
        str(path),
    ], timeout=90)
    if generate.returncode != 0:
        return False, (generate.stderr or generate.stdout or "ffmpeg fixture generation failed")[-4000:]
    return True, ""


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

        ok, detail = _generate_fixture(source, width=320, height=180)
        if not ok:
            return {"status": "fail", "stage": "generate_fixture", "detail": detail}

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
        output_ok = bool(
            playlist.is_file()
            and playlist.stat().st_size > 0
            and init.is_file()
            and init.stat().st_size > 0
            and segments
            and "#EXTM3U" in text
        )
        result = {
            "status": "ok" if output_ok else "fail",
            "stage": "complete" if output_ok else "verify_output",
            "probe": {
                "container": probed.container,
                "video_codec": probed.video_codec,
                "audio_codec": probed.audio_codec,
                "width": probed.width,
                "height": probed.height,
                "duration": probed.duration,
            },
            "playlist": playlist.name,
            "init_segment": init.name,
            "media_segments": len(segments),
        }
        manager.stop(session_id, remove_cache=True)
        return result


def smoke_abr() -> dict:
    """Exercise a real two-rendition FFmpeg HLS master playlist.

    This smoke intentionally forces software H.264 so it is deterministic on
    generic CI runners and also works on an SBC whose hardware encoder is not
    configured. Runtime playback can still use NOMAD_ABR/NOMAD_HW_ACCEL policy.
    """
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        return {
            "status": "fail",
            "stage": "prerequisites",
            "detail": "ffmpeg and ffprobe are required",
        }

    with tempfile.TemporaryDirectory(prefix="nomad-abr-selftest-") as tmp:
        root = Path(tmp)
        source = root / "source.mkv"
        cache = root / "abr"
        ok, detail = _generate_fixture(source, width=1280, height=720)
        if not ok:
            return {"status": "fail", "stage": "generate_fixture", "detail": detail}

        try:
            probed = probe_media(str(source))
        except Exception as exc:
            return {"status": "fail", "stage": "ffprobe", "detail": str(exc)}

        manager = ABRManager(root=str(cache))
        session_id = "abr-selftest"
        renditions = (
            ABRRendition("720p", 1280, 720, 2_500_000),
            ABRRendition("480p", 854, 480, 1_200_000),
        )
        old_abr = os.environ.get("NOMAD_ABR")
        old_hw = os.environ.get("NOMAD_HW_ACCEL")
        try:
            os.environ["NOMAD_ABR"] = "force"
            os.environ["NOMAD_HW_ACCEL"] = "off"
            manager.ensure_job(
                session_id=session_id,
                source_path=str(source),
                renditions=renditions,
                start_position=0,
            )
            master = manager.wait_until_ready(session_id, timeout=45)
        except Exception as exc:
            return {
                "status": "fail",
                "stage": "abr",
                "detail": str(exc),
                "ffmpeg_log": manager.log_tail(session_id),
            }
        finally:
            if old_abr is None:
                os.environ.pop("NOMAD_ABR", None)
            else:
                os.environ["NOMAD_ABR"] = old_abr
            if old_hw is None:
                os.environ.pop("NOMAD_HW_ACCEL", None)
            else:
                os.environ["NOMAD_HW_ACCEL"] = old_hw

        session_dir = manager.session_dir(session_id)
        master_text = master.read_text(encoding="utf-8", errors="replace") if master.exists() else ""
        variants = [session_dir / "variant_720p.m3u8", session_dir / "variant_480p.m3u8"]
        inits = [session_dir / "init_720p.mp4", session_dir / "init_480p.mp4"]
        segment_counts = {
            "720p": len(list(session_dir.glob("segment_720p_*.m4s"))),
            "480p": len(list(session_dir.glob("segment_480p_*.m4s"))),
        }
        output_ok = bool(
            master.is_file()
            and "#EXTM3U" in master_text
            and "variant_720p.m3u8" in master_text
            and "variant_480p.m3u8" in master_text
            and all(path.is_file() and path.stat().st_size > 0 for path in variants)
            and all(path.is_file() and path.stat().st_size > 0 for path in inits)
            and all(count > 0 for count in segment_counts.values())
        )
        result = {
            "status": "ok" if output_ok else "fail",
            "stage": "complete" if output_ok else "verify_output",
            "probe": {
                "video_codec": probed.video_codec,
                "audio_codec": probed.audio_codec,
                "width": probed.width,
                "height": probed.height,
                "duration": probed.duration,
            },
            "master_playlist": master.name,
            "variants": [path.name for path in variants],
            "init_segments": [path.name for path in inits],
            "media_segments": segment_counts,
        }
        manager.stop(session_id, remove_cache=True)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Nomad Pi playback-core readiness")
    parser.add_argument(
        "--smoke-hls",
        action="store_true",
        help="generate a synthetic video and exercise real single-rendition FFmpeg HLS output",
    )
    parser.add_argument(
        "--smoke-abr",
        action="store_true",
        help="generate a 720p synthetic video and exercise a real 720p/480p HLS master playlist",
    )
    args = parser.parse_args()

    report = playback_health(user_id=0)
    result = {"readiness": report}
    if args.smoke_hls:
        result["hls_smoke_test"] = smoke_hls()
    if args.smoke_abr:
        result["abr_smoke_test"] = smoke_abr()

    print(json.dumps(result, indent=2))
    readiness_failed = report.get("status") == "fail"
    smoke_failed = (
        (args.smoke_hls and result["hls_smoke_test"].get("status") != "ok")
        or (args.smoke_abr and result["abr_smoke_test"].get("status") != "ok")
    )
    return 1 if readiness_failed or smoke_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
