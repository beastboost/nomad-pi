from app.services.reader_state import ReaderStateStore


def test_reading_progress_is_per_user_and_persistent(tmp_path):
    db = str(tmp_path / "reader.db")
    first = ReaderStateStore(db_path=db)
    saved = first.save_progress(
        user_id=1,
        path="/data/books/Test.cbz",
        position={"page": 12, "total_pages": 80},
        percent=15.0,
    )
    assert saved.position["page"] == 12

    second = ReaderStateStore(db_path=db)
    restored = second.get_progress(user_id=1, path="/data/books/Test.cbz")
    assert restored is not None
    assert restored.position == {"page": 12, "total_pages": 80}
    assert restored.percent == 15.0
    assert second.get_progress(user_id=2, path="/data/books/Test.cbz") is None


def test_progress_clamps_percent(tmp_path):
    store = ReaderStateStore(db_path=str(tmp_path / "reader.db"))
    high = store.save_progress(user_id=1, path="/a.pdf", position={"page": 1}, percent=500)
    low = store.save_progress(user_id=1, path="/b.pdf", position={"page": 1}, percent=-20)
    assert high.percent == 100
    assert low.percent == 0


def test_recent_reading_orders_by_latest_update(tmp_path):
    store = ReaderStateStore(db_path=str(tmp_path / "reader.db"))
    store.save_progress(user_id=1, path="/first.pdf", position={"page": 1}, percent=1)
    store.save_progress(user_id=1, path="/second.pdf", position={"page": 2}, percent=2)
    recent = store.recent(1)
    assert recent[0].path == "/second.pdf"
    assert {item.path for item in recent} == {"/first.pdf", "/second.pdf"}


def test_bookmarks_and_annotations_are_user_scoped(tmp_path):
    store = ReaderStateStore(db_path=str(tmp_path / "reader.db"))
    bookmark = store.add_mark(
        user_id=1,
        path="/book.epub",
        kind="bookmark",
        label="Chapter start",
        note="",
        position={"page": 10, "total_pages": 200},
    )
    note = store.add_mark(
        user_id=1,
        path="/book.epub",
        kind="annotation",
        label="Page 12",
        note="Important point",
        position={"page": 12, "total_pages": 200},
    )
    store.add_mark(
        user_id=2,
        path="/book.epub",
        kind="bookmark",
        label="Other user",
        note="",
        position={"page": 99},
    )

    all_marks = store.list_marks(user_id=1, path="/book.epub")
    assert {item.id for item in all_marks} == {bookmark.id, note.id}
    annotations = store.list_marks(user_id=1, path="/book.epub", kind="annotation")
    assert [item.note for item in annotations] == ["Important point"]
    assert store.delete_mark(user_id=2, mark_id=bookmark.id) is False
    assert store.delete_mark(user_id=1, mark_id=bookmark.id) is True
    assert [item.id for item in store.list_marks(user_id=1, path="/book.epub")] == [note.id]
