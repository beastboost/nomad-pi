from pathlib import Path

from app.services import debrid
from app.services import download_queue_runtime as runtime


def test_cancel_marks_job_and_clear_removes_all_terminal_states(monkeypatch):
    with debrid._downloads_lock:
        original = dict(debrid._downloads)
        debrid._downloads.clear()
        debrid._downloads.update({
            "active": {"id": "active", "status": "downloading", "speed": 123},
            "done": {"id": "done", "status": "completed"},
            "failed": {"id": "failed", "status": "failed"},
            "error": {"id": "error", "status": "error"},
        })
    try:
        assert runtime._cancel_download("active") is True
        with debrid._downloads_lock:
            assert debrid._downloads["active"]["status"] == "cancelled"
            assert debrid._downloads["active"]["speed"] == 0
        assert runtime._clear_completed() == 4
        assert debrid.get_all_downloads() == []
    finally:
        with debrid._downloads_lock:
            debrid._downloads.clear()
            debrid._downloads.update(original)


def test_removed_queue_entry_is_treated_as_cancelled():
    with debrid._downloads_lock:
        original = dict(debrid._downloads)
        debrid._downloads.clear()
    try:
        assert runtime._cancelled("missing") is True
    finally:
        with debrid._downloads_lock:
            debrid._downloads.clear()
            debrid._downloads.update(original)


def test_cancelled_partial_file_is_removed(tmp_path):
    partial = Path(tmp_path) / "partial.mp4"
    partial.write_bytes(b"partial")
    runtime._remove_partial(str(partial))
    assert not partial.exists()
