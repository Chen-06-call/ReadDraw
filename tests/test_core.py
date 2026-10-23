"""Fast, dependency-light checks for the first release's core services."""

import asyncio
import tempfile
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import flet as ft
from PIL import Image

from readdraw.drawing import (
    compose_page, mouse_speed_pressure, point_near_stroke, pressure_width,
    shape_points,
)
from readdraw.pdf import open_pdf, render_page
from readdraw.epub import EpubDocument
from readdraw.storage import Store
from readdraw.models import Attachment
from readdraw.sync_server import create_app
from readdraw.updater import parse_release, version_tuple
from readdraw.canvas_view import PageTransform
from readdraw.canvas_view import ReadingCanvas
from readdraw.attachment_tools import scaled_image_size
from readdraw import config
from readdraw.data_location import migrate_data_dir


class CoreServiceTests(unittest.TestCase):
    def test_shape_points_cover_common_geometry(self) -> None:
        start, end = (10.0, 20.0), (110.0, 80.0)
        self.assertEqual(shape_points("line", start, end), [[10.0, 20.0], [110.0, 80.0]])
        for shape in ("rectangle", "triangle", "diamond"):
            points = shape_points(shape, start, end)
            self.assertEqual(points[0], points[-1])
        self.assertEqual(len(shape_points("circle", start, end)), 49)
        self.assertEqual(len(shape_points("wave", start, end)), 49)
        arrow = shape_points("arrow", start, end)
        self.assertEqual(arrow[1], arrow[3])

    def test_circle_and_square_keep_equal_dimensions_in_every_drag_direction(self) -> None:
        for start, end in (((10, 20), (70, 80)), ((70, 80), (10, 20)),
                           ((70, 20), (10, 80)), ((10, 80), (70, 20))):
            circle = shape_points("circle", start, end)
            square = shape_points("square", start, end)
            circle_width = max(point[0] for point in circle) - min(point[0] for point in circle)
            circle_height = max(point[1] for point in circle) - min(point[1] for point in circle)
            square_width = max(point[0] for point in square) - min(point[0] for point in square)
            square_height = max(point[1] for point in square) - min(point[1] for point in square)
            self.assertAlmostEqual(circle_width, circle_height, places=6)
            self.assertAlmostEqual(square_width, square_height, places=6)

    def test_shape_geometry_remains_anchored_to_original_pointer(self) -> None:
        start = (80.0, 90.0)
        first_preview = shape_points("triangle", start, (150.0, 140.0))
        second_preview = shape_points("triangle", start, (210.0, 180.0))
        self.assertEqual(min(point[0] for point in first_preview), start[0])
        self.assertEqual(min(point[0] for point in second_preview), start[0])
        self.assertEqual(min(point[1] for point in first_preview), start[1])
        self.assertEqual(min(point[1] for point in second_preview), start[1])

    def test_mouse_speed_maps_to_simulated_pressure(self) -> None:
        """鼠标移动越慢模拟压力越大，速度上限处压力归零。"""
        self.assertGreater(mouse_speed_pressure(200), mouse_speed_pressure(1200))
        self.assertEqual(mouse_speed_pressure(1800), 0.0)
        self.assertEqual(mouse_speed_pressure(-10), 1.0)

    def test_pressure_changes_pen_width_in_export_and_live_canvas(self) -> None:
        """压感笔迹在导出图和实时矢量层中都按压力改变粗细。"""
        stroke = {
            "tool": "pen", "color": "#E45756", "width": 8,
            "points": [[10, 25], [30, 25], [50, 25], [70, 25]],
            "pressures": [0.0, 0.0, 1.0, 1.0],
        }
        exported = compose_page(Image.new("RGB", (80, 50), "white"), [stroke])
        self.assertEqual(exported.getpixel((20, 20)), (255, 255, 255, 255))
        self.assertEqual(exported.getpixel((60, 20)), (228, 87, 86, 255))
        self.assertEqual(pressure_width(8, 0.65), 8.0)

        canvas = ReadingCanvas(lambda event: None, lambda event: None, lambda event: None)
        canvas.set_page(Image.new("RGB", (80, 50), "white"), [], [stroke])
        self.assertEqual(len(canvas.ink.shapes), 3)
        self.assertLess(canvas.ink.shapes[0].paint.stroke_width,
                        canvas.ink.shapes[-1].paint.stroke_width)

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
            store.update_attachment_size(attachment.id, 120, 60)
            updated = store.attachments(book.id, 2)[0]
            self.assertEqual((updated.width, updated.height), (120, 60))
            self.assertTrue(store.delete_attachment(attachment.id))
            self.assertFalse(Path(attachment.path).exists())
            self.assertEqual(store.attachments(book.id, 2), [])
            self.assertFalse(store.delete_attachment(attachment.id))
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
                    },
                    {
                        "name": "ReadDraw.exe",
                        "browser_download_url": "https://example.test/latest.exe",
                    },
                ],
            }
        )
        self.assertIsNotNone(release)
        self.assertEqual(release.asset_name, "ReadDraw.exe")
        self.assertEqual(release.asset_url, "https://example.test/latest.exe")
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

    def test_zoomed_page_pan_is_clamped_and_resettable(self) -> None:
        """放大页面只能在边界内拖动，重置后恢复居中。"""
        canvas = ReadingCanvas(lambda event: None, lambda event: None, lambda event: None,
                               can_pan_page=lambda: True)
        canvas.set_viewport(400, 400)
        canvas.set_page(Image.new("RGB", (400, 400), "white"), [], [])
        canvas.set_zoom(2.0)
        canvas._begin_page_pan(SimpleNamespace(global_position=SimpleNamespace(x=100.0, y=100.0)))
        asyncio.run(canvas._update_pointer(
            SimpleNamespace(global_position=SimpleNamespace(x=-1000.0, y=-1000.0))
        ))
        asyncio.run(canvas._end_pointer())
        self.assertLessEqual(canvas.transform.left + canvas.transform.width, canvas.viewport[0] + 0.001)
        self.assertLessEqual(canvas.transform.top + canvas.transform.height, canvas.viewport[1] + 0.001)
        self.assertTrue(canvas.reset_view())
        self.assertEqual(canvas.zoom, 1.0)
        self.assertEqual(canvas.pan_offset, (0.0, 0.0))

    def test_attachment_layer_moves_in_page_coordinates_and_zoom_relayouts(self) -> None:
        """连续、重复和反向移动均跟随全局鼠标位置，不能退回每帧的局部位移。"""
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
            for zoom in (0.5, 1.0, 2.0):
                with self.subTest(zoom=zoom):
                    canvas.set_zoom(zoom)
                    attachment.x, attachment.y = 24, 24
                    start = SimpleNamespace(global_position=SimpleNamespace(x=500, y=300))
                    canvas._begin_attachment_drag(attachment, start)
                    for dx, dy in ((6, 3), (12, 6), (60, 30), (60, 30), (50, 25), (-30, -30), (0, 0), (120, 80)):
                        # 局部位移故意保持很小，复现旧代码“只能挪一点”的事件序列。
                        event = SimpleNamespace(global_position=SimpleNamespace(x=500 + dx, y=300 + dy),
                                                local_delta=SimpleNamespace(x=6, y=3))
                        canvas._move_attachment(attachment, event)
                        x, y = max(0, 24 + dx / canvas.transform.scale), max(0, 24 + dy / canvas.transform.scale)
                        self.assertEqual((attachment.x, attachment.y), (round(x), round(y)))
                        position = canvas.attachment_controls[attachment.id]
                        self.assertAlmostEqual(position.left, canvas.transform.to_view(x, y)[0])
                        self.assertAlmostEqual(position.top, canvas.transform.to_view(x, y)[1])
                    canvas._end_attachment_drag(attachment)
            self.assertTrue(moved)
            previous_scale = canvas.transform.scale
            self.assertTrue(canvas.set_zoom(2.5))
            self.assertGreater(canvas.transform.scale, previous_scale)
            self.assertAlmostEqual(canvas.attachment_layer.controls[0].left, canvas.transform.to_view(attachment.x, attachment.y)[0])

    def test_attachment_corner_drag_resizes_and_delete_control_remains(self) -> None:
        """拖动图片右下角实时缩放，保持比例，并在松开后只保存一次。"""
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "inserted.png"
            Image.new("RGBA", (80, 40), "red").save(image_path)
            attachment = Attachment("image-1", "book-1", 0, str(image_path), "inserted.png", 24, 24, 200, 100, "now")
            resized = []
            deleted = []
            canvas = ReadingCanvas(
                lambda event: None, lambda event: None, lambda event: None,
                on_attachment_resize=lambda item: resized.append((item.width, item.height)),
                on_attachment_delete=lambda item: deleted.append(item.id),
            )
            canvas.set_page(Image.new("RGB", (600, 800), "white"), [attachment], [])
            canvas._select_attachment(attachment)
            self.assertEqual(canvas.selected_attachment_id, attachment.id)
            self.assertEqual(len(canvas.attachment_layer.controls), 2)
            handle = canvas.attachment_resize_handles[attachment.id]
            self.assertTrue(handle.visible)
            self.assertEqual(handle.mouse_cursor, ft.MouseCursor.RESIZE_DOWN_RIGHT)
            self.assertEqual(canvas.attachment_toolbars[attachment.id].width, 36)
            self.assertEqual(canvas.attachment_toolbars[attachment.id].content.tooltip, "删除图片")
            start = SimpleNamespace(global_position=SimpleNamespace(x=100.0, y=100.0))
            canvas._begin_attachment_resize(attachment, start)
            pointer = SimpleNamespace(global_position=SimpleNamespace(
                x=100.0 + 100 * canvas.transform.scale,
                y=100.0 + 50 * canvas.transform.scale,
            ))
            canvas._resize_attachment_from_drag(attachment, pointer)
            self.assertEqual((attachment.width, attachment.height), (300, 150))
            self.assertAlmostEqual(attachment.width / attachment.height, 2)
            self.assertEqual(resized, [])
            self.assertEqual(canvas.attachment_controls[attachment.id].width,
                             attachment.width * canvas.transform.scale)
            canvas._end_attachment_resize(attachment, pointer)
            self.assertEqual(resized, [(300, 150)])
            canvas._delete_attachment(attachment)
            self.assertEqual(deleted, [attachment.id])
            self.assertEqual(canvas.attachments, [])

    def test_attachment_size_keeps_ratio_and_page_bounds(self) -> None:
        self.assertEqual(scaled_image_size(400, 200, 1.1, (600, 800)), (440, 220))
        self.assertEqual(scaled_image_size(400, 200, 1.1, (420, 800)), (420, 210))
        self.assertEqual(scaled_image_size(400, 200, 0.01, (600, 800)), (20, 10))

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
