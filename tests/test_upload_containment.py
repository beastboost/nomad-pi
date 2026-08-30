"""Upload destinations must stay inside the media library.

``category`` arrives straight off a query string and used to be joined into a
filesystem path unchecked, so ``?category=../../..`` resolved outside data/ and
``mkdir(parents=True)`` then created whatever directory it named. These tests
pin the allow-list and the containment backstop that closed that.
"""

import io
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers import uploads


TRAVERSAL_CATEGORIES = [
    "../../..",
    "../..",
    "..",
    "/etc",
    "movies/../../..",
    "....//....//",
    "movies/..",
]


@pytest.mark.parametrize("category", TRAVERSAL_CATEGORIES)
def test_traversal_categories_are_rejected(category):
    with pytest.raises(HTTPException) as excinfo:
        uploads._validated_category(category)
    assert excinfo.value.status_code == 400


@pytest.mark.parametrize("category", uploads.UPLOAD_CATEGORIES)
def test_every_allowed_category_resolves_under_data(category):
    assert uploads._validated_category(category) == category
    destination = uploads._compute_destination(category, "Example File.txt")
    assert Path("data").resolve() in Path(destination).resolve().parents


def test_category_is_case_and_whitespace_insensitive():
    assert uploads._validated_category("  MOVIES ") == "movies"


def test_staging_directories_are_not_upload_targets():
    # data/uploads and data/ingest are internal staging areas, not library
    # categories a client may aim an upload at.
    for category in ("uploads", "ingest"):
        with pytest.raises(HTTPException):
            uploads._validated_category(category)


def test_contain_rejects_a_destination_outside_its_category():
    base = Path("data/files")
    with pytest.raises(HTTPException) as excinfo:
        uploads._contain(Path("data/files/../../etc/passwd"), base)
    assert excinfo.value.status_code == 400


def test_contain_accepts_a_nested_destination():
    base = Path("data/shows")
    contained = uploads._contain(Path("data/shows/Show/Season 01/ep.mkv"), base)
    assert base.resolve() in contained.parents


def test_filename_is_flattened_to_its_basename():
    destination = uploads._compute_destination("files", "../../escape.txt")
    assert Path(destination).name == "escape.txt"
    assert Path("data/files").resolve() == Path(destination).parent


def test_dead_upload_endpoints_are_gone():
    # download/delete/verify/info all looked under data/uploads/<file_id>/,
    # which no upload path ever writes to, so they were permanent 404s.
    routes = {getattr(r, "path", "") for r in uploads.router.routes}
    assert not [p for p in routes if "/download/" in p or "/verify/" in p or "/info/" in p]
    assert "/api/uploads/single" in routes
    assert "/api/uploads/progress/{file_id}" in routes


def test_upload_progress_model_is_constructible_without_a_percentage():
    # percentage was a required field, so building this model raised and every
    # single/multiple upload returned 500 before writing a byte.
    progress = uploads.UploadProgress(
        file_id="abc", filename="x.mkv", total_size=0, uploaded_size=0, status="uploading",
    )
    assert progress.percentage == 0


def test_upload_writes_the_file_it_reports(tmp_path, monkeypatch):
    # UploadFile.file.read() is synchronous; awaiting it raised TypeError on the
    # first chunk, so uploads 500'd even with a valid category.
    from fastapi.testclient import TestClient
    from app.main import app
    from app.routers import auth

    app.dependency_overrides[auth.get_current_user_id] = lambda: 1
    try:
        client = TestClient(app)
        payload = b"nomad-pi upload containment test"
        response = client.post(
            "/api/uploads/single?category=files",
            files={"file": ("containment-probe.txt", io.BytesIO(payload), "text/plain")},
        )
        assert response.status_code == 200, response.text
        written = Path(response.json()["path"])
        assert Path("data").resolve() in written.resolve().parents
        assert written.read_bytes() == payload
        written.unlink(missing_ok=True)
    finally:
        app.dependency_overrides.pop(auth.get_current_user_id, None)
