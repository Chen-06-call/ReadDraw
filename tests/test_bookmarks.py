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
                self.assertTrue(store.toggle_bookmark(first.id, 2))
                self.assertTrue(store.toggle_bookmark(second.id, 7))
                self.assertEqual(store.bookmark_pages(first.id), [2, 7])
                self.assertFalse(store.toggle_bookmark(first.id, 7))
                self.assertEqual(store.bookmark_pages(second.id), [7])
            finally:
                store.close()
            reopened = Store(path)
            try:
                self.assertEqual(reopened.bookmark_pages(first.id), [2])
                self.assertTrue(reopened.toggle_bookmark(first.id, 7))
                self.assertEqual(reopened.bookmark_pages(first.id), [2, 7])
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
            old_snapshot = source.export_snapshot()
            target.import_snapshot(old_snapshot)
            self.assertEqual(target.bookmark_pages(book.id), [1])
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
