"""Multi-rendition adaptive HLS execution for Nomad Pi."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import os
import shutil
import subprocess
import threading
import time
from typing import Dict, Iterable, Optional

from .encoders import is_hardware_encoder, video_encoder_candidates


class ABRJobError(RuntimeError):
    pass


@dataclass(frozen=True)
class ABRRendition:
    name: str
    width: int
    height: int
    bitrate: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ABRJob:
    session_id: str
    source_path: str
    directory: Path
    process: Optional[subprocess.Popen]
    log_path: Path
    renditions: tuple[ABRRendition, ...]
    encoder: str
    fallback_encoder: Optional[str] = None
    fallback_cmd: Optional[list[str]] = None
    fallback_attempted: bool = False


DEFAULT_LADDER = (
    ABRRendition("1080p", 1920, 1080, 8_000_000),
    ABRRendition("720p", 1280, 720, 4_000_000),
    ABRRendition("480p", 854, 480, 2_000_000),
)


def abr_policy() -> str:
    value = str(os.environ.get("NOMAD_ABR", "auto")).strip().lower()
    return value if value in {"off", "auto", "force"} else "auto"


def choose_renditions(
    source_width: Optional[int],
    source_height: Optional[int],
    *,
    max_width: Optional[int] = None,
    max_height: Optional[int] = None,
    max_bitrate: Optional[int] = None,
    ladder: Iterable[ABRRendition] = DEFAULT_LADDER,
) -> list[ABRRendition]:
    if not source_width or not source_height:
        return []
    selected: list[ABRRendition] = []
    for rendition in ladder:
        # Never upscale merely to manufacture another ABR rung.
        if rendition.width > source_width or rendition.height > source_height:
            continue
        if max_width and rendition.width > max_width:
            continue
        if max_height and rendition.height > max_height:
            continue
        bitrate = min(rendition.bitrate, int(max_bitrate)) if max_bitrate else rendition.bitrate
        if bitrate < 500_000:
            continue
        selected.append(ABRRendition(rendition.name, rendition.width, rendition.height, bitrate))
    return selected


def abr_available(*, available_encoders: Optional[Iterable[str]] = None, policy: Optional[str] = None) -> tuple[bool, str, list[str]]:
    selected_policy = (policy or abr_policy()).lower()
    candidates = video_encoder_candidates("h264", available=available_encoders, policy="auto")
    hardware = [name for name in candidates if is_hardware_encoder(name)]
    if selected_policy == "off":
        return False, "Adaptive bitrate is disabled by NOMAD_ABR=off", candidates
    if selected_policy == "force":
        return bool(candidates), "Adaptive bitrate forced by configuration", candidates
    if hardware:
        return True, f"Adaptive bitrate can use {hardware[0]}", candidates
    if str(os.environ.get("NOMAD_ABR_SOFTWARE", "0")).strip().lower() in {"1", "true", "yes", "on"}:
        return True, "Adaptive bitrate software transcoding explicitly enabled", candidates
    return False, "Auto ABR requires an executable SBC hardware encoder; set NOMAD_ABR=force or NOMAD_ABR_SOFTWARE=1 to allow software multi-rendition encoding", candidates


def build_abr_command(
    *,
    source_path: str,
    output_dir: Path,
    renditions: Iterable[ABRRendition],
    video_encoder: str,
    audio_stream_index: Optional[int] = None,
    subtitle_stream_index: Optional[int] = None,
    start_position: float = 0,
) -> list[str]:
    variants = list(renditions)
    if len(variants) < 2:
        raise ABRJobError("Adaptive HLS requires at least two renditions")

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    output_dir = Path(output_dir)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-y"]
    if start_position and start_position > 0:
        cmd += ["-ss", f"{float(start_position):.3f}"]
    cmd += ["-i", source_path]

    base_label = "base"
    filters = []
    if subtitle_stream_index is not None:
        filters.append(f"[0:v:0][0:{int(subtitle_stream_index)}]overlay[{base_label}]")
    else:
        filters.append(f"[0:v:0]null[{base_label}]")

    split_outputs = "".join(f"[v{i}]" for i in range(len(variants)))
    filters.append(f"[{base_label}]split={len(variants)}{split_outputs}")
    for i, rendition in enumerate(variants):
        filters.append(f"[v{i}]scale={rendition.width}:{rendition.height}[vo{i}]")
    cmd += ["-filter_complex", ";".join(filters)]

    audio_map = f"0:{int(audio_stream_index)}?" if audio_stream_index is not None else "0:a:0?"
    for i in range(len(variants)):
        cmd += ["-map", f"[vo{i}]", "-map", audio_map]

    for i, rendition in enumerate(variants):
        cmd += [
            f"-c:v:{i}", video_encoder,
            f"-b:v:{i}", str(rendition.bitrate),
            f"-maxrate:v:{i}", str(rendition.bitrate),
            f"-bufsize:v:{i}", str(rendition.bitrate * 2),
            f"-force_key_frames:v:{i}", "expr:gte(t,n_forced*4)",
            f"-c:a:{i}", "aac",
            f"-b:a:{i}", "160k",
            f"-ac:a:{i}", "2",
        ]
        if video_encoder in {"libx264", "libx265"}:
            cmd += [f"-preset:v:{i}", "veryfast"]

    stream_map = " ".join(
        f"v:{i},a:{i},name:{rendition.name}" for i, rendition in enumerate(variants)
    )
    cmd += [
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "0",
        "-hls_segment_type", "fmp4",
        "-hls_fmp4_init_filename", "init_%v.mp4",
        "-hls_flags", "independent_segments+temp_file",
        "-var_stream_map", stream_map,
        "-master_pl_name", "master.m3u8",
        "-hls_segment_filename", str(output_dir / "segment_%v_%05d.m4s"),
        str(output_dir / "variant_%v.m3u8"),
    ]
    return cmd


class ABRManager:
    def __init__(self, root: str = "data/.nomad_cache/abr"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, ABRJob] = {}
        self._lock = threading.Lock()

    def session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    def master_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "master.m3u8"

    def _ready(self, job: ABRJob) -> bool:
        master = self.master_path(job.session_id)
        if not master.is_file() or master.stat().st_size <= 0:
            return False
        for rendition in job.renditions:
            path = job.directory / f"variant_{rendition.name}.m3u8"
            if not path.is_file() or path.stat().st_size <= 0:
                return False
        return True

    @staticmethod
    def _spawn(cmd: list[str], log_path: Path, note: str) -> subprocess.Popen:
        with open(log_path, "ab") as handle:
            handle.write((f"\n--- {note} ---\n").encode("utf-8", errors="replace"))
        log_handle = open(log_path, "ab", buffering=0)
        try:
            return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=log_handle, close_fds=True)
        finally:
            log_handle.close()

    @staticmethod
    def _clear_outputs(directory: Path) -> None:
        for pattern in ("master.m3u8", "variant_*.m3u8", "init_*.mp4", "segment_*.m4s", "*.tmp"):
            for path in directory.glob(pattern):
                try:
                    path.unlink()
                except OSError:
                    pass

    def cleanup_cache(self, ttl_seconds: Optional[float] = None) -> int:
        if ttl_seconds is None:
            try:
                ttl_seconds = float(os.environ.get("NOMAD_HLS_CACHE_TTL", "86400"))
            except (TypeError, ValueError):
                ttl_seconds = 86400.0
        cutoff = time.time() - max(300.0, float(ttl_seconds))
        with self._lock:
            active = {
                sid for sid, job in self._jobs.items()
                if job.process and job.process.poll() is None
            }
        removed = 0
        try:
            children = list(self.root.iterdir())
        except OSError:
            return 0
        for directory in children:
            if not directory.is_dir() or directory.name in active:
                continue
            try:
                newest = max(
                    [directory.stat().st_mtime]
                    + [p.stat().st_mtime for p in directory.iterdir() if p.exists()]
                )
            except OSError:
                continue
            if newest >= cutoff:
                continue
            shutil.rmtree(directory, ignore_errors=True)
            if not directory.exists():
                removed += 1
        return removed

    def ensure_job(
        self,
        *,
        session_id: str,
        source_path: str,
        renditions: Iterable[ABRRendition],
        audio_stream_index: Optional[int] = None,
        subtitle_stream_index: Optional[int] = None,
        start_position: float = 0,
    ) -> ABRJob:
        if not shutil.which("ffmpeg"):
            raise ABRJobError("ffmpeg is not installed")
        variants = tuple(renditions)
        if len(variants) < 2:
            raise ABRJobError("Adaptive HLS requires at least two renditions")
        self.cleanup_cache()

        with self._lock:
            existing = self._jobs.get(session_id)
            if existing and existing.process and existing.process.poll() is None:
                return existing
            if existing and self._ready(existing):
                return existing

            directory = self.session_dir(session_id)
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
            directory.mkdir(parents=True, exist_ok=True)
            log_path = directory / "ffmpeg.log"

            allowed, reason, candidates = abr_available()
            if not allowed:
                raise ABRJobError(reason)
            if not candidates:
                raise ABRJobError("No H.264 encoder is available for adaptive playback")
            primary = candidates[0]
            fallback = candidates[1] if len(candidates) > 1 else None
            common = dict(
                source_path=source_path,
                output_dir=directory,
                renditions=variants,
                audio_stream_index=audio_stream_index,
                subtitle_stream_index=subtitle_stream_index,
                start_position=start_position,
            )
            cmd = build_abr_command(**common, video_encoder=primary)
            fallback_cmd = build_abr_command(**common, video_encoder=fallback) if fallback else None
            process = self._spawn(
                cmd,
                log_path,
                f"starting adaptive ladder with {primary}: {reason}",
            )
            job = ABRJob(
                session_id=session_id,
                source_path=source_path,
                directory=directory,
                process=process,
                log_path=log_path,
                renditions=variants,
                encoder=primary,
                fallback_encoder=fallback,
                fallback_cmd=fallback_cmd,
            )
            self._jobs[session_id] = job
            return job

    def _try_fallback(self, job: ABRJob) -> bool:
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
                f"adaptive hardware path failed; falling back to {job.fallback_encoder}",
            )
            job.encoder = job.fallback_encoder or job.encoder
            job.fallback_cmd = None
            return True

    def wait_until_ready(self, session_id: str, timeout: Optional[float] = None) -> Path:
        if timeout is None:
            try:
                timeout = float(os.environ.get("NOMAD_ABR_START_TIMEOUT", os.environ.get("NOMAD_HLS_START_TIMEOUT", "30")))
            except (TypeError, ValueError):
                timeout = 30.0
        timeout = max(0.1, float(timeout))
        deadline = time.monotonic() + timeout

        while True:
            while time.monotonic() < deadline:
                with self._lock:
                    job = self._jobs.get(session_id)
                if not job:
                    raise ABRJobError("Adaptive playback job not found")
                if self._ready(job):
                    return self.master_path(session_id)
                if job.process and job.process.poll() is not None:
                    if self._try_fallback(job):
                        deadline = time.monotonic() + timeout
                        break
                    raise ABRJobError(self.log_tail(session_id) or f"ffmpeg exited with code {job.process.returncode}")
                time.sleep(0.1)
            else:
                with self._lock:
                    job = self._jobs.get(session_id)
                if job and self._try_fallback(job):
                    deadline = time.monotonic() + timeout
                    continue
                raise ABRJobError(f"Timed out after {timeout:.1f}s waiting for adaptive HLS")
            continue

    def status(self, session_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(session_id)
        running = bool(job and job.process and job.process.poll() is None)
        return {
            "running": running,
            "master_ready": bool(job and self._ready(job)),
            "encoder": job.encoder if job else None,
            "hardware_accelerated": bool(job and is_hardware_encoder(job.encoder)),
            "fallback_attempted": bool(job and job.fallback_attempted),
            "renditions": [r.to_dict() for r in job.renditions] if job else [],
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

    def log_tail(self, session_id: str, max_bytes: int = 5000) -> str:
        path = self.session_dir(session_id) / "ffmpeg.log"
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - max_bytes))
                return handle.read().decode("utf-8", errors="replace").strip()
        except OSError:
            return ""
