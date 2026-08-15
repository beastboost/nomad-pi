"""FFmpeg-backed HLS execution for Nomad Pi playback sessions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
import threading
import time
from typing import Dict, Iterable, Optional, Tuple

from .planner import PlaybackMode


class HLSJobError(RuntimeError):
    pass


@dataclass
class HLSJob:
    session_id: str
    source_path: str
    directory: Path
    process: subprocess.Popen
    log_path: Path


VIDEO_ENCODERS = {
    "h264": "libx264",
    "avc": "libx264",
    "hevc": "libx265",
    "h265": "libx265",
    "vp9": "libvpx-vp9",
    "av1": "libaom-av1",
}

AUDIO_ENCODERS = {
    "aac": "aac",
    "opus": "libopus",
    "mp3": "libmp3lame",
    "vorbis": "libvorbis",
    "alac": "alac",
}


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


def build_hls_command(
    *,
    source_path: str,
    output_dir: Path,
    mode: str,
    target_video_codec: Optional[str],
    target_audio_codec: Optional[str],
    source_width: Optional[int] = None,
    source_height: Optional[int] = None,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    max_bitrate: Optional[int] = None,
    start_position: float = 0,
) -> list[str]:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    output_dir = Path(output_dir)
    init_name = "init.mp4"
    segment_pattern = str(output_dir / "segment_%05d.m4s")
    playlist_path = str(output_dir / "index.m3u8")

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-y"]
    if start_position and start_position > 0:
        cmd += ["-ss", f"{float(start_position):.3f}"]
    cmd += ["-i", source_path, "-map", "0:v:0?", "-map", "0:a:0?"]

    playback_mode = PlaybackMode(mode)
    if playback_mode == PlaybackMode.REMUX:
        cmd += ["-c:v", "copy", "-c:a", "copy"]
    elif playback_mode == PlaybackMode.TRANSCODE_AUDIO:
        audio_encoder = AUDIO_ENCODERS.get((target_audio_codec or "aac").lower(), "aac")
        cmd += ["-c:v", "copy", "-c:a", audio_encoder]
        if audio_encoder in {"aac", "libopus", "libmp3lame"}:
            cmd += ["-b:a", "192k"]
    elif playback_mode == PlaybackMode.TRANSCODE_VIDEO:
        video_encoder = VIDEO_ENCODERS.get((target_video_codec or "h264").lower(), "libx264")
        cmd += ["-c:v", video_encoder]
        if video_encoder == "libx264":
            cmd += ["-preset", "veryfast", "-crf", "23"]
        elif video_encoder == "libx265":
            cmd += ["-preset", "veryfast", "-crf", "27"]

        dims = fit_dimensions(source_width, source_height, max_width, max_height)
        if dims:
            cmd += ["-vf", f"scale={dims[0]}:{dims[1]}"]
        if max_bitrate:
            bitrate = max(250_000, int(max_bitrate))
            cmd += ["-maxrate", str(bitrate), "-bufsize", str(bitrate * 2)]

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
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "0",
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

    def ensure_job(
        self,
        *,
        session_id: str,
        source_path: str,
        mode: str,
        target_video_codec: Optional[str],
        target_audio_codec: Optional[str],
        source_width: Optional[int] = None,
        source_height: Optional[int] = None,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        max_bitrate: Optional[int] = None,
        start_position: float = 0,
    ) -> HLSJob:
        if not shutil.which("ffmpeg"):
            raise HLSJobError("ffmpeg is not installed")

        with self._lock:
            existing = self._jobs.get(session_id)
            if existing and existing.process.poll() is None:
                return existing

            directory = self.session_dir(session_id)
            if self._playlist_complete(session_id):
                # Completed cache can be served without starting ffmpeg again.
                process = subprocess.Popen(["true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                process.wait()
                job = HLSJob(session_id, source_path, directory, process, directory / "ffmpeg.log")
                self._jobs[session_id] = job
                return job

            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
            directory.mkdir(parents=True, exist_ok=True)
            log_path = directory / "ffmpeg.log"
            cmd = build_hls_command(
                source_path=source_path,
                output_dir=directory,
                mode=mode,
                target_video_codec=target_video_codec,
                target_audio_codec=target_audio_codec,
                source_width=source_width,
                source_height=source_height,
                max_width=max_width,
                max_height=max_height,
                max_bitrate=max_bitrate,
                start_position=start_position,
            )
            log_handle = open(log_path, "ab", buffering=0)
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=log_handle,
                    close_fds=True,
                )
            finally:
                log_handle.close()
            job = HLSJob(session_id, source_path, directory, process, log_path)
            self._jobs[session_id] = job
            return job

    def wait_until_ready(self, session_id: str, timeout: float = 8.0) -> Path:
        deadline = time.monotonic() + max(0.1, float(timeout))
        playlist = self.playlist_path(session_id)
        while time.monotonic() < deadline:
            if playlist.exists() and playlist.stat().st_size > 0:
                return playlist
            with self._lock:
                job = self._jobs.get(session_id)
            if job and job.process.poll() is not None:
                message = self.log_tail(session_id)
                raise HLSJobError(message or f"ffmpeg exited with code {job.process.returncode}")
            time.sleep(0.1)
        raise HLSJobError("Timed out waiting for the HLS playlist")

    def status(self, session_id: str) -> dict:
        playlist = self.playlist_path(session_id)
        with self._lock:
            job = self._jobs.get(session_id)
        running = bool(job and job.process.poll() is None)
        return {
            "running": running,
            "playlist_ready": playlist.exists() and playlist.stat().st_size > 0,
            "complete": self._playlist_complete(session_id),
            "returncode": None if not job or running else job.process.returncode,
        }

    def stop(self, session_id: str, *, remove_cache: bool = False) -> None:
        with self._lock:
            job = self._jobs.pop(session_id, None)
        if job and job.process.poll() is None:
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
