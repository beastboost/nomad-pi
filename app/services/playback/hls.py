"""FFmpeg/GStreamer-backed HLS execution for Nomad playback sessions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os
import shutil
import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

import psutil

from .encoders import (
    SOFTWARE_VIDEO_ENCODERS,
    is_hardware_encoder,
    video_encoder_args,
    video_encoder_candidates,
)
from .gstreamer_a733 import a733_backend_allowed, build_a733_hls_command
from .planner import PlaybackMode


class HLSJobError(RuntimeError):
    pass


@dataclass
class HLSJob:
    session_id: str
    source_path: str
    directory: Path
    process: Optional[subprocess.Popen]
    log_path: Path
    encoder: Optional[str] = None
    fallback_encoder: Optional[str] = None
    fallback_cmd: Optional[list[str]] = None
    fallback_attempted: bool = False


AUDIO_ENCODERS = {
    "aac": "aac",
    "opus": "libopus",
    "mp3": "libmp3lame",
    "vorbis": "libvorbis",
    "alac": "alac",
}


def _hardware_backend(name: Optional[str]) -> bool:
    return bool(name and (is_hardware_encoder(name) or name == "gst:omxh264videoenc"))


def fit_dimensions(
    width: Optional[int],
    height: Optional[int],
    max_width: Optional[int],
    max_height: Optional[int],
) -> Optional[Tuple[int, int]]:
    if not width or not height:
        return None
    scale = 1.0
    if max_width and width > max_width:
        scale = min(scale, max_width / width)
    if max_height and height > max_height:
        scale = min(scale, max_height / height)
    if scale >= 1.0:
        return None
    out_w = max(2, int(width * scale) // 2 * 2)
    out_h = max(2, int(height * scale) // 2 * 2)
    return out_w, out_h


@lru_cache(maxsize=4)
def ffmpeg_supports_readrate(ffmpeg_path: Optional[str] = None) -> bool:
    """Return whether this FFmpeg build exposes the newer ``-readrate`` input option.

    Radxa vendor images can ship an older FFmpeg that still supports ``-re``
    but predates ``-readrate``. Merely constructing a command with -readrate on
    those builds makes FFmpeg exit before opening the media, so detect the
    option once per executable and use the legacy pacing flag when necessary.
    """
    ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-h", "full"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "-readrate " in (result.stdout or "") or "-readrate\t" in (result.stdout or "")


def streaming_input_readrate(mode: str | PlaybackMode) -> Optional[float]:
    """Cap cheap stream-copy jobs on small appliances so they do not saturate I/O.

    A remux/audio-only transcode can otherwise consume a multi-gigabyte movie as
    fast as storage allows while the same device is serving the growing HLS
    cache. On <2 GiB appliances we default to 2x media rate: enough headroom for
    playback without racing through the whole source. Set NOMAD_HLS_READRATE to
    ``off``/``0`` to disable or a positive number to override.

    Older FFmpeg builds that cannot express an arbitrary read rate are handled
    by build_hls_command(), which safely falls back to the long-supported ``-re``
    real-time pacing option instead of failing playback.
    """
    playback_mode = mode if isinstance(mode, PlaybackMode) else PlaybackMode(mode)
    if playback_mode not in {PlaybackMode.REMUX, PlaybackMode.TRANSCODE_AUDIO}:
        return None

    raw = str(os.environ.get("NOMAD_HLS_READRATE", "auto")).strip().lower()
    if raw in {"off", "false", "no", "0"}:
        return None
    if raw not in {"", "auto"}:
        try:
            value = float(raw)
            return max(0.5, min(8.0, value)) if value > 0 else None
        except (TypeError, ValueError):
            pass

    try:
        total_ram = int(psutil.virtual_memory().total)
    except Exception:
        return None
    return 2.0 if total_ram < 2 * 1024 * 1024 * 1024 else None


def build_hls_command(
    *,
    source_path: str,
    output_dir: Path,
    mode: str,
    target_video_codec: Optional[str],
    target_audio_codec: Optional[str],
    audio_stream_index: Optional[int] = None,
    subtitle_stream_index: Optional[int] = None,
    video_encoder_override: Optional[str] = None,
    source_video_codec: Optional[str] = None,
    source_width: Optional[int] = None,
    source_height: Optional[int] = None,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    max_bitrate: Optional[int] = None,
    start_position: float = 0,
    input_readrate: Optional[float] = None,
    readrate_supported: Optional[bool] = None,
) -> list[str]:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    output_dir = Path(output_dir)
    init_name = "init.mp4"
    segment_pattern = str(output_dir / "segment_%05d.m4s")
    playlist_path = str(output_dir / "index.m3u8")

    playback_mode = PlaybackMode(mode)
    source_codec = str(source_video_codec or "").strip().lower()
    if subtitle_stream_index is not None and playback_mode != PlaybackMode.TRANSCODE_VIDEO:
        raise HLSJobError("Image subtitle burn-in requires video transcoding")

    dims = fit_dimensions(source_width, source_height, max_width, max_height)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-y"]
    if start_position and start_position > 0:
        cmd += ["-ss", f"{float(start_position):.3f}"]
    if input_readrate:
        supports_readrate = (
            ffmpeg_supports_readrate(ffmpeg)
            if readrate_supported is None
            else bool(readrate_supported)
        )
        if supports_readrate:
            cmd += ["-readrate", f"{float(input_readrate):.3f}"]
        else:
            # FFmpeg has supported -re for many years. It is equivalent to a
            # 1x input read rate, so it is conservative compared with our 2x
            # low-memory default but prevents both I/O runaway and a startup
            # failure on older Radxa/vendor FFmpeg packages.
            cmd += ["-re"]
    cmd += ["-i", source_path]

    # Graphic subtitle streams (PGS/DVD/DVB) are decoded as bitmap frames.
    # FFmpeg's overlay compatibility path can blend them directly with the
    # video stream. Overlay before scaling so subtitle coordinates still match
    # the source frame, then scale the composited frame if the client requested
    # a lower quality profile.
    if subtitle_stream_index is not None:
        if dims:
            graph = (
                f"[0:v:0][0:{int(subtitle_stream_index)}]overlay[vsub];"
                f"[vsub]scale={dims[0]}:{dims[1]}[vout]"
            )
        else:
            graph = f"[0:v:0][0:{int(subtitle_stream_index)}]overlay[vout]"
        cmd += ["-filter_complex", graph, "-map", "[vout]"]
    else:
        cmd += ["-map", "0:v:0?"]

    if audio_stream_index is None:
        cmd += ["-map", "0:a:0?"]
    else:
        cmd += ["-map", f"0:{int(audio_stream_index)}?"]

    if playback_mode == PlaybackMode.REMUX:
        cmd += ["-c:v", "copy", "-c:a", "copy"]
        if source_codec in {"hevc", "h265"}:
            # Apple requires/strongly prefers hvc1 signalling for HEVC carried
            # in MP4/fMP4. This changes the sample entry without re-encoding.
            cmd += ["-tag:v", "hvc1"]
    elif playback_mode == PlaybackMode.TRANSCODE_AUDIO:
        audio_encoder = AUDIO_ENCODERS.get((target_audio_codec or "aac").lower(), "aac")
        cmd += ["-c:v", "copy", "-c:a", audio_encoder]
        if source_codec in {"hevc", "h265"}:
            cmd += ["-tag:v", "hvc1"]
        if audio_encoder in {"aac", "libopus", "libmp3lame"}:
            cmd += ["-b:a", "192k"]
    elif playback_mode == PlaybackMode.TRANSCODE_VIDEO:
        target_codec = (target_video_codec or "h264").lower()
        video_encoder = video_encoder_override or SOFTWARE_VIDEO_ENCODERS.get(target_codec, "libx264")
        cmd += ["-c:v", video_encoder]
        cmd += video_encoder_args(video_encoder, max_bitrate=max_bitrate)

        # A 10-bit HEVC/VP9 source can otherwise produce a 10-bit H.264 output
        # with some FFmpeg/x264 builds. Baseline browser/iPhone compatibility
        # is much stronger when generated H.264 is explicitly 8-bit 4:2:0.
        if target_codec in {"h264", "avc"}:
            cmd += ["-pix_fmt", "yuv420p"]
        elif target_codec in {"hevc", "h265"}:
            cmd += ["-pix_fmt", "yuv420p", "-tag:v", "hvc1"]

        if dims and subtitle_stream_index is None:
            cmd += ["-vf", f"scale={dims[0]}:{dims[1]}"]

        if target_audio_codec:
            audio_encoder = AUDIO_ENCODERS.get(target_audio_codec.lower(), "aac")
            cmd += ["-c:a", audio_encoder]
            if audio_encoder in {"aac", "libopus", "libmp3lame"}:
                cmd += ["-b:a", "192k"]
        else:
            cmd += ["-c:a", "copy"]
    else:
        raise HLSJobError(f"Playback mode {mode!r} does not require HLS")

    cmd += [
        "-avoid_negative_ts", "make_zero",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "0",
        "-hls_playlist_type", "event",
        "-hls_segment_type", "fmp4",
        "-hls_fmp4_init_filename", init_name,
        "-hls_flags", "independent_segments+temp_file",
        "-hls_segment_filename", segment_pattern,
        playlist_path,
    ]
    return cmd


class HLSManager:
    def __init__(self, root: str = "data/.nomad_cache/hls"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, HLSJob] = {}
        self._lock = threading.Lock()

    def session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    def playlist_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "index.m3u8"

    def _playlist_complete(self, session_id: str) -> bool:
        path = self.playlist_path(session_id)
        try:
            return "#EXT-X-ENDLIST" in path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False

    def cleanup_cache(self, ttl_seconds: Optional[float] = None) -> int:
        """Remove inactive HLS cache directories older than the configured TTL."""
        if ttl_seconds is None:
            try:
                ttl_seconds = float(os.environ.get("NOMAD_HLS_CACHE_TTL", "86400"))
            except (TypeError, ValueError):
                ttl_seconds = 86400.0
        ttl_seconds = max(300.0, float(ttl_seconds))
        cutoff = time.time() - ttl_seconds

        with self._lock:
            active_ids = {
                session_id
                for session_id, job in self._jobs.items()
                if job.process and job.process.poll() is None
            }

        removed = 0
        try:
            children = list(self.root.iterdir())
        except OSError:
            return 0

        for directory in children:
            if not directory.is_dir() or directory.name in active_ids:
                continue
            try:
                newest_mtime = directory.stat().st_mtime
                for item in directory.iterdir():
                    try:
                        newest_mtime = max(newest_mtime, item.stat().st_mtime)
                    except OSError:
                        continue
                if newest_mtime >= cutoff:
                    continue
                shutil.rmtree(directory, ignore_errors=True)
                if not directory.exists():
                    removed += 1
            except OSError:
                continue
        return removed

    @staticmethod
    def _spawn(cmd: list[str], log_path: Path, note: Optional[str] = None) -> subprocess.Popen:
        if note:
            with open(log_path, "ab") as handle:
                handle.write((f"\n--- {note} ---\n").encode("utf-8", errors="replace"))
        log_handle = open(log_path, "ab", buffering=0)
        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=log_handle,
                close_fds=True,
            )
        finally:
            log_handle.close()

    @staticmethod
    def _clear_outputs(directory: Path) -> None:
        for pattern in ("index.m3u8", "init.mp4", "segment_*.m4s", "segment_*.ts", "*.tmp"):
            for path in directory.glob(pattern):
                try:
                    path.unlink()
                except OSError:
                    pass

    def ensure_job(
        self,
        *,
        session_id: str,
        source_path: str,
        mode: str,
        target_video_codec: Optional[str],
        target_audio_codec: Optional[str],
        audio_stream_index: Optional[int] = None,
        subtitle_stream_index: Optional[int] = None,
        source_video_codec: Optional[str] = None,
        source_width: Optional[int] = None,
        source_height: Optional[int] = None,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        max_bitrate: Optional[int] = None,
        start_position: float = 0,
    ) -> HLSJob:
        if not shutil.which("ffmpeg"):
            raise HLSJobError("ffmpeg is not installed")

        self.cleanup_cache()

        with self._lock:
            existing = self._jobs.get(session_id)
            if existing and existing.process and existing.process.poll() is None:
                return existing

            directory = self.session_dir(session_id)
            if self._playlist_complete(session_id):
                job = HLSJob(session_id, source_path, directory, None, directory / "ffmpeg.log")
                self._jobs[session_id] = job
                return job

            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
            directory.mkdir(parents=True, exist_ok=True)
            log_path = directory / "ffmpeg.log"

            playback_mode = PlaybackMode(mode)
            encoder_candidates: list[Optional[str]] = [None]
            if playback_mode == PlaybackMode.TRANSCODE_VIDEO:
                encoder_candidates = list(video_encoder_candidates(target_video_codec))
                if not encoder_candidates:
                    raise HLSJobError(
                        "Hardware acceleration was forced but no supported hardware encoder was detected"
                    )

            common = dict(
                source_path=source_path,
                output_dir=directory,
                mode=mode,
                target_video_codec=target_video_codec,
                target_audio_codec=target_audio_codec,
                audio_stream_index=audio_stream_index,
                subtitle_stream_index=subtitle_stream_index,
                source_video_codec=source_video_codec,
                source_width=source_width,
                source_height=source_height,
                max_width=max_width,
                max_height=max_height,
                max_bitrate=max_bitrate,
                start_position=start_position,
                input_readrate=streaming_input_readrate(playback_mode),
            )

            use_a733_gst = (
                playback_mode == PlaybackMode.TRANSCODE_VIDEO
                and a733_backend_allowed(
                    target_video_codec=target_video_codec,
                    audio_stream_index=audio_stream_index,
                    subtitle_stream_index=subtitle_stream_index,
                )
            )

            fallback_cmd = None
            if use_a733_gst:
                dims = fit_dimensions(source_width, source_height, max_width, max_height)
                primary_encoder = "gst:omxh264videoenc"
                # Do not fall back to an unvalidated generic V4L2 wrapper after
                # the vendor path fails. The deterministic safety net is x264.
                fallback_encoder = SOFTWARE_VIDEO_ENCODERS.get(
                    str(target_video_codec or "h264").lower(),
                    "libx264",
                )
                cmd = build_a733_hls_command(
                    source_path=source_path,
                    output_dir=directory,
                    start_position=start_position,
                    width=dims[0] if dims else None,
                    height=dims[1] if dims else None,
                    max_bitrate=max_bitrate,
                )
                fallback_cmd = build_hls_command(
                    **common,
                    video_encoder_override=fallback_encoder,
                )
            else:
                primary_encoder = encoder_candidates[0]
                fallback_encoder = encoder_candidates[1] if len(encoder_candidates) > 1 else None
                cmd = build_hls_command(
                    **common,
                    video_encoder_override=primary_encoder,
                )
                if fallback_encoder:
                    fallback_cmd = build_hls_command(
                        **common,
                        video_encoder_override=fallback_encoder,
                    )

            process = self._spawn(
                cmd,
                log_path,
                note=(
                    "starting validated A733 GStreamer/OpenMAX encoder omxh264videoenc"
                    if primary_encoder == "gst:omxh264videoenc" else
                    (
                        f"starting {'hardware' if _hardware_backend(primary_encoder) else 'software'} "
                        f"encoder {primary_encoder}"
                        if primary_encoder else "starting HLS stream-copy job"
                    )
                ),
            )
            job = HLSJob(
                session_id=session_id,
                source_path=source_path,
                directory=directory,
                process=process,
                log_path=log_path,
                encoder=primary_encoder,
                fallback_encoder=fallback_encoder,
                fallback_cmd=fallback_cmd,
            )
            self._jobs[session_id] = job
            return job

    def _try_fallback(self, job: HLSJob) -> bool:
        if not job.fallback_cmd or job.fallback_attempted:
            return False
        with self._lock:
            current = self._jobs.get(job.session_id)
            if current is not job or job.fallback_attempted:
                return False
            job.fallback_attempted = True
            self._clear_outputs(job.directory)
            job.process = self._spawn(
                job.fallback_cmd,
                job.log_path,
                note=f"hardware backend failed; falling back to {job.fallback_encoder}",
            )
            job.encoder = job.fallback_encoder
            job.fallback_cmd = None
            return True

    def wait_until_ready(self, session_id: str, timeout: Optional[float] = None) -> Path:
        if timeout is None:
            try:
                timeout = float(os.environ.get("NOMAD_HLS_START_TIMEOUT", "20"))
            except (TypeError, ValueError):
                timeout = 20.0
        timeout = max(0.1, float(timeout))
        deadline = time.monotonic() + timeout
        playlist = self.playlist_path(session_id)

        while True:
            while time.monotonic() < deadline:
                if playlist.exists() and playlist.stat().st_size > 0:
                    return playlist
                with self._lock:
                    job = self._jobs.get(session_id)
                if job and job.process and job.process.poll() is not None:
                    if self._try_fallback(job):
                        # Give the software fallback its own full startup window.
                        deadline = time.monotonic() + timeout
                        break
                    message = self.log_tail(session_id)
                    raise HLSJobError(message or f"HLS backend exited with code {job.process.returncode}")
                time.sleep(0.1)
            else:
                with self._lock:
                    job = self._jobs.get(session_id)
                if job and self._try_fallback(job):
                    deadline = time.monotonic() + timeout
                    continue
                raise HLSJobError(f"Timed out after {timeout:.1f}s waiting for the HLS playlist")
            continue

    def status(self, session_id: str) -> dict:
        playlist = self.playlist_path(session_id)
        with self._lock:
            job = self._jobs.get(session_id)
        running = bool(job and job.process and job.process.poll() is None)
        return {
            "running": running,
            "playlist_ready": playlist.exists() and playlist.stat().st_size > 0,
            "complete": self._playlist_complete(session_id),
            "returncode": None if not job or not job.process or running else job.process.returncode,
            "encoder": job.encoder if job else None,
            "hardware_accelerated": bool(job and _hardware_backend(job.encoder)),
            "fallback_attempted": bool(job and job.fallback_attempted),
        }

    def stop(self, session_id: str, *, remove_cache: bool = False) -> None:
        with self._lock:
            job = self._jobs.pop(session_id, None)
        if job and job.process and job.process.poll() is None:
            job.process.terminate()
            try:
                job.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                job.process.kill()
        if remove_cache:
            shutil.rmtree(self.session_dir(session_id), ignore_errors=True)

    def log_tail(self, session_id: str, max_bytes: int = 4000) -> str:
        path = self.session_dir(session_id) / "ffmpeg.log"
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - max_bytes))
                return handle.read().decode("utf-8", errors="replace").strip()
        except OSError:
            return ""
