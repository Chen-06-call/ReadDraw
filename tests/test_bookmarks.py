"""验证书签持久化、按书籍隔离和同步删除行为。"""

import tempfile
import unittest
from pathlib import Path

from readdraw.storage import Store


class BookmarkStorageTests(unittest.TestCase):
    def test_toggle_persists_and_books_remain_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library.sqlite3"
            store = Store(path)
            try:
                first = store.add_book("第一本", "first.pdf", 10)
                second = store.add_book("第二本", "second.epub", 10, "epub")
                self.assertTrue(store.toggle_bookmark(first.id, 7))
                store.save_bookmark(first.id, 7, "重读重点")
                self.assertTrue(store.toggle_bookmark(first.id, 2))
                self.assertTrue(store.toggle_bookmark(second.id, 7))
                self.assertEqual(store.bookmark_pages(first.id), [2, 7])
                self.assertEqual(store.bookmarks(first.id)[1]["note"], "重读重点")
                self.assertFalse(store.toggle_bookmark(first.id, 7))
                self.assertEqual(store.bookmark_pages(second.id), [7])
            finally:
                store.close()
            reopened = Store(path)
            try:
                self.assertEqual(reopened.bookmark_pages(first.id), [2])
                self.assertTrue(reopened.toggle_bookmark(first.id, 7))
                self.assertEqual(reopened.bookmark_pages(first.id), [2, 7])
                self.assertEqual(reopened.bookmarks(first.id)[1]["note"], "")
            finally:
                reopened.close()

    def test_invalid_page_or_missing_book_cannot_create_bookmark(self) -> None:
        store = Store(":memory:")
        try:
            book = store.add_book("示例", "book.pdf", 2)
            for book_id, page in ((book.id, -1), (book.id, 2), ("missing", 0)):
                with self.subTest(book_id=book_id, page=page), self.assertRaises(ValueError):
                    store.toggle_bookmark(book_id, page)
            self.assertEqual(store.bookmark_pages(book.id), [])
        finally:
            store.close()

    def test_sync_deletion_survives_reimporting_old_snapshot(self) -> None:
        source, target = Store(":memory:"), Store(":memory:")
        try:
            book = source.add_book("示例", "book.pdf", 3)
            source.toggle_bookmark(book.id, 1)
            source.save_bookmark(book.id, 1, "同步备注")
            old_snapshot = source.export_snapshot()
            target.import_snapshot(old_snapshot)
            self.assertEqual(target.bookmark_pages(book.id), [1])
            self.assertEqual(target.bookmarks(book.id)[0]["note"], "同步备注")
            source.toggle_bookmark(book.id, 1)
            target.import_snapshot(source.export_snapshot())
            self.assertEqual(target.bookmark_pages(book.id), [])
            target.import_snapshot(old_snapshot)
            self.assertEqual(target.bookmark_pages(book.id), [])
            # 旧客户端没有书签字段的快照也应能导入，并保留本地书签状态。
            target.import_snapshot({"books": old_snapshot["books"]})
            self.assertEqual(target.bookmark_pages(book.id), [])
        finally:
            source.close()
            target.close()

    def test_legacy_bookmark_table_and_sync_snapshot_migrate_without_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            import sqlite3
            connection = sqlite3.connect(path)
            connection.execute("""CREATE TABLE books (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
                pages INTEGER NOT NULL, current_page INTEGER NOT NULL DEFAULT 0,
                added_at TEXT NOT NULL, format TEXT NOT NULL DEFAULT 'pdf')""")
            connection.execute("""CREATE TABLE bookmarks (
                book_id TEXT NOT NULL, page INTEGER NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
                PRIMARY KEY(book_id,page))""")
            connection.execute("INSERT INTO books VALUES('book','舊書','old.pdf',2,0,'now','pdf')")
            connection.execute("INSERT INTO bookmarks VALUES('book',1,0,'2026-01-01T00:00:00+00:00')")
            connection.commit()
            connection.close()

            store = Store(path)
            try:
                self.assertEqual(store.bookmarks("book"), [{"page": 1, "note": ""}])
                legacy_snapshot = {
                    "books": [{"id": "book", "title": "旧书", "path": "old.pdf",
                               "pages": 2, "current_page": 0, "added_at": "now", "format": "pdf"}],
                    "bookmarks": [{"book_id": "book", "page": 0, "deleted": 0,
                                   "updated_at": "2026-01-02T00:00:00+00:00"}],
                }
                store.import_snapshot(legacy_snapshot)
                self.assertEqual(store.bookmarks("book"), [
                    {"page": 0, "note": ""}, {"page": 1, "note": ""}
                ])
            finally:
                store.close()
