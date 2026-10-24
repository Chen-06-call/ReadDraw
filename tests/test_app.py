"""Exercise application callbacks with a Flet session and isolated local data.

The recording transport validates Python control updates without a native GUI.
It does not replace a visual check in the Windows client.
"""

import asyncio
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pymupdf
import flet as ft
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
        # 单元测试不读取测试电脑的实体键盘，界面集成时才使用系统即时状态。
        self.enterContext(patch("main.is_alt_pressed", side_effect=lambda fallback: fallback))
        self.app = ReadDrawApp(self.session.page)
        self.session.get_page_patch()

    async def test_desktop_root_fills_window_without_keyboard_wrapper(self) -> None:
        """根布局直接填满窗口，不经过额外的键盘监听包装。"""
        root = self.session.page.controls[0]
        self.assertIsInstance(root, ft.Column)
        self.assertTrue(root.expand)
        self.assertEqual(self.session.page.window.width, 1280)
        self.assertEqual(self.session.page.window.height, 800)
        self.assertTrue(self.session.page.window.maximized)

    async def test_reading_and_drawing_workspaces_keep_reader_state(self) -> None:
        """绘画入口显示独立画板，返回阅读时仍保留书籍与翻页状态。"""
        self.assertEqual(self.app.workspace, "reading")
        self.assertIs(self.app.workspace_switcher.content, self.app.reader_workspace)
        self.assertEqual(len(self.app.drawing_workspace.controls), 2)
        self.assertIs(self.app.drawing_workspace.controls[1].content, self.app.free_board.control)
        self.app.import_book(str(self.create_pdf()))
        self.app.go_page(1)
        self.assertEqual(self.app.page_index, 1)
        self.assertIsNotNone(self.app.canvas_host.animate_offset)

        self.app.drawing_nav.on_click(None)
        self.assertEqual(self.app.workspace, "drawing")
        self.assertIs(self.app.workspace_switcher.content, self.app.drawing_workspace)
        self.assertFalse(self.app.reading_actions.visible)
        self.app.reading_nav.on_click(None)
        self.assertEqual(self.app.workspace, "reading")
        self.assertIs(self.app.workspace_switcher.content, self.app.reader_workspace)
        self.assertTrue(self.app.reading_actions.visible)
        self.assertEqual(self.app.page_index, 1)
        self.assertIsNotNone(self.app.book)

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
            self.assertIs(self.app.canvas_host.content, self.app.reader_scroll_detector)
            self.assertIs(self.app.reader_scroll_detector.content, self.app.drawing_view.control)
            with Image.open(io.BytesIO(self.app.drawing_view.image.src)) as rendered:
                self.assertGreater(rendered.height, rendered.width)
            self.app.go_page(1)
            with Image.open(io.BytesIO(self.app.drawing_view.image.src)) as rendered:
                self.assertGreater(rendered.width, rendered.height)
            self.assertEqual(self.app.store.books()[0].current_page, 1)
            error.assert_not_called()

    async def test_first_and_last_page_buttons_jump_to_document_boundaries(self) -> None:
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()

        self.app.go_to_last_page()
        self.assertEqual(self.app.page_index, 1)
        self.assertEqual(self.app.store.books()[0].current_page, 1)
        self.assertTrue(self.app.last_btn.disabled)
        self.assertFalse(self.app.first_btn.disabled)

        self.app.go_to_first_page()
        self.assertEqual(self.app.page_index, 0)
        self.assertEqual(self.app.store.books()[0].current_page, 0)
        self.assertTrue(self.app.first_btn.disabled)
        self.assertFalse(self.app.last_btn.disabled)

    async def test_bookmark_button_and_directory_navigate_without_losing_ink(self) -> None:
        """点击真实书签控件，验证图标切换、目录跳页及未完成笔迹保存。"""
        self.assertTrue(self.app.bookmark_btn.disabled)
        self.app.toggle_bookmark()
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()
        self.app.bookmark_btn.on_click(None)
        self.assertTrue(self.app.bookmark_editor.visible)
        self.app.bookmark_save_btn.on_click(None)
        self.assertEqual(self.app.bookmark_btn.icon, ft.Icons.BOOKMARK)
        self.assertEqual(self.app.bookmark_btn.tooltip, "删除当前页书签")
        self.assertEqual(self.app.bookmark_count.value, "1")
        self.app.go_page(1)
        self.assertEqual(self.app.bookmark_btn.icon, ft.Icons.BOOKMARK_BORDER)
        self.app.bookmark_btn.on_click(None)
        self.assertTrue(self.app.bookmark_editor.visible)
        self.app.bookmark_note_checkbox.value = True
        self.app.toggle_bookmark_note(SimpleNamespace(control=self.app.bookmark_note_checkbox))
        self.app.bookmark_note_field.value = "待重读"
        self.app.bookmark_save_btn.on_click(None)
        self.assertEqual([entry.controls[0].data for entry in self.app.bookmark_list.controls], [0, 1])
        self.assertEqual(self.app.store.bookmarks(self.app.book.id)[1]["note"], "待重读")
        transform = self.app.drawing_view.transform
        x, y = transform.to_view(30, 40)
        await self.app.start_stroke(SimpleNamespace(local_x=x, local_y=y))
        self.app.bookmark_list.controls[0].controls[0].on_click(None)
        self.assertEqual(self.app.page_index, 0)
        self.assertTrue(self.app.store.get_strokes(self.app.book.id, 1))
        self.assertEqual(self.app.store.books()[0].current_page, 0)
        self.app.bookmark_btn.on_click(None)
        self.assertEqual(self.app.bookmark_btn.icon, ft.Icons.BOOKMARK_BORDER)
        self.assertEqual([entry.controls[0].data for entry in self.app.bookmark_list.controls], [1])
        self.app.bookmark_list.controls[0].controls[0].on_click(None)
        self.assertEqual(self.app.page_index, 1)
        self.assertEqual(self.app.bookmark_btn.icon, ft.Icons.BOOKMARK)
        self.app.bookmark_list.controls[0].controls[1].on_click(None)
        self.assertEqual(self.app.page_index, 1)
        self.assertEqual(self.app.store.bookmark_pages(self.app.book.id), [])
        self.assertEqual([entry.value for entry in self.app.bookmark_list.controls],
                         ["暂无书签，点击工具栏书签图标添加"])

    async def test_selected_tool_uses_elevated_button_style(self) -> None:
        self.assertTrue(self.app.pen_btn.selected)
        self.assertEqual(
            self.app.pen_btn.style.elevation[ft.ControlState.SELECTED], 4
        )
        self.app.set_tool("marker")
        self.assertTrue(self.app.marker_btn.selected)
        self.assertEqual(
            self.app.marker_btn.style.shadow_color[ft.ControlState.SELECTED],
            "#21756766",
        )

    async def test_bookmark_directory_follows_book_selection_and_save_errors(self) -> None:
        """切书后只展示本书书签；写入失败时保持图标和目录原状。"""
        source = self.create_pdf()
        self.app.import_book(str(source))
        first_id = self.app.book.id
        self.app.toggle_bookmark()
        self.app.save_bookmark()
        other = self.root / "other.pdf"
        other.write_bytes(source.read_bytes())
        self.app.import_book(str(other))
        self.assertEqual(self.app.bookmark_count.value, "0")
        self.assertEqual(self.app.bookmark_btn.icon, ft.Icons.BOOKMARK_BORDER)
        with patch.object(self.app.store, "save_bookmark", side_effect=sqlite3.OperationalError("磁盘已满")):
            self.app.toggle_bookmark()
            self.app.save_bookmark()
        self.assertIn("保存书签失败", self.app.status.value)
        self.assertEqual(self.app.bookmark_count.value, "0")
        self.assertEqual(self.app.bookmark_btn.icon, ft.Icons.BOOKMARK_BORDER)
        self.app.open_book(next(book for book in self.app.store.books() if book.id == first_id))
        self.assertEqual(self.app.bookmark_count.value, "1")
        self.assertEqual(self.app.bookmark_btn.icon, ft.Icons.BOOKMARK)

    async def test_bookmark_cancel_optional_note_and_delete_other_page(self) -> None:
        """取消不写入；不勾备注不保存文字；删除其它页书签不会翻页。"""
        self.app.import_book(str(self.create_pdf()))
        self.app.notes_panel.visible = False
        self.app.toggle_bookmark()
        self.assertTrue(self.app.notes_panel.visible)
        self.app.bookmark_note_field.value = "取消的备注"
        self.app.cancel_bookmark()
        self.assertEqual(self.app.store.bookmarks(self.app.book.id), [])
        self.app.toggle_bookmark()
        self.app.bookmark_note_field.value = "未勾选的备注"
        self.app.save_bookmark()
        self.assertEqual(self.app.store.bookmarks(self.app.book.id), [{"page": 0, "note": ""}])
        self.app.go_page(1)
        with patch.object(self.app.store, "delete_bookmark", side_effect=sqlite3.OperationalError("只读磁盘")):
            self.app.bookmark_list.controls[0].controls[1].on_click(None)
        self.assertIn("删除书签失败", self.app.status.value)
        self.assertEqual(self.app.store.bookmark_pages(self.app.book.id), [0])
        self.app.bookmark_list.controls[0].controls[1].on_click(None)
        self.assertEqual(self.app.page_index, 1)
        self.assertEqual(self.app.store.bookmarks(self.app.book.id), [])

    async def test_settings_migrate_open_library_and_preserve_background(self) -> None:
        self.app.import_book(str(self.create_pdf()))
        self.app.toggle_bookmark()
        self.app.save_bookmark()
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
        self.assertEqual(self.app.store.bookmark_pages(self.app.book.id), [0])
        self.assertEqual(self.app.bookmark_btn.icon, ft.Icons.BOOKMARK)

    async def test_page_animation_settings_persist_and_switch_effect(self) -> None:
        self.assertTrue(self.app.page_animation_enabled)
        self.assertEqual(self.app.page_animation_type, "slide")
        self.assertTrue(self.app.apply_page_animation(True, "fade"))
        self.assertEqual(config.get_setting("page_animation_type"), "fade")
        self.assertIsNotNone(self.app.canvas_host.animate_opacity)
        self.assertIsNone(self.app.canvas_host.animate_offset)

        self.assertTrue(self.app.apply_page_animation(False, "fade"))
        self.assertFalse(self.app.page_animation_enabled)
        self.assertIsNone(self.app.canvas_host.animate_opacity)
        self.assertIsNone(self.app.canvas_host.animate_offset)
        self.assertEqual(self.app.canvas_host.opacity, 1)

    async def test_custom_free_canvas_and_auto_save_setting(self) -> None:
        self.assertTrue(self.app.apply_free_canvas_size(1200, 800))
        self.assertEqual(self.app.free_board.viewport, (1200.0, 800.0))
        self.assertTrue(self.app.free_board.manual_size)
        self.assertTrue(self.app.change_auto_save(False))
        self.assertFalse(self.app.auto_save_enabled)
        self.assertFalse(config.get_setting("auto_save_enabled"))
        self.app.free_board.strokes = [{
            "tool": "pen", "color": "#217567", "width": 3,
            "points": [[10, 10], [20, 20]],
        }]
        self.app.save_current_work()
        self.assertEqual(self.app.free_draft.load(), self.app.free_board.strokes)

    async def test_new_canvas_asks_before_discarding_existing_strokes(self) -> None:
        self.app.free_board.strokes = [{
            "tool": "pen", "color": "#217567", "width": 3,
            "points": [[10, 10], [20, 20]],
        }]
        self.app.create_free_canvas()
        confirm = self.app.page._dialogs.controls[-1]
        self.assertIn("未保存", getattr(confirm.title, "value", ""))
        self.assertEqual(len(confirm.actions), 3)
        # 选择取消不会清空当前画布，也不会进入尺寸设置。
        confirm.actions[0].on_click(None)
        self.session.get_page_patch()
        self.assertEqual(len(self.app.free_board.strokes), 1)

    async def test_settings_contains_update_and_auto_save_controls(self) -> None:
        self.app.open_settings()
        dialog = self.app.page._dialogs.controls[-1]
        self.assertIsInstance(dialog.content.controls[5], ft.Switch)
        self.assertTrue(any(
            isinstance(control, ft.OutlinedButton) and control.icon == ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED
            for control in dialog.content.controls
        ))

    async def test_auto_saved_session_restores_reading_page_and_workspace(self) -> None:
        self.app.import_book(str(self.create_pdf()))
        self.app.go_page(1)
        self.app.show_workspace("drawing")
        self.app.save_current_work()
        self.app.document.close()
        self.app.document = None
        self.app.store.close()
        self.session.close()

        connection = RecordingConnection()
        session = Session(connection)
        restored = ReadDrawApp(session.page)
        session.get_page_patch()
        self.assertEqual(restored.workspace, "drawing")
        self.assertIsNotNone(restored.book)
        self.assertEqual(restored.page_index, 1)
        restored.document.close()
        restored.store.close()
        session.close()

    async def test_disabled_auto_save_starts_with_blank_default_canvas(self) -> None:
        """关闭自动保存后，重启不应恢复旧笔迹或自定义画布尺寸。"""
        self.assertTrue(self.app.apply_free_canvas_size(1200, 800))
        self.app.free_board.strokes = [{
            "tool": "pen", "color": "#217567", "width": 3,
            "points": [[10, 10], [20, 20]],
        }]
        self.app.save_current_work()
        self.assertTrue(self.app.change_auto_save(False))
        self.app.store.close()
        self.session.close()

        connection = RecordingConnection()
        session = Session(connection)
        restored = ReadDrawApp(session.page)
        self.assertFalse(restored.auto_save_enabled)
        self.assertEqual(restored.free_board.strokes, [])
        self.assertEqual(restored.free_board.viewport, (760.0, 560.0))
        self.assertFalse(restored.free_board.manual_size)
        restored.store.close()
        session.close()

    async def test_disabled_page_animation_keeps_navigation_working(self) -> None:
        self.app.import_book(str(self.create_pdf()))
        self.assertTrue(self.app.apply_page_animation(False, "slide"))
        self.app.go_page(1)
        self.assertEqual(self.app.page_index, 1)
        self.assertIsNone(self.app.canvas_host.animate_offset)
        self.assertEqual(self.app.canvas_host.offset, (0, 0))

    async def test_animation_settings_controls_and_failed_save(self) -> None:
        """通过真实设置控件切换选项，保存失败时还原最近一次成功的值。"""
        self.app.open_settings()
        # 录制连接没有原生客户端，显式提交控件树后再模拟用户事件。
        self.session.get_page_patch()
        dialog = self.app.page._dialogs.controls[-1]
        switch = dialog.content.controls[2]
        selector = dialog.content.controls[3]
        self.assertIsInstance(switch, ft.Switch)
        selector.value = "scale"
        selector.on_select(SimpleNamespace(control=selector))
        self.session.get_page_patch()
        self.assertEqual(self.app.page_animation_type, "scale")
        self.assertEqual(config.get_setting("page_animation_type"), "scale")
        switch.value = False
        switch.on_change(SimpleNamespace(control=switch))
        self.session.get_page_patch()
        self.assertTrue(selector.disabled)
        self.assertFalse(config.get_setting("page_animation_enabled"))
        switch.value = True
        switch.on_change(SimpleNamespace(control=switch))
        self.assertFalse(selector.disabled)
        with patch("main.config.save_settings", side_effect=OSError("只读目录")):
            selector.value = "fade"
            selector.on_select(SimpleNamespace(control=selector))
        self.assertEqual(selector.value, "scale")
        self.assertEqual(self.app.page_animation_type, "scale")

    async def test_page_transitions_finish_and_ignore_outdated_tasks(self) -> None:
        """每种动画最终归位，快速翻页时旧任务不能提前结束新动画。"""
        self.app.import_book(str(self.create_pdf()))
        for kind in ("slide", "fade", "scale"):
            self.app.apply_page_animation(True, kind)
            self.app.go_page(1 if self.app.page_index == 0 else -1)
            self.assertEqual(self.app.canvas_host.opacity, 0 if kind == "fade" else 1)
            await asyncio.sleep(0.08)
            self.assertEqual(self.app.canvas_host.offset, (0, 0))
            self.assertEqual(self.app.canvas_host.opacity, 1)
            self.assertEqual(self.app.canvas_host.scale, 1)
        self.app.apply_page_animation(True, "fade")
        self.app.go_page(-1)
        stale_revision = self.app._page_transition_revision
        self.app.go_page(1)
        with patch("main.asyncio.sleep", new=AsyncMock()):
            await self.app._finish_page_transition(stale_revision)
        self.assertEqual(self.app.canvas_host.opacity, 0)
        self.app.apply_page_animation(False, "fade")
        await asyncio.sleep(0.08)
        self.assertEqual(self.app.canvas_host.opacity, 1)

    async def test_invalid_file_reports_error_without_exiting(self) -> None:
        self.app.import_book(str(self.root / "missing.pdf"))
        self.assertIsNone(self.app.book)
        self.assertIn("无法打开书籍", self.app.status.value)
        self.assertEqual(self.app.page._dialogs.controls, [])
        self.assertGreater(len(self.connection.messages), 0)

    async def test_shutdown_tolerates_a_disconnected_window(self) -> None:
        with patch.object(self.app.page.window, "close", new=AsyncMock(side_effect=RuntimeError("Session closed"))):
            await self.app._close_window()
        self.assertTrue(self.app._closed)
        self.assertIsNone(self.app.document)

    async def test_text_note_editor_saves_content_without_opening_dialog(self) -> None:
        self.app.import_book(str(self.create_pdf()))
        with patch.object(self.app.page, "show_dialog") as show_dialog:
            self.app.open_text_dialog()
            self.assertTrue(self.app.note_editor.visible)
            show_dialog.assert_not_called()

            self.app.save_text_annotation()
            self.assertEqual(self.app.store.text_annotations(self.app.book.id, 0), [])

            self.app.note_quote_field.value = "ReadDraw page"
            self.app.note_content_field.value = "重点内容"
            self.app.save_text_annotation()

        annotations = self.app.store.text_annotations(self.app.book.id, 0)
        self.assertEqual(len(annotations), 1)
        self.assertEqual(annotations[0].content, "重点内容")
        self.assertEqual(annotations[0].quote, "ReadDraw page")
        self.assertFalse(self.app.note_editor.visible)
        show_dialog.assert_not_called()

    async def test_window_close_requests_host_exit_after_cleanup(self) -> None:
        with patch.object(self.app.page.window, "close", new=AsyncMock()) as close:
            await self.app._close_window()
        self.assertFalse(self.app.page.window.prevent_close)
        close.assert_awaited_once()

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
        self.assertAlmostEqual(stroke["opacity"], 0.20)
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

    async def test_shape_dropdown_draws_live_shape_and_saves_for_undo(self) -> None:
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()
        self.assertEqual(len(self.app.shape_btn.items), 7)
        self.app.select_shape("triangle")

        transform = self.app.drawing_view.transform
        def pointer(x, y):
            return SimpleNamespace(local_x=transform.to_view(x, y)[0],
                                   local_y=transform.to_view(x, y)[1])

        await self.app.start_stroke(pointer(130, 140))
        await self.app.update_stroke(pointer(100, 120))
        await self.app.update_stroke(pointer(30, 40))
        self.assertAlmostEqual(self.app.active_stroke["shape_start"][0], 130)
        self.assertAlmostEqual(self.app.active_stroke["shape_start"][1], 140)
        self.assertGreater(len(self.app.drawing_view._stroke_shapes(self.app.active_stroke)), 0)
        await self.app.end_stroke(None)

        self.assertEqual(self.app.store.get_strokes(self.app.book.id, 0)[0]["shape"], "triangle")
        self.app.undo()
        self.assertEqual(self.app.strokes, [])

    async def test_ctrl_constrains_live_shape_while_held(self) -> None:
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()
        self.app.select_shape("circle")
        transform = self.app.drawing_view.transform
        def pointer(x, y, ctrl=False):
            return SimpleNamespace(local_x=transform.to_view(x, y)[0],
                                   local_y=transform.to_view(x, y)[1], ctrl=ctrl)

        await self.app.start_stroke(pointer(30, 40))
        with patch("main.is_control_pressed", side_effect=lambda fallback: fallback):
            await self.app.update_stroke(pointer(130, 80, ctrl=True))
        points = self.app.active_stroke["points"]
        width = max(point[0] for point in points) - min(point[0] for point in points)
        height = max(point[1] for point in points) - min(point[1] for point in points)
        self.assertAlmostEqual(width, height, places=5)

    async def test_clear_page_strokes_saves_and_can_be_undone(self) -> None:
        """一键清空本页笔迹但不影响文字批注，并可用撤销恢复。"""
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()
        self.app.strokes = [{
            "tool": "pen", "color": "#E45756", "width": 4,
            "points": [[20, 30], [80, 90]],
        }]
        self.app.store.save_strokes(self.app.book.id, self.app.page_index, self.app.strokes)
        self.app.store.add_text_annotation(self.app.book.id, self.app.page_index, "note", "保留的文字批注")
        self.app.update_canvas()

        self.app.clear_current_page_strokes()

        self.assertEqual(self.app.strokes, [])
        self.assertEqual(self.app.store.get_strokes(self.app.book.id, self.app.page_index), [])
        self.assertEqual(len(self.app.store.text_annotations(self.app.book.id, self.app.page_index)), 1)
        self.app.undo()
        self.assertEqual(len(self.app.strokes), 1)
        self.assertEqual(len(self.app.store.get_strokes(self.app.book.id, self.app.page_index)), 1)

    async def test_pen_pressure_updates_the_active_stroke_width(self) -> None:
        """笔压事件改变当前画笔段宽度，缺少压力事件时仍使用默认粗细。"""
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()
        transform = self.app.drawing_view.transform
        def pointer(x, y):
            return SimpleNamespace(local_x=transform.to_view(x, y)[0],
                                   local_y=transform.to_view(x, y)[1])

        await self.app.start_stroke(pointer(40, 50))
        self.session.get_page_patch()
        self.assertEqual(self.app.active_stroke["pressures"], [0.65])
        first_width = self.app.drawing_view.active_path.paint.stroke_width
        self.app.drawing_view.detector.on_force_press_update(
            SimpleNamespace(pressure=0.95)
        )
        await self.app.update_stroke(pointer(140, 50))
        self.assertEqual(self.app.active_stroke["pressures"], [0.95, 0.95])
        self.assertGreater(self.app.drawing_view.active_path.paint.stroke_width, first_width)
        await self.app.end_stroke(None)
        self.assertEqual(
            self.app.store.get_strokes(self.app.book.id, self.app.page_index)[0]["pressures"],
            [0.95, 0.95],
        )

    async def test_mouse_pen_speed_simulates_pressure(self) -> None:
        """鼠标慢画线宽较粗、快画较细，压力值会保存在笔迹中。"""
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()
        transform = self.app.drawing_view.transform

        def pointer(x, y, global_x, global_y):
            return SimpleNamespace(
                local_x=transform.to_view(x, y)[0],
                local_y=transform.to_view(x, y)[1],
                global_position=SimpleNamespace(x=global_x, y=global_y),
            )

        with patch("main.time.perf_counter", side_effect=[0.0, 0.05, 0.1]):
            await self.app.start_stroke(pointer(40, 50, 100, 100))
            await self.app.update_stroke(pointer(50, 50, 105, 100))
            slow_pressure = self.app.stroke_pressure
            await self.app.update_stroke(pointer(60, 50, 205, 100))
            fast_pressure = self.app.stroke_pressure

        self.assertGreater(slow_pressure, 0.65)
        self.assertLess(fast_pressure, slow_pressure)
        self.assertEqual(self.app.active_stroke["pressures"], [0.65, slow_pressure, fast_pressure])

    async def test_flet_pan_events_await_stroke_updates(self) -> None:
        """Flet 手势转发必须等待异步回调，否则画笔只会显示起笔点。"""
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()
        transform = self.app.drawing_view.transform

        def pointer(x, y):
            return SimpleNamespace(local_x=transform.to_view(x, y)[0],
                                   local_y=transform.to_view(x, y)[1])

        detector = self.app.drawing_view.detector
        await detector.on_pan_down(pointer(40, 50))
        await detector.on_pan_update(pointer(140, 50))
        self.assertEqual(len(self.app.active_stroke["points"]), 2)
        self.assertGreater(len(self.app.drawing_view.ink.shapes), 1)
        await detector.on_pan_end(pointer(140, 50))

    async def test_mouse_mode_does_not_create_strokes_and_alt_scroll_zooms(self) -> None:
        self.app.import_book(str(self.create_pdf()))
        self.app.set_tool("mouse")
        self.assertTrue(self.app.mouse_btn.selected)
        self.assertFalse(self.app.pen_btn.selected)
        event = SimpleNamespace(local_x=100, local_y=100)
        await self.app.start_stroke(event)
        await self.app.update_stroke(event)
        await self.app.end_stroke(event)
        self.assertEqual(self.app.strokes, [])
        self.app.alt_pressed = True
        previous_zoom = self.app.drawing_view.zoom
        self.app.on_canvas_scroll(SimpleNamespace(scroll_delta=SimpleNamespace(x=0, y=-120)))
        self.assertGreater(self.app.drawing_view.zoom, previous_zoom)

    async def test_scroll_pages_in_every_tool_and_arrow_keys(self) -> None:
        """普通滚轮和左右箭头翻页不受当前绘画工具影响。"""
        self.app.import_book(str(self.create_pdf()))
        self.app.set_tool("pen")
        self.assertEqual(self.app.page_index, 0)
        self.app.on_canvas_scroll(SimpleNamespace(scroll_delta=SimpleNamespace(x=0, y=120)))
        self.assertEqual(self.app.page_index, 1)
        self.app.on_canvas_scroll(SimpleNamespace(scroll_delta=SimpleNamespace(x=0, y=-120)))
        self.assertEqual(self.app.page_index, 0)
        self.app.on_keyboard_event(SimpleNamespace(key="ArrowRight", alt=False))
        self.assertEqual(self.app.page_index, 1)
        self.app.on_keyboard_event(SimpleNamespace(key="ArrowLeft", alt=False))
        self.assertEqual(self.app.page_index, 0)

    async def test_page_navigation_resets_zoom_and_pan(self) -> None:
        """翻页后不继承上一页的放大比例和拖动偏移。"""
        self.app.import_book(str(self.create_pdf()))
        self.app.drawing_view.set_zoom(2.0)
        self.app.drawing_view.pan_offset = (-80.0, -40.0)
        self.app.drawing_view.layout()
        self.app.go_page(1)
        self.assertEqual(self.app.drawing_view.zoom, 1.0)
        self.assertEqual(self.app.drawing_view.pan_offset, (0.0, 0.0))
        self.app.go_page(-1)
        self.assertEqual(self.app.drawing_view.zoom, 1.0)

    async def test_mouse_mode_pans_zoomed_page_without_drawing(self) -> None:
        """鼠标模式下放大页面可拖动，拖动不会新增笔迹。"""
        self.app.import_book(str(self.create_pdf()))
        self.app.set_tool("mouse")
        canvas = self.app.drawing_view
        canvas.set_zoom(2.0)
        start = SimpleNamespace(global_position=SimpleNamespace(x=500.0, y=300.0))
        update = SimpleNamespace(global_position=SimpleNamespace(x=560.0, y=340.0))
        canvas._begin_page_pan(start)
        await canvas._update_pointer(update)
        await canvas._end_pointer(update)
        self.assertNotEqual(canvas.pan_offset, (0.0, 0.0))
        self.assertEqual(self.app.strokes, [])

    async def test_scroll_over_inserted_image_still_navigates_pages(self) -> None:
        """插入图片位于鼠标下方时，图片手势也转发阅读区滚轮。"""
        self.app.import_book(str(self.create_pdf()))
        source = self.root / "inserted.png"
        Image.new("RGB", (80, 40), "red").save(source)
        attachment = self.app.store.add_attachment(self.app.book.id, 0, str(source))
        self.app.load_page()
        event = SimpleNamespace(scroll_delta=SimpleNamespace(x=0, y=120))
        self.app.reader_scroll_detector.on_scroll(event)
        self.assertEqual(self.app.page_index, 1)

    async def test_alt_scroll_zoom_works_outside_mouse_mode(self) -> None:
        """按住 Alt 的滚轮缩放在画笔和荧光笔模式下同样可用。"""
        self.app.import_book(str(self.create_pdf()))
        self.app.set_tool("marker")
        self.app.alt_pressed = True
        previous_zoom = self.app.drawing_view.zoom
        event = SimpleNamespace(scroll_delta=SimpleNamespace(x=0, y=-120))
        self.app.reader_scroll_detector.on_scroll(event)
        self.assertGreater(self.app.drawing_view.zoom, previous_zoom)
        # 松开 Alt 后系统即时状态优先，即使页面缓存仍为 True 也应恢复翻页。
        with patch("main.is_alt_pressed", return_value=False):
            zoom_after = self.app.drawing_view.zoom
            self.app.reader_scroll_detector.on_scroll(
                SimpleNamespace(scroll_delta=SimpleNamespace(x=0, y=120))
            )
            self.assertEqual(self.app.page_index, 1)
        self.assertEqual(self.app.drawing_view.zoom, 1.0)
        self.assertNotEqual(zoom_after, self.app.drawing_view.zoom)

    async def test_scroll_after_zoom_changes_page_without_full_page_refresh(self) -> None:
        """缩放后松开 Alt 滚轮翻页时不整页刷新，滚轮监听器保持挂载。"""
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()
        scroll_detector = self.app.reader_scroll_detector
        self.app.alt_pressed = True
        self.app.on_canvas_scroll(
            SimpleNamespace(scroll_delta=SimpleNamespace(x=0, y=-120))
        )
        self.assertGreater(self.app.drawing_view.zoom, 1.0)

        self.app.alt_pressed = False
        with patch("main.is_alt_pressed", return_value=False):
            with patch.object(self.app.page, "update") as full_page_update:
                scroll_detector.on_scroll(
                    SimpleNamespace(scroll_delta=SimpleNamespace(x=0, y=120))
                )

        self.assertEqual(self.app.page_index, 1)
        self.assertIs(self.app.canvas_host.content, scroll_detector)
        self.assertIs(scroll_detector.content, self.app.drawing_view.control)
        self.assertTrue(full_page_update.called)
        self.assertTrue(all(call.args for call in full_page_update.call_args_list))

    async def test_continuous_image_drag_saves_only_on_release(self) -> None:
        """走真实的 Flet 事件解码与控件回调，连续移动后翻页仍保留最终位置。"""
        self.app.import_book(str(self.create_pdf()))
        source = self.root / "inserted.png"
        Image.new("RGB", (80, 40), "red").save(source)
        attachment = self.app.store.add_attachment(self.app.book.id, 0, str(source))
        self.app.load_page()
        self.app.set_tool("mouse")
        self.session.get_page_patch()
        canvas = self.app.drawing_view
        position = canvas.attachment_controls[attachment.id]
        detector = position.content.controls[0]
        initial_left, initial_top = position.left, position.top
        with patch.object(self.app.store, "update_attachment_position", wraps=self.app.store.update_attachment_position) as save:
            await self.session.dispatch_event(detector._i, "pan_start", {
                "k": "mouse", "g": {"x": 500, "y": 300}, "l": {"x": 20, "y": 20},
            })
            for dx, dy in ((5, 3), (10, 6), (80, 40), (80, 40), (60, 30), (120, 90)):
                await self.session.dispatch_event(detector._i, "pan_update", {
                    "g": {"x": 500 + dx, "y": 300 + dy}, "l": {"x": 20, "y": 20},
                    "ld": {"x": 5, "y": 3},
                })
                self.assertAlmostEqual(position.left, initial_left + dx)
                self.assertAlmostEqual(position.top, initial_top + dy)
                self.assertIs(position.content.controls[0], detector)
            save.assert_not_called()
            # 松开时鼠标继续向前移动，必须保存结束坐标，不能漏掉最后一段。
            await self.session.dispatch_event(detector._i, "pan_end", {
                "g": {"x": 650, "y": 400}, "l": {"x": 20, "y": 20}, "v": {"x": 0, "y": 0},
            })
            expected = (round(24 + 150 / canvas.transform.scale), round(24 + 100 / canvas.transform.scale))
            save.assert_called_once_with(attachment.id, *expected)
            await self.session.dispatch_event(detector._i, "pan_cancel", {})
            save.assert_called_once()
        self.assertEqual(self.app.strokes, [])
        self.app.go_page(1)
        self.app.go_page(-1)
        restored = self.app.attachments[0]
        self.assertEqual((restored.x, restored.y), expected)

    async def test_image_picker_inserts_without_reloading_reader_or_losing_undo(self) -> None:
        """覆盖原先遗漏的按钮完整回调；导入后书页与撤销历史应保持不变。"""
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()
        source = self.root / "中文图片.jpg"
        Image.new("RGB", (320, 160), "red").save(source)
        original_src = self.app.drawing_view.image.src
        self.app.history.append([])
        with (
            patch.object(self.app.image_dialog, "pick_file", new=AsyncMock(return_value=str(source))),
            patch.object(self.app, "load_page") as reload_page,
        ):
            await self.app.open_image_picker()
        reload_page.assert_not_called()
        self.assertEqual(self.app.history, [[]])
        self.assertIs(self.app.drawing_view.image.src, original_src)
        self.assertEqual(len(self.app.attachments), 1)
        attachment = self.app.attachments[0]
        self.assertEqual(attachment.name, source.name)
        with Image.open(attachment.path) as saved:
            self.assertEqual(saved.format, "PNG")
        self.assertIn(attachment.id, self.app.drawing_view.attachment_controls)
        self.assertFalse(self.app.image_btn.disabled)
        self.assertFalse(self.app._closed)

    async def test_inserted_image_can_be_resized_and_deleted(self) -> None:
        """图片编辑操作同步更新数据库与文件，不重载书页或清空笔迹。"""
        self.app.import_book(str(self.create_pdf()))
        source = self.root / "editable.png"
        Image.new("RGB", (100, 50), "green").save(source)
        attachment = self.app.store.add_attachment(self.app.book.id, 0, str(source))
        self.app.attachments = self.app.store.attachments(self.app.book.id, 0)
        self.app.load_page()
        attachment = self.app.attachments[0]
        original_page = self.app.drawing_view.image.src
        self.app.set_tool("mouse")
        self.app.drawing_view._select_attachment(attachment)

        canvas = self.app.drawing_view
        handle = canvas.attachment_resize_handles[attachment.id]
        with patch.object(self.app.store, "update_attachment_size", wraps=self.app.store.update_attachment_size) as save:
            await self.session.dispatch_event(handle._i, "pan_start", {
                "k": "mouse", "g": {"x": 500, "y": 300}, "l": {"x": 20, "y": 20},
            })
            await self.session.dispatch_event(handle._i, "pan_update", {
                "g": {"x": 550, "y": 325}, "l": {"x": 20, "y": 20},
            })
            self.assertEqual(save.call_count, 0)
            await self.session.dispatch_event(handle._i, "pan_end", {
                "g": {"x": 550, "y": 325}, "l": {"x": 20, "y": 20}, "v": {"x": 0, "y": 0},
            })
            self.assertEqual(save.call_count, 1)
        saved = self.app.store.attachments(self.app.book.id, 0)[0]
        self.assertGreater(saved.width, 100)
        self.assertEqual(saved.width / saved.height, 2)
        image_file = Path(saved.path)
        self.app.drawing_view._delete_attachment(attachment)
        self.assertFalse(image_file.exists())
        self.assertEqual(self.app.store.attachments(self.app.book.id, 0), [])
        self.assertEqual(self.app.attachments, [])
        self.assertIs(self.app.drawing_view.image.src, original_page)

    async def test_invalid_image_and_picker_errors_leave_app_usable(self) -> None:
        """损坏图片、失效路径或选择器异常都只提示错误，且不留下无效附件。"""
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()
        corrupt = self.root / "corrupt.png"
        corrupt.write_text("not an image")
        for selection in (corrupt, self.root / "missing.png"):
            with patch.object(self.app.image_dialog, "pick_file", new=AsyncMock(return_value=str(selection))):
                await self.app.open_image_picker()
            self.assertEqual(self.app.store.attachments(self.app.book.id, 0), [])
            self.assertFalse(self.app.image_btn.disabled)
            self.assertFalse(self.app._closed)
            self.assertIn("无法插入图片", self.app.status.value)
        with patch.object(self.app.image_dialog, "pick_file", new=AsyncMock(side_effect=OSError("dialog failed"))):
            await self.app.open_image_picker()
        self.assertIn("dialog failed", self.app.status.value)
        self.assertEqual(list(self.app.store.attachment_dir.iterdir()), [])
        self.app.go_page(1)
        self.assertEqual(self.app.page_index, 1)

    async def test_image_selection_cancel_reentry_and_page_change(self) -> None:
        """取消、重复点击、选择期间翻页都不能误写入另一页面。"""
        self.app.import_book(str(self.create_pdf()))
        self.session.get_page_patch()
        with patch.object(self.app.image_dialog, "pick_file", new=AsyncMock(return_value=None)):
            await self.app.open_image_picker()
        selected = asyncio.Future()
        with patch.object(self.app.image_dialog, "pick_file", new=AsyncMock(return_value=None)) as pick:
            async def wait_for_selection(_picker):
                return await selected
            pick.side_effect = wait_for_selection
            task = asyncio.create_task(self.app.open_image_picker())
            await asyncio.sleep(0)
            await self.app.open_image_picker()
            pick.assert_awaited_once()
            self.app.go_page(1)
            selected.set_result(str(self.root / "unused.png"))
            await task
        self.assertEqual(self.app.store.attachments(self.app.book.id, 0), [])
        self.assertEqual(self.app.store.attachments(self.app.book.id, 1), [])
        self.assertIn("阅读页面已切换", self.app.status.value)
        self.assertFalse(self.app.image_btn.disabled)

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
