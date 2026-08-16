"""Runtime fixes for low-memory remux/audio-HLS playback.

Radxa vendor images can ship an FFmpeg old enough to lack ``-readrate``.  The
previous compatibility fallback used ``-re`` which is exactly 1x media speed.
That is unsuitable for an on-demand HLS producer: the browser can catch the
producer after a tiny scheduling or I/O delay and repeatedly underrun.

For cheap remux/audio-only jobs we instead let legacy FFmpeg build ahead while
running it at reduced CPU/I/O priority.  The storage-pressure guard prevents
that producer from consuming the appliance filesystem.  We also wait for a
small complete-segment lead before exposing the playlist to the browser.
"""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import threading
import time
from typing import Optional

from app.services.playback import hls as hls_module
from app.services.playback.hls import HLSJobError, HLSManager
from app.services.playback.planner import PlaybackMode


_INSTALLED = False
_LOCK = threading.Lock()
_ORIGINAL_READRATE = hls_module.streaming_input_readrate
_ORIGINAL_BUILD = hls_module.build_hls_command
_ORIGINAL_SPAWN = HLSManager._spawn
_ORIGINAL_WAIT = HLSManager.wait_until_ready


def _cheap_mode(mode) -> bool:
    try:
        value = mode if isinstance(mode, PlaybackMode) else PlaybackMode(str(mode))
    except (TypeError, ValueError):
        return False
    return value in {PlaybackMode.REMUX, PlaybackMode.TRANSCODE_AUDIO}


def _legacy_ffmpeg_needs_ahead_mode(desired: Optional[float]) -> bool:
    return bool(
        desired
        and float(desired) > 1.0
        and not hls_module.ffmpeg_supports_readrate()
    )


def _effective_streaming_readrate(mode) -> Optional[float]:
    desired = _ORIGINAL_READRATE(mode)
    # Do not replace a requested 2x producer with -re/1x on legacy FFmpeg.
    # Returning None makes the cheap stream-copy job run ahead; _spawn() then
    # lowers its scheduler priority so serving completed segments wins I/O.
    if _legacy_ffmpeg_needs_ahead_mode(desired):
        return None
    return desired


def _stable_build_hls_command(**kwargs):
    cmd = list(_ORIGINAL_BUILD(**kwargs))
    if not _cheap_mode(kwargs.get("mode")):
        return cmd

    # Older demuxers occasionally expose awkward/missing presentation stamps
    # when copying MKV/MP4 streams into fragmented HLS. +genpts is a no-op when
    # valid PTS already exist and gives the muxer monotonic presentation timing
    # when they do not.
    try:
        input_pos = cmd.index("-i")
    except ValueError:
        return cmd
    if "-fflags" not in cmd[:input_pos]:
        cmd[input_pos:input_pos] = ["-fflags", "+genpts"]

    # Defensive cleanup for callers that explicitly constructed a legacy
    # read-rate command before this runtime overlay was installed.  A 1x -re
    # producer is the exact underrun condition this module exists to avoid.
    if "-re" in cmd[:cmd.index("-i")]:
        cmd.remove("-re")
    return cmd


def _low_priority_command(cmd: list[str]) -> list[str]:
    """Best-effort scheduler wrapper for an ahead-of-realtime remux producer."""
    wrapped: list[str] = []
    ionice = shutil.which("ionice")
    nice = shutil.which("nice")
    if ionice:
        # Best-effort class, lowest priority inside the class.  Segment serving
        # and the web UI therefore win when they need the same storage device.
        wrapped += [ionice, "-c", "2", "-n", "7"]
    if nice:
        wrapped += [nice, "-n", "5"]
    wrapped += list(cmd)
    return wrapped


def _stable_spawn(cmd: list[str], log_path: Path, note: Optional[str] = None):
    cheap = bool(note and "HLS stream-copy job" in note)
    actual = _low_priority_command(cmd) if cheap else cmd
    if cheap and actual != cmd:
        note = f"{note}; ahead-of-realtime legacy remux at low scheduler priority"
    return _ORIGINAL_SPAWN(actual, log_path, note=note)


def _segment_count(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return sum(
        1
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _prebuffer_target() -> int:
    raw = str(os.environ.get("NOMAD_HLS_PREBUFFER_SEGMENTS", "3")).strip()
    try:
        return max(1, min(8, int(raw)))
    except (TypeError, ValueError):
        return 3


def _stable_wait_until_ready(self: HLSManager, session_id: str, timeout: Optional[float] = None) -> Path:
    playlist = _ORIGINAL_WAIT(self, session_id, timeout=timeout)

    with self._lock:
        job = self._jobs.get(session_id)
    # encoder=None is the existing marker for the cheap remux/audio-copy path.
    # Do not delay actual video encoders, where every extra segment costs real
    # startup latency and may be slower than realtime on software fallback.
    if not job or job.encoder is not None:
        return playlist

    target = _prebuffer_target()
    if target <= 1:
        return playlist

    try:
        extra_timeout = float(os.environ.get("NOMAD_HLS_PREBUFFER_TIMEOUT", "12"))
    except (TypeError, ValueError):
        extra_timeout = 12.0
    deadline = time.monotonic() + max(1.0, min(30.0, extra_timeout))

    while time.monotonic() < deadline:
        if _segment_count(playlist) >= target:
            return playlist
        try:
            complete = "#EXT-X-ENDLIST" in playlist.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            complete = False
        if complete:
            return playlist
        if job.process and job.process.poll() is not None:
            if job.process.returncode == 0 and playlist.exists():
                return playlist
            message = self.log_tail(session_id)
            raise HLSJobError(message or f"HLS backend exited with code {job.process.returncode}")
        time.sleep(0.1)

    # A lead buffer is a smoothness optimisation, not a reason to make an
    # otherwise valid stream fail startup.  Return whatever FFmpeg has produced
    # after the bounded wait and let the browser continue filling its buffer.
    return playlist


def install_remux_stability() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    with _LOCK:
        if _INSTALLED:
            return
        hls_module.streaming_input_readrate = _effective_streaming_readrate
        hls_module.build_hls_command = _stable_build_hls_command
        HLSManager._spawn = staticmethod(_stable_spawn)
        HLSManager.wait_until_ready = _stable_wait_until_ready
        HLSManager._nomad_remux_stability_installed = True
        _INSTALLED = True
