"""Exercise application callbacks with a Flet session and isolated local data.

The recording transport validates Python control updates without a native GUI.
It does not replace a visual check in the Windows client.
"""

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pymupdf
from PIL import Image
from flet.messaging.connection import Connection
from flet.messaging.session import Session
from flet.pubsub.pubsub_hub import PubSubHub

from main import ReadDrawApp
from readdraw import config


class RecordingConnection(Connection):
    def __init__(self) -> None:
        super().__init__()
        self.loop = asyncio.get_running_loop()
        self.pubsubhub = PubSubHub(self.loop)
        self.messages = []

    def send_message(self, message) -> None:
        self.messages.append(message)


class AppFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch.multiple(
            config,
            APP_DIR=self.root / "library",
            DB_PATH=self.root / "library" / "readdraw.sqlite3",
            ATTACHMENTS_DIR=self.root / "library" / "attachments",
            SETTINGS_PATH=self.root / "settings.json",
        ))
        self.connection = RecordingConnection()
        self.session = Session(self.connection)
        self.app = ReadDrawApp(self.session.page)
        self.session.get_page_patch()

    async def asyncTearDown(self) -> None:
        if self.app.document:
            self.app.document.close()
        self.app.store.close()
        self.session.close()
        await asyncio.sleep(0)

    def create_pdf(self) -> Path:
        path = self.root / "sample.pdf"
        with pymupdf.open() as document:
            document.new_page(width=300, height=400).insert_text((30, 50), "ReadDraw page")
            document.new_page(width=400, height=300).insert_text((30, 50), "Second page")
            document.save(path)
        return path

    async def test_open_pdf_keeps_page_visible_with_annotations_and_page_changes(self) -> None:
        with patch.object(self.app, "show_error") as error:
            self.app.import_book(str(self.create_pdf()))
            self.assertIsNotNone(self.app.book)
            self.app.store.add_text_annotation(self.app.book.id, 0, "note", "Example note")
            self.app.load_page()
            self.assertEqual(len(self.app.annotation_list.controls), 1)
            self.assertIs(self.app.canvas_host.content, self.app.drawing_view.control)
            with Image.open(io.BytesIO(self.app.drawing_view.image.src)) as rendered:
                self.assertGreater(rendered.height, rendered.width)
            self.app.go_page(1)
            with Image.open(io.BytesIO(self.app.drawing_view.image.src)) as rendered:
                self.assertGreater(rendered.width, rendered.height)
            self.assertEqual(self.app.store.books()[0].current_page, 1)
            error.assert_not_called()

    async def test_settings_migrate_open_library_and_preserve_background(self) -> None:
        self.app.import_book(str(self.create_pdf()))
        self.app.open_settings()
        self.assertTrue(self.app.apply_background("#FFFDF7"))
        destination = self.root / "relocated"
        with patch.object(self.app.directory_picker, "get_directory_path", new=AsyncMock(return_value=str(destination))):
            await self.app.choose_data_dir()
        self.assertEqual(self.app.store.database_path.parent, destination)
        self.assertEqual(self.app.settings_path_text.value, str(destination))
        self.assertEqual(self.app.data_path_text.value, str(destination))
        self.assertEqual(config.get_setting("background"), "#FFFDF7")
        self.assertIsNotNone(self.app.book)
        self.assertTrue(self.app.drawing_view.image.visible)

    async def test_invalid_file_reports_error_without_exiting(self) -> None:
        self.app.import_book(str(self.root / "missing.pdf"))
        self.assertIsNone(self.app.book)
        self.assertIn("无法打开书籍", self.app.status.value)
        self.assertEqual(self.app.page._dialogs.controls, [])
        self.assertGreater(len(self.connection.messages), 0)

    async def test_shutdown_tolerates_a_disconnected_window(self) -> None:
        with patch.object(self.app.page.window, "destroy", new=AsyncMock(side_effect=RuntimeError("Session closed"))):
            await self.app._close_window()
        self.assertTrue(self.app._closed)
        self.assertIsNone(self.app.document)

    async def test_marker_draw_save_reload_and_undo_without_a_dialog(self) -> None:
        """荧光笔只切换绘画工具，笔迹透明度随页码保存并可撤销。"""
        self.app.import_book(str(self.create_pdf()))
        # 模拟客户端消费页面补丁，完成新画布控件的挂载。
        self.session.get_page_patch()
        with patch.object(self.app.page, "show_dialog") as show_dialog:
            self.app.set_tool("marker")
            self.assertTrue(self.app.marker_btn.selected)
            self.assertFalse(self.app.pen_btn.selected)
            show_dialog.assert_not_called()

        transform = self.app.drawing_view.transform
        def pointer(x, y):
            return SimpleNamespace(local_x=transform.to_view(x, y)[0], local_y=transform.to_view(x, y)[1])

        await self.app.start_stroke(pointer(40, 50))
        await self.app.update_stroke(pointer(140, 50))
        await self.app.end_stroke(None)
        stroke = self.app.strokes[0].copy()
        self.assertEqual(stroke["tool"], "marker")
        self.assertEqual(stroke["color"], "#FFEB3B")
        self.assertEqual(stroke["width"], self.app.thickness * 4)
        self.assertAlmostEqual(stroke["opacity"], 0.32)
        self.app.undo()
        self.assertEqual(self.app.strokes, [])
        self.app.redo()
        self.assertEqual(self.app.strokes, [stroke])
        self.app.go_page(1)
        self.app.go_page(-1)
        self.assertEqual(self.app.strokes, [stroke])
        self.app.set_color("#12B76A")
        self.assertEqual(self.app.tool, "marker")
        self.assertEqual(self.app.marker_color, "#12B76A")

    async def test_legacy_highlight_remains_a_note_without_text_search(self) -> None:
        """旧文字高亮记录不丢失，但加载页面时不再进入原文查找流程。"""
        self.app.import_book(str(self.create_pdf()))
        self.app.store.add_text_annotation(self.app.book.id, 0, "highlight", "旧记录", "ReadDraw")
        with patch("main.render_page", return_value=Image.new("RGB", (100, 200), "white")) as render:
            self.app.load_page()
        render.assert_called_once_with(self.app.document, 0)
        self.assertEqual(len(self.app.text_annotations), 1)
        self.assertEqual(len(self.app.annotation_list.controls), 1)


if __name__ == "__main__":
    unittest.main()
