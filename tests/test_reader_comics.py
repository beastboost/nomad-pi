import zipfile
from pathlib import Path

from app.routers import media


def test_cbz_reader_extracts_images_naturally_and_blocks_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "BASE_DIR", str(tmp_path))
    books = tmp_path / "books"
    books.mkdir()
    comic = books / "Example Comic.cbz"

    with zipfile.ZipFile(comic, "w") as archive:
        archive.writestr("pages/10.jpg", b"ten")
        archive.writestr("pages/2.jpg", b"two")
        archive.writestr("pages/1.jpg", b"one")
        archive.writestr("notes/readme.txt", b"ignore")
        archive.writestr("../escape.jpg", b"must-not-escape")

    # Metadata is optional for comic rendering. Keep this test isolated from the
    # application database and exercise only archive extraction/page delivery.
    monkeypatch.setattr(media.database, "get_db", lambda: (_ for _ in ()).throw(RuntimeError("no db")))

    result = media.comic_pages("/data/books/Example Comic.cbz", user_id=1)
    assert result["total"] == 3
    assert [item["name"] for item in result["pages"]] == ["1.jpg", "2.jpg", "10.jpg"]
    assert result["cover"].endswith("/1.jpg")
    assert not (tmp_path / "escape.jpg").exists()

    for page in result["pages"]:
        assert page["path"].startswith("/data/.cache/comics/")
        fs_path = media.safe_fs_path_from_web_path(page["path"])
        assert Path(fs_path).is_file()
