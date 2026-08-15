from pathlib import Path

from app.services import stream_keep_download as skd


class FakeResponse:
    def __init__(self, *, status_code, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []
        self.is_redirect = False
        self.is_permanent_redirect = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1024 * 1024):
        yield from self._chunks

    def close(self):
        return None


def _state(download_id, final_path):
    skd._states[download_id] = {
        "id": download_id,
        "status": "downloading",
        "dest_path": str(final_path),
        "progress": 0,
        "speed": 0,
        "size_total": 0,
        "size_downloaded": 0,
        "error": None,
    }
    skd._cancelled.discard(download_id)


def test_parse_content_range():
    assert skd._parse_content_range("bytes 5-9/10") == (5, 10)
    assert skd._parse_content_range("bytes */10") == (None, 10)
    assert skd._parse_content_range("") == (None, None)


def test_worker_resumes_existing_partial_with_if_range(tmp_path, monkeypatch):
    final = tmp_path / "movie.mp4"
    part = Path(str(final) + ".part")
    part.write_bytes(b"hello")
    skd._save_sidecar(str(final), etag='"abc"', last_modified="", total=10, url="https://cdn.example/movie")
    download_id = "resume-test"
    _state(download_id, final)

    seen = {}

    def fake_get(url, *, headers=None, **kwargs):
        seen.update(headers or {})
        return FakeResponse(
            status_code=206,
            headers={
                "Content-Range": "bytes 5-9/10",
                "Content-Length": "5",
                "ETag": '"abc"',
            },
            chunks=[b"world"],
        )

    monkeypatch.setattr(skd, "_safe_get", fake_get)
    monkeypatch.setattr(skd, "_index_completed", lambda path, category: "/data/movies/movie/movie.mp4")

    skd._worker(download_id, "https://cdn.example/movie", str(final), "movies")

    assert seen["Range"] == "bytes=5-"
    assert seen["If-Range"] == '"abc"'
    assert final.read_bytes() == b"helloworld"
    status = skd.get_status(download_id)
    assert status["status"] == "completed"
    assert status["size_downloaded"] == 10
    assert status["local_path"].startswith("/data/")
    assert not part.exists()


def test_worker_truncates_partial_when_server_ignores_range(tmp_path, monkeypatch):
    final = tmp_path / "movie.mp4"
    part = Path(str(final) + ".part")
    part.write_bytes(b"stale")
    skd._save_sidecar(str(final), etag='"old"', last_modified="", total=5, url="https://cdn.example/movie")
    download_id = "restart-test"
    _state(download_id, final)

    def fake_get(url, *, headers=None, **kwargs):
        assert headers.get("Range") == "bytes=5-"
        assert headers.get("If-Range") == '"old"'
        return FakeResponse(
            status_code=200,
            headers={"Content-Length": "8", "ETag": '"new"'},
            chunks=[b"new-data"],
        )

    monkeypatch.setattr(skd, "_safe_get", fake_get)
    monkeypatch.setattr(skd, "_index_completed", lambda path, category: "/data/movies/movie/movie.mp4")

    skd._worker(download_id, "https://cdn.example/movie", str(final), "movies")

    assert final.read_bytes() == b"new-data"
    assert skd.get_status(download_id)["status"] == "completed"


def test_cancel_keeps_partial_for_later_resume(tmp_path):
    final = tmp_path / "movie.mp4"
    part = Path(str(final) + ".part")
    part.write_bytes(b"partial")
    download_id = "cancel-test"
    _state(download_id, final)

    assert skd.cancel(download_id) is True
    assert skd.get_status(download_id)["status"] == "cancelled"
    assert part.read_bytes() == b"partial"
