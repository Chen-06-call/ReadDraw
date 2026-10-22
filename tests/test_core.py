"""Fast, dependency-light checks for the first release's core services."""

import tempfile
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from readdraw.drawing import compose_page, point_near_stroke
from readdraw.pdf import open_pdf, render_page
from readdraw.epub import EpubDocument
from readdraw.storage import Store
from readdraw.models import Attachment
from readdraw.sync_server import create_app
from readdraw.updater import parse_release, version_tuple
from readdraw.canvas_view import PageTransform
from readdraw.canvas_view import ReadingCanvas
from readdraw import config
from readdraw.data_location import migrate_data_dir


class CoreServiceTests(unittest.TestCase):
    def test_marker_export_blends_color_without_hiding_text(self) -> None:
        """半透明荧光笔必须和白纸、黑字混合，导出的纸面仍不透明。"""
        base = Image.new("RGB", (100, 40), "white")
        base.putpixel((50, 20), (0, 0, 0))
        marker = {"color": "#FFEB3B", "opacity": 0.32, "width": 16, "points": [[10, 20], [90, 20]]}
        exported = compose_page(base, [marker])
        self.assertEqual(exported.getpixel((20, 20)), (255, 249, 192, 255))
        self.assertEqual(exported.getpixel((50, 20)), (82, 76, 19, 255))
        self.assertEqual(exported.getpixel((20, 2)), (255, 255, 255, 255))
        # 旧笔迹没有透明度字段时仍按实色画笔导出。
        pen = dict(marker, color="#E45756")
        pen.pop("opacity")
        self.assertEqual(compose_page(base, [pen]).getpixel((20, 20)), (228, 87, 86, 255))

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
            store.update_attachment_position(attachment.id, 80, 90)
            updated = store.attachments(book.id, 2)[0]
            self.assertEqual((updated.x, updated.y), (80, 90))
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

    @patch("readdraw.updater.APP_VERSION", "0.0.2")
    def test_update_release_parsing(self) -> None:
        # 固定旧版本基线，避免每次发布都要修改这组升级协议样例。
        self.assertEqual(version_tuple("v1.2.3"), (1, 2, 3))
        self.assertIsNone(parse_release({"tag_name": "v0.0.0", "assets": []}))
        release = parse_release(
            {
                "tag_name": "v0.0.3",
                "name": "First update",
                "body": "修复问题",
                "assets": [
                    {
                        "name": "ReadDraw-Setup-v0.0.3.exe",
                        "browser_download_url": "https://example.test/ReadDraw-Setup.exe",
                    },
                    {
                        "name": "ReadDraw-v0.0.3-windows-x64.exe",
                        "browser_download_url": "https://example.test/ReadDraw.exe",
                    }
                ],
            }
        )
        self.assertIsNotNone(release)
        self.assertEqual(release.asset_name, "ReadDraw-v0.0.3-windows-x64.exe")
        self.assertEqual(release.version, "0.0.3")

    def test_canvas_transform_round_trip(self) -> None:
        transform = PageTransform.fit(1000, 2000, 600, 600)
        view_point = transform.to_view(500, 1000)
        page_point = transform.to_page(*view_point)
        self.assertAlmostEqual(page_point[0], 500, places=5)
        self.assertAlmostEqual(page_point[1], 1000, places=5)

    def test_reading_canvas_keeps_page_and_gesture_layers(self) -> None:
        canvas = ReadingCanvas(lambda event: None, lambda event: None, lambda event: None)
        canvas.set_page(Image.new("RGB", (100, 200), "white"), [], [])
        self.assertTrue(canvas.image.visible)
        # Decode the actual payload sent to the Flet client, not just the render.
        with Image.open(io.BytesIO(canvas.image.src)) as decoded:
            self.assertEqual(decoded.size, (100, 200))
            self.assertEqual(decoded.getpixel((50, 100)), (255, 255, 255, 255))
        frame = canvas.page_frame
        self.assertGreater(frame.width, 0)
        self.assertLessEqual(frame.left + frame.width, canvas.viewport[0])
        self.assertLessEqual(frame.top + frame.height, canvas.viewport[1])
        # A landscape page must refit rather than reuse portrait bounds.
        canvas.set_page(Image.new("RGB", (400, 100), "blue"), [], [])
        self.assertAlmostEqual(frame.width / frame.height, 4)
        with Image.open(io.BytesIO(canvas.image.src)) as decoded:
            self.assertEqual(decoded.getpixel((50, 50)), (0, 0, 255, 255))

    def test_attachment_layer_moves_in_page_coordinates_and_zoom_relayouts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "inserted.png"
            Image.new("RGBA", (80, 40), "red").save(image_path)
            attachment = Attachment("image-1", "book-1", 0, str(image_path), "inserted.png", 24, 24, 240, 180, "now")
            moved = []
            canvas = ReadingCanvas(lambda event: None, lambda event: None, lambda event: None,
                                   on_attachment_move=lambda item: moved.append((item.x, item.y)),
                                   can_drag_attachments=lambda: True)
            canvas.set_page(Image.new("RGB", (600, 800), "white"), [attachment], [])
            self.assertEqual(len(canvas.attachment_layer.controls), 1)
            canvas._begin_attachment_drag(attachment)
            delta = type("Delta", (), {"x": 60, "y": 30})()
            canvas._move_attachment(attachment, type("Event", (), {"local_delta": delta})())
            self.assertEqual((attachment.x, attachment.y), (24 + round(60 / canvas.transform.scale), 24 + round(30 / canvas.transform.scale)))
            self.assertTrue(moved)
            previous_scale = canvas.transform.scale
            self.assertTrue(canvas.set_zoom(1.5))
            self.assertGreater(canvas.transform.scale, previous_scale)
            self.assertAlmostEqual(canvas.attachment_layer.controls[0].left, canvas.transform.to_view(attachment.x, attachment.y)[0])

    def test_settings_merge_preserves_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = config.SETTINGS_PATH
            try:
                config.SETTINGS_PATH = Path(directory) / "settings.json"
                config.save_settings(data_dir="D:/ReadDrawData")
                config.save_settings(background="#FFFDF7")
                self.assertEqual(config.load_settings(), {"data_dir": "D:/ReadDrawData", "background": "#FFFDF7"})
            finally:
                config.SETTINGS_PATH = original

    def test_data_migration_keeps_background_and_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(config, "SETTINGS_PATH", root / "settings.json"),
                patch.object(config, "APP_DIR", root / "source"),
                patch.object(config, "DB_PATH", root / "source" / "readdraw.sqlite3"),
                patch.object(config, "ATTACHMENTS_DIR", root / "source" / "attachments"),
            ):
                config.save_settings(background="#EEF4FF")
                source = Store(config.DB_PATH)
                try:
                    book = source.add_book("Book", str(root / "external.pdf"), 3)
                    source.update_page(book.id, 2)
                    image = root / "image.png"
                    Image.new("RGB", (10, 10), "red").save(image)
                    attachment = source.add_attachment(book.id, 2, str(image))
                    destination = migrate_data_dir(source, root / "target")
                    target = Store(destination / "readdraw.sqlite3")
                    try:
                        self.assertEqual(target.books()[0].current_page, 2)
                        copied_path = Path(target.attachments(book.id, 2)[0].path)
                        self.assertTrue(copied_path.is_relative_to(destination))
                        self.assertEqual(copied_path.read_bytes(), Path(attachment.path).read_bytes())
                        self.assertEqual(config.get_setting("background"), "#EEF4FF")
                        self.assertEqual(config._configured_app_dir(), destination)
                    finally:
                        target.close()
                    # Attempting to overwrite an existing library must fail.
                    with self.assertRaises(ValueError):
                        migrate_data_dir(source, destination)
                    self.assertEqual(source.books()[0].current_page, 2)
                finally:
                    source.close()


if __name__ == "__main__":
    unittest.main()
