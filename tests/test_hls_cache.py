import os
import time
from pathlib import Path

from app.services.playback.hls import HLSJob, HLSManager


class _RunningProcess:
    returncode = None

    def poll(self):
        return None


def _age(path: Path, seconds: float):
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def test_hls_cache_cleanup_removes_only_stale_inactive_directories(tmp_path):
    manager = HLSManager(root=str(tmp_path / "hls"))

    stale = manager.session_dir("stale")
    stale.mkdir()
    stale_segment = stale / "segment_00000.m4s"
    stale_segment.write_bytes(b"stale")
    _age(stale_segment, 1000)
    _age(stale, 1000)

    fresh = manager.session_dir("fresh")
    fresh.mkdir()
    fresh_segment = fresh / "segment_00000.m4s"
    fresh_segment.write_bytes(b"fresh")

    active = manager.session_dir("active")
    active.mkdir()
    active_segment = active / "segment_00000.m4s"
    active_segment.write_bytes(b"active")
    _age(active_segment, 1000)
    _age(active, 1000)
    manager._jobs["active"] = HLSJob(
        session_id="active",
        source_path="movie.mkv",
        directory=active,
        process=_RunningProcess(),
        log_path=active / "ffmpeg.log",
    )

    removed = manager.cleanup_cache(ttl_seconds=300)

    assert removed == 1
    assert not stale.exists()
    assert fresh.exists()
    assert active.exists()
