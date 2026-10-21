"""Fast, dependency-light checks for the first release's core services."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from readdraw.drawing import compose_page, point_near_stroke
from readdraw.pdf import open_pdf, render_page
from readdraw.epub import EpubDocument
from readdraw.storage import Store
from readdraw.sync_server import create_app
from readdraw.updater import parse_release, version_tuple
from readdraw.window_drop import DROP_PORT, NativeDropBridge


class CoreServiceTests(unittest.TestCase):
    def test_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "test.sqlite3")
            book = store.add_book("示例", "example.pdf", 3)
            store.update_page(book.id, 2)
            strokes = [{"color": "#E45756", "width": 4, "points": [[1, 2], [3, 4]]}]
            store.save_strokes(book.id, 2, strokes)
            self.assertEqual(store.books()[0].current_page, 2)
            self.assertEqual(store.get_strokes(book.id, 2), strokes)
            annotation = store.add_text_annotation(book.id, 2, "highlight", "重点", "ReadDraw")
            self.assertEqual(store.text_annotations(book.id, 2)[0].id, annotation.id)
            image_path = Path(directory) / "attachment.png"
            Image.new("RGBA", (20, 20), "red").save(image_path)
            attachment = store.add_attachment(book.id, 2, str(image_path))
            self.assertTrue(Path(attachment.path).exists())
            store.close()

    def test_pdf_render_and_drawing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "sample.pdf"
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz
            document = fitz.open()
            page = document.new_page(width=200, height=200)
            page.insert_text((20, 40), "ReadDraw")
            document.save(pdf_path)
            reopened = open_pdf(str(pdf_path))
            rendered = render_page(reopened, 0)
            composed = compose_page(rendered, [{"color": "#E45756", "width": 6, "points": [[10, 10], [40, 40]]}])
            self.assertGreater(rendered.width, 0)
            self.assertEqual(composed.mode, "RGBA")
            self.assertTrue(point_near_stroke({"points": [[10, 10]]}, 12, 12))
            reopened.close()

    def test_epub_reader_and_sync_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            from ebooklib import epub

            epub_path = Path(directory) / "sample.epub"
            book = epub.EpubBook()
            book.set_identifier("read-draw-test")
            book.set_title("测试书")
            book.set_language("zh")
            chapter = epub.EpubHtml(title="第一章", file_name="chapter.xhtml", lang="zh")
            chapter.content = "<html><body><h1>第一章</h1><p>这是用于 ReadDraw 测试的文本。</p></body></html>"
            book.add_item(chapter)
            book.toc = (epub.Link("chapter.xhtml", "第一章", "chapter"),)
            book.spine = ["nav", chapter]
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            epub.write_epub(epub_path, book)
            document = EpubDocument(str(epub_path))
            rendered = document.render_page(0, ["ReadDraw"])
            self.assertGreaterEqual(document.page_count, 1)
            self.assertGreater(rendered.width, 0)
            self.assertIn("/health", [route.path for route in create_app(":memory:").routes])

    def test_update_release_parsing(self) -> None:
        self.assertEqual(version_tuple("v1.2.3"), (1, 2, 3))
        self.assertIsNone(parse_release({"tag_name": "v0.0.0", "assets": []}))
        release = parse_release(
            {
                "tag_name": "v0.0.1",
                "name": "First update",
                "body": "修复问题",
                "assets": [
                    {
                        "name": "ReadDraw-Setup-v0.0.1.exe",
                        "browser_download_url": "https://example.test/ReadDraw-Setup.exe",
                    },
                    {
                        "name": "ReadDraw-v0.0.1-windows-x64.exe",
                        "browser_download_url": "https://example.test/ReadDraw.exe",
                    }
                ],
            }
        )
        self.assertIsNotNone(release)
        self.assertEqual(release.asset_name, "ReadDraw-v0.0.1-windows-x64.exe")
        self.assertEqual(release.version, "0.0.1")

    def test_windows_drop_contract(self) -> None:
        self.assertEqual(DROP_PORT, 47831)
        self.assertTrue(callable(NativeDropBridge.start))


if __name__ == "__main__":
    unittest.main()
