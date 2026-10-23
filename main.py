"""ReadDraw: a small local PDF reader with page drawing annotations."""

from __future__ import annotations

import os
import asyncio
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any

# 选择器辅助进程不启动 Flet、数据库或同步服务，也不使用窗口程序的标准输出。
if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--select-image-file":
    from readdraw.file_dialogs import run_image_picker_helper

    run_image_picker_helper(sys.argv[2])
    raise SystemExit(0)

from readdraw import config
from readdraw.diagnostics import configure_logging

# 在导入第三方本机组件前启用崩溃日志；窗口程序没有控制台，日志用于定位启动故障。
if __name__ == "__main__":
    configure_logging()

import flet as ft
from PIL import Image as PILImage
from readdraw.data_location import migrate_data_dir
from readdraw.file_dialogs import ImageFileDialog
from readdraw.canvas_view import ReadingCanvas
from readdraw.drawing import (
    MARKER_COLOR, MARKER_OPACITY, MARKER_WIDTH_MULTIPLIER,
    clone_strokes, compose_page, mouse_speed_pressure, normalize_pressure, point_near_stroke,
)
from readdraw.models import Book
from readdraw.reader import open_document, render_page
from readdraw.settings_view import create_settings_dialog
from readdraw.desktop_view import build_desktop
from readdraw.keyboard_state import is_alt_pressed
from readdraw.storage import Store
from readdraw.sync_server import SyncServer
from readdraw.updater import ReleaseInfo, check_latest_release, download_update, is_packaged, schedule_windows_replace
from readdraw.version import APP_TAG, APP_VERSION


class ReadDrawApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.store = Store()
        self.books = self.store.books()
        self.book: Book | None = None
        self.document: Any = None
        self.page_index = 0
        self.base_image: PILImage.Image | None = None
        self.strokes: list[dict[str, Any]] = []
        self.history: list[list[dict[str, Any]]] = []
        self.redo_stack: list[list[dict[str, Any]]] = []
        self.text_annotations = []
        self.attachments = []
        self.active_stroke: dict[str, Any] | None = None
        self.tool = "pen"
        self.color = "#E45756"
        self.marker_color = MARKER_COLOR
        self.thickness = 4
        self._closed = False
        self._closing = False
        self._image_importing = False
        self.alt_pressed = False
        configured_background = config.get_setting("background", config.DEFAULT_BACKGROUND)
        self.background_color = configured_background if configured_background in config.BACKGROUND_OPTIONS.values() else config.DEFAULT_BACKGROUND
        self.drawing_view = ReadingCanvas(
            self.start_stroke, self.update_stroke, self.end_stroke,
            on_attachment_move=self.on_attachment_move,
            on_attachment_end=self.on_attachment_end,
            on_attachment_resize=self.on_attachment_resize,
            on_attachment_delete=self.on_attachment_delete,
            can_drag_attachments=lambda: self.tool == "mouse",
            on_zoom=self.on_canvas_scroll,
            can_pan_page=lambda: self.tool == "mouse",
            on_pressure=self.update_stroke_pressure,
        )
        self.erasing = False
        self.stroke_pressure = 0.65
        self._device_pressure_active = False
        self._pressure_pointer: tuple[float, float] | None = None
        self._pressure_sample_time: float | None = None
        self.directory_picker = ft.FilePicker()
        self.data_path_text = ft.Text(str(config.APP_DIR), size=10, color="#667085", selectable=True)
        self.settings_path_text = ft.Text(str(config.APP_DIR), size=12, color="#667085", selectable=True)
        self.canvas_host = ft.Container(expand=True, alignment=ft.Alignment.CENTER, bgcolor=self.background_color, border_radius=8,
            content=ft.Column([ft.Icon(ft.Icons.MENU_BOOK_ROUNDED, size=54, color="#8B95A5"),
                ft.Text("打开 PDF / EPUB 开始阅读", size=20, weight=ft.FontWeight.W_600, color="#344054"),
                ft.Text("支持点击下方按钮选择文件，也可以把文件直接拖到阅读区域", color="#667085"),
                ft.FilledButton("打开文件", icon=ft.Icons.FOLDER_OPEN_ROUNDED, on_click=self.open_picker, height=42)],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=10))
        self.status = ft.Text("准备就绪", size=12, color="#667085")
        self.page_label = ft.Text("未打开书籍", size=13, color="#475467")
        self.file_picker = ft.FilePicker()
        self.image_picker = ft.FilePicker()
        self.image_dialog = ImageFileDialog()
        self.sync_server = SyncServer()
        self.pending_release: ReleaseInfo | None = None
        self.build()

    def build(self) -> None:
        build_desktop(self)

    def toggle_library(self, _=None) -> None:
        self.library_panel.visible = not self.library_panel.visible
        self.page.update()

    def toggle_notes(self, _=None) -> None:
        self.notes_panel.visible = not self.notes_panel.visible
        self.page.update()

    def fit_page(self, _=None) -> None:
        self.drawing_view.reset_view()
        self.page.update()

    def on_page_error(self, event: Any) -> None:
        logging.getLogger("readdraw").error("Client event error: %s", getattr(event, "data", event))

    def on_keyboard_event(self, event: Any) -> None:
        """处理全局快捷键：左右箭头翻页，并记录 Alt 状态。"""
        key = str(getattr(event, "key", "")).lower()
        self.alt_pressed = bool(getattr(event, "alt", False)) or key in {"alt", "alt left", "alt right"}
        normalized_key = key.replace(" ", "").replace("_", "")
        if normalized_key in {"arrowleft", "left"}:
            self.go_page(-1)
        elif normalized_key in {"arrowright", "right"}:
            self.go_page(1)

    def on_canvas_scroll(self, event: Any) -> None:
        """Alt 加滚轮缩放页面，否则滚轮翻页，和当前绘画工具无关。"""
        delta = getattr(getattr(event, "scroll_delta", None), "y", 0.0)
        if not delta or not self.document:
            return
        if is_alt_pressed(self.alt_pressed):
            factor = 1.1 if delta < 0 else 1 / 1.1
            changed = self.drawing_view.set_zoom(self.drawing_view.zoom * factor)
            status = f"按住 Alt 缩放：{self.drawing_view.zoom:.0%}"
        else:
            # 鼠标向下滚动进入下一页，向上滚动返回上一页。
            self.go_page(1 if delta > 0 else -1)
            changed = False
            status = self.page_label.value
        if changed:
            try:
                self.drawing_view.control.update()
            except RuntimeError:
                # 单元测试或页面重建期间控件可能暂未挂载，缩放状态仍已保存。
                pass
        self.status.value = status
        self.status.update()

    def color_button(self, color: str) -> ft.Control:
        return ft.Container(width=23, height=23, bgcolor=color, border_radius=12, border=ft.Border.all(2, "#FFFFFF"), tooltip=f"颜色 {color}", on_click=lambda e, c=color: self.set_color(c))

    def refresh_library(self) -> None:
        self.library_list.controls.clear()
        if hasattr(self, "library_count"):
            self.library_count.value = f"{len(self.books)}"
        if not self.books:
            self.library_list.controls.append(ft.Text("还没有书籍", size=13, color="#98A2B3"))
        for book in self.books:
            selected = self.book and book.id == self.book.id
            self.library_list.controls.append(ft.Container(padding=ft.Padding.symmetric(horizontal=10, vertical=10), border_radius=6,
                bgcolor="#EEF2FF" if selected else None, on_click=lambda e, b=book: self.open_book(b), content=ft.Row([
                    ft.Icon(ft.Icons.PICTURE_AS_PDF_ROUNDED if book.format == "pdf" else ft.Icons.MENU_BOOK_ROUNDED, color="#3857D6" if selected else "#98A2B3", size=19),
                    ft.Column([ft.Text(book.title, size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, color="#1D2939"), ft.Text(f"第 {book.current_page + 1} / {book.pages} 页", size=11, color="#98A2B3")], spacing=2, expand=True)], spacing=8)))

    async def open_picker(self, _=None) -> None:
        files = await self.file_picker.pick_files(
            dialog_title="选择 PDF 或 EPUB 书籍",
            allow_multiple=False,
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["pdf", "epub"],
        )
        if files and files[0].path:
            self.import_book(files[0].path)

    async def choose_data_dir(self, _=None) -> None:
        try:
            selected = await self.directory_picker.get_directory_path(
                dialog_title="选择 ReadDraw 数据保存位置",
                initial_directory=str(config.APP_DIR),
            )
        except Exception as exc:
            self.show_error(f"无法选择数据位置：{exc}")
            return
        if not selected:
            return
        current_id = self.book.id if self.book else None
        was_syncing = self.sync_server.running
        try:
            await self.end_stroke(None)
            self.sync_server.stop()
            target = migrate_data_dir(self.store, selected)
            replacement = Store(target / "readdraw.sqlite3")
            previous = self.store
            self.store = replacement
            previous.close()
            self.books = self.store.books()
            self.sync_server.database_path = config.DB_PATH
            self.data_path_text.value = str(target)
            self.settings_path_text.value = str(target)
            self.refresh_library()
            if current_id:
                matching = next((book for book in self.books if book.id == current_id), None)
                if matching:
                    self.open_book(matching)
            self.status.value = f"数据已保存到：{target}"
            self.page.update()
        except Exception as exc:
            self.show_error(f"修改数据位置失败：{exc}")
        finally:
            if was_syncing:
                self.sync_server.start()

    def apply_background(self, color: str) -> bool:
        """Publish a background only after its preference has been saved."""
        if color not in config.BACKGROUND_OPTIONS.values():
            return False
        try:
            config.save_settings(background=color)
        except OSError as exc:
            self.show_error(f"保存背景设置失败：{exc}")
            return False
        self.background_color = color
        self.canvas_host.bgcolor = color
        self.page.bgcolor = color
        self.status.color = "#D0D5DD" if color == "#263238" else "#667085"
        self.page.update()
        return True

    def open_settings(self, _=None) -> None:
        self.settings_path_text.value = str(config.APP_DIR)
        dialog = create_settings_dialog(
            self.background_color, self.settings_path_text,
            self.apply_background, self.choose_data_dir,
            lambda event: self.page.pop_dialog(),
        )
        self.page.show_dialog(dialog)

    async def check_updates(self, _=None) -> None:
        self.status.value = "正在检查 GitHub Releases..."
        self.status.update()
        try:
            release = await asyncio.to_thread(check_latest_release)
        except Exception as exc:
            self.status.value = f"更新检查失败：{exc}"
            self.status.update()
            return
        if release is None:
            self.status.value = f"当前已是最新版本 {APP_TAG}"
            self.status.update()
            return
        self.pending_release = release
        self.show_update_dialog(release)

    def show_update_dialog(self, release: ReleaseInfo) -> None:
        notes = release.notes.strip() or "该版本没有发布说明。"
        notes = notes[:1200]
        actions = [ft.TextButton("稍后", on_click=lambda e: self.page.pop_dialog())]
        if is_packaged():
            actions.append(ft.FilledButton("下载并重启", icon=ft.Icons.DOWNLOAD_ROUNDED, on_click=self.download_pending_update))
        else:
            actions.append(ft.TextButton("源码模式", disabled=True))
        self.page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text(f"发现新版本 {release.tag}"),
            content=ft.Column([ft.Text(release.name, weight=ft.FontWeight.W_600), ft.Text(notes, selectable=True)], tight=True, width=520),
            actions=actions,
        ))

    async def download_pending_update(self, _=None) -> None:
        if not self.pending_release:
            return
        try:
            downloaded = await asyncio.to_thread(download_update, self.pending_release)
            schedule_windows_replace(downloaded)
            self.page.pop_dialog()
            self.status.value = "更新已下载，应用将在退出后重启"
            self.status.update()
            await self._close_window()
        except Exception as exc:
            self.show_error(f"更新失败：{exc}")

    async def open_image_picker(self, _=None) -> None:
        """串行完成选择、校验和附件更新，异常只在状态栏提示。"""
        if self._closed or self._image_importing:
            return
        if not self.book:
            self.show_error("请先打开一本书")
            return
        self._image_importing = True
        self.image_btn.disabled = True
        self.image_btn.update()
        book_id, page_index = self.book.id, self.page_index
        logger = logging.getLogger("readdraw")
        try:
            logger.info("打开图片选择窗口")
            selected = await self.image_dialog.pick_file(self.image_picker)
            if not selected or self._closed:
                return
            # 系统对话框打开期间允许切换阅读页面，不能把图片插入错误的位置。
            if not self.book or (self.book.id, self.page_index) != (book_id, page_index):
                self.show_error("阅读页面已切换，请在目标页重新插入图片")
                return
            logger.info("图片选择完成，开始校验并保存附件")
            self.finish_drawing()
            attachment = self.store.add_attachment(book_id, page_index, selected)
            self.attachments = self.store.attachments(book_id, page_index)
            # 不重新渲染 PDF 或替换整个阅读区，减少原生选择框返回时的控件变更。
            self.drawing_view.set_attachments(self.attachments)
            self.set_tool("mouse")
            self.drawing_view._select_attachment(self.attachments[-1])
            self.status.value = "图片已插入：可拖动，点击图片上方的 − / + / 删除按钮编辑"
            self.status.color = "#217567"
            self.status.update()
            logger.info("图片插入完成：%s", attachment.id)
        except Exception as exc:
            logger.exception("插入图片失败")
            if not self._closed:
                self.show_error(f"无法插入图片：{exc}")
        finally:
            self._image_importing = False
            if not self._closed:
                self.image_btn.disabled = False
                self.image_btn.update()

    def import_book(self, path: str) -> None:
        try:
            doc = open_document(path)
            title = Path(path).stem
            book = next((b for b in self.books if os.path.abspath(b.path) == os.path.abspath(path)), None)
            if book is None:
                book = self.store.add_book(title, path, doc.page_count, Path(path).suffix.lower().lstrip("."))
                self.books = self.store.books()
            doc.close()
            self.open_book(book)
            self.status.value = f"已导入《{title}》"
            self.status.update()
        except Exception as exc:
            self.show_error(f"无法打开书籍：{exc}")

    def open_book(self, book: Book) -> None:
        try:
            self.finish_drawing()
            if self.document: self.document.close()
            self.document = open_document(book.path)
            self.book = book
            self.page_index = min(book.current_page, max(0, self.document.page_count - 1))
            self.load_page()
            self.refresh_library()
        except Exception as exc:
            self.show_error(f"无法打开书籍：{exc}")

    def load_page(self) -> None:
        if not self.document or not self.book: return
        self.finish_drawing()
        self.text_annotations = self.store.text_annotations(self.book.id, self.page_index)
        self.attachments = self.store.attachments(self.book.id, self.page_index)
        # 旧文字高亮仅保留为笔记，不再触发 PDF 原文搜索和重绘。
        self.base_image = render_page(self.document, self.page_index)
        self.strokes = self.store.get_strokes(self.book.id, self.page_index)
        self.history.clear()
        self.redo_stack.clear()
        self.drawing_view.set_page(self.base_image, self.attachments, self.strokes)
        self.canvas_host.content = self.drawing_view.control
        self.page_input.value = str(self.page_index + 1)
        self.page_label.value = f"第 {self.page_index + 1} / {self.document.page_count} 页"
        self.progress_text.value = f"阅读进度 {self.page_index + 1} / {self.document.page_count} 页\n{(self.page_index + 1) / self.document.page_count:.0%}"
        self.notes_text.value = f"{len(self.strokes)} 条绘画笔迹" if self.strokes else "当前页还没有绘画批注"
        self.refresh_annotations()
        self.prev_btn.disabled = self.page_index == 0
        self.next_btn.disabled = self.page_index >= self.document.page_count - 1
        self.status.value = f"正在阅读《{self.book.title}》"
        self.page.update()

    def update_canvas(self) -> None:
        """Refresh vector ink after undo/redo without touching the page image."""
        self.drawing_view.set_strokes(self.strokes)
        self.drawing_view.ink.update()

    async def start_stroke(self, event: Any) -> None:
        if self.tool == "mouse" or not self.book or self.base_image is None:
            return
        position = self.drawing_view.coords(event)
        if position is None:
            return
        self.finish_drawing()
        self.history.append(clone_strokes(self.strokes))
        self.redo_stack.clear()
        self.erasing = self.tool == "eraser"
        if self.erasing:
            self.erase_at(*position)
            return
        is_marker = self.tool == "marker"
        self.active_stroke = {
            "tool": self.tool,
            "color": self.marker_color if is_marker else self.color,
            "width": self.thickness * MARKER_WIDTH_MULTIPLIER if is_marker else self.thickness,
            "opacity": MARKER_OPACITY if is_marker else 1.0,
            "points": [list(position)],
        }
        if self.tool == "pen":
            device_pressure = getattr(event, "pressure", None)
            self._device_pressure_active = device_pressure is not None
            self.stroke_pressure = normalize_pressure(device_pressure)
            self.active_stroke["pressures"] = [self.stroke_pressure]
            self._pressure_pointer = self._pressure_position(event, position)
            self._pressure_sample_time = time.perf_counter()
        self.strokes.append(self.active_stroke)
        self.drawing_view.begin(self.active_stroke)

    async def update_stroke(self, event: Any) -> None:
        if not self.active_stroke and not self.erasing:
            return
        position = self.drawing_view.coords(event, clamp=True)
        if position is None:
            return
        if self.erasing:
            self.erase_at(*position)
        elif self.active_stroke is not None:
            if "pressures" in self.active_stroke and not self._device_pressure_active:
                self.stroke_pressure = self._estimate_mouse_pressure(event, position)
            self.active_stroke["points"].append(list(position))
            if "pressures" in self.active_stroke:
                self.active_stroke["pressures"].append(self.stroke_pressure)
            self.drawing_view.append(
                *position, pressure=self.stroke_pressure, stroke=self.active_stroke
            )

    def update_stroke_pressure(self, pressure: float) -> None:
        """接收真实压感设备的压力事件并更新当前笔迹。"""
        if self.active_stroke is None or "pressures" not in self.active_stroke:
            return
        self._device_pressure_active = True
        self.stroke_pressure = normalize_pressure(pressure)
        self.drawing_view.update_active_pressure(self.stroke_pressure)

    def _pressure_position(self, event: Any, fallback: tuple[float, float]) -> tuple[float, float]:
        """优先使用窗口坐标估算鼠标速度，避免缩放页面影响笔压。"""
        return self.drawing_view._pointer(event) or fallback

    def _estimate_mouse_pressure(self, event: Any, fallback: tuple[float, float]) -> float:
        """按鼠标速度估算压力，并平滑线宽变化以减少抖动。"""
        pointer = self._pressure_position(event, fallback)
        sample_time = time.perf_counter()
        if self._pressure_pointer is not None and self._pressure_sample_time is not None:
            elapsed = max(0.008, min(0.1, sample_time - self._pressure_sample_time))
            distance = math.dist(pointer, self._pressure_pointer)
            target = mouse_speed_pressure(distance / elapsed)
            self.stroke_pressure += (target - self.stroke_pressure) * 0.4
        self._pressure_pointer = pointer
        self._pressure_sample_time = sample_time
        return self.stroke_pressure

    def erase_at(self, x: float, y: float) -> None:
        radius = 16 / self.drawing_view.transform.scale
        remaining = [s for s in self.strokes if not point_near_stroke(s, x, y, radius)]
        if len(remaining) != len(self.strokes):
            self.strokes[:] = remaining
            self.update_canvas()

    def finish_drawing(self) -> None:
        """Commit a completed stroke or eraser gesture once, including on close."""
        if (self.active_stroke is not None or self.erasing) and self.book:
            self.store.save_strokes(self.book.id, self.page_index, self.strokes)
            self.notes_text.value = f"{len(self.strokes)} 条绘画笔迹"
        self.active_stroke = None
        self.erasing = False
        self._device_pressure_active = False
        self._pressure_pointer = None
        self._pressure_sample_time = None
        self.drawing_view.active_path = None

    async def end_stroke(self, _event: Any) -> None:
        self.finish_drawing()
        self.notes_text.update()

    def set_tool(self, tool: str) -> None:
        if tool not in ("mouse", "pen", "marker", "eraser"):
            return
        # 切换工具前提交笔迹，避免荧光笔与普通画笔共用尚未结束的手势。
        self.finish_drawing()
        self.tool = tool
        if tool != "mouse":
            self.drawing_view.clear_attachment_selection()
        if tool == "mouse" and self.drawing_view.zoom > 1.0:
            self.drawing_view.detector.mouse_cursor = ft.MouseCursor.GRAB
        else:
            self.drawing_view.detector.mouse_cursor = ft.MouseCursor.BASIC if tool == "mouse" else ft.MouseCursor.PRECISE
        self.mouse_btn.selected = tool == "mouse"
        self.pen_btn.selected = tool == "pen"
        self.marker_btn.selected = tool == "marker"
        self.eraser_btn.selected = tool == "eraser"
        self.thickness_slider.tooltip = "荧光笔粗细（普通画笔的 4 倍）" if tool == "marker" else "画笔粗细"
        self.status.value = {
            "mouse": "鼠标模式：可拖动图片，按住 Alt + 滚轮缩放",
            "marker": "荧光笔：按住鼠标在书页上涂画",
            "eraser": "橡皮擦",
            "pen": "画笔",
        }[tool]
        self.page.update()

    def on_attachment_move(self, _attachment: Any) -> None:
        """拖动过程中只更新图片控件，避免每一帧重绘书页。"""
        if self.status.value != "正在移动图片":
            self.status.value = "正在移动图片"
            self.status.update()

    def on_attachment_end(self, attachment: Any) -> None:
        """松开鼠标后一次性保存附件位置。"""
        if self.book:
            self.store.update_attachment_position(attachment.id, attachment.x, attachment.y)
            self.status.value = "图片位置已保存"
            self.status.update()

    def on_attachment_resize(self, attachment: Any) -> bool:
        """保存调整后的图片尺寸，重开书页后仍保持当前大小。"""
        try:
            self.store.update_attachment_size(attachment.id, attachment.width, attachment.height)
        except Exception as exc:
            logging.getLogger("readdraw").exception("保存图片尺寸失败")
            self.show_error(f"无法调整图片：{exc}")
            return False
        self.status.value = f"图片大小已调整为 {attachment.width} × {attachment.height}"
        self.status.update()
        return True

    def on_attachment_delete(self, attachment: Any) -> bool:
        """删除当前图片记录和文件；画布负责只刷新附件图层。"""
        try:
            self.store.delete_attachment(attachment.id)
        except Exception as exc:
            logging.getLogger("readdraw").exception("删除图片失败")
            self.show_error(f"无法删除图片：{exc}")
            return False
        self.attachments = [item for item in self.attachments if item.id != attachment.id]
        self.status.value = "图片已删除"
        self.status.update()
        return True

    def set_color(self, color: str) -> None:
        if self.tool == "marker":
            self.marker_color = color
        else:
            self.color = color
        self.set_tool("marker" if self.tool == "marker" else "pen")

    def change_thickness(self, e: Any) -> None:
        self.thickness = int(e.control.value)

    def go_page(self, delta: int) -> None:
        if self.document and 0 <= self.page_index + delta < self.document.page_count:
            self.finish_drawing()
            # 每次翻页都回到适合窗口的默认视图，避免新页面继承旧页的放大和偏移。
            self.drawing_view.reset_view(relayout=False)
            self.page_index += delta
            self.store.update_page(self.book.id, self.page_index)
            self.load_page()
            self.refresh_library()

    def jump_page(self, e: Any) -> None:
        if not self.document: return
        try:
            target = int(e.control.value) - 1
            if not 0 <= target < self.document.page_count: raise ValueError
            self.finish_drawing()
            self.drawing_view.reset_view(relayout=False)
            self.page_index = target
            self.store.update_page(self.book.id, target)
            self.load_page()
            self.refresh_library()
        except ValueError:
            self.page_input.value = str(self.page_index + 1)
            self.page_input.update()

    def undo(self, _=None) -> None:
        self.finish_drawing()
        if not self.history or not self.book: return
        self.redo_stack.append(clone_strokes(self.strokes))
        self.strokes = self.history.pop()
        self.store.save_strokes(self.book.id, self.page_index, self.strokes)
        self.update_canvas()
        self.page.update()

    def redo(self, _=None) -> None:
        self.finish_drawing()
        if not self.redo_stack or not self.book: return
        self.history.append(clone_strokes(self.strokes))
        self.strokes = self.redo_stack.pop()
        self.store.save_strokes(self.book.id, self.page_index, self.strokes)
        self.update_canvas()
        self.page.update()

    def refresh_annotations(self) -> None:
        self.annotation_list.controls.clear()
        if not self.text_annotations:
            self.annotation_list.controls.append(ft.Text("暂无文字标注", size=12, color="#98A2B3"))
            return
        for annotation in self.text_annotations:
            icon = ft.Icons.HIGHLIGHT_ROUNDED if annotation.kind == "highlight" else ft.Icons.EDIT_NOTE_ROUNDED
            label = annotation.quote if annotation.kind == "highlight" and annotation.quote else annotation.content
            self.annotation_list.controls.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                    bgcolor="#FFFBEB" if annotation.kind == "highlight" else "#F2F4F7",
                    border_radius=5,
                    content=ft.Row([ft.Icon(icon, size=16, color="#B54708"), ft.Text(label, size=11, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS, expand=True)], spacing=5),
                )
            )

    def open_note_editor(self, _=None) -> None:
        """在侧栏展开批注表单，避免调用不稳定的原生弹窗。"""
        if not self.book:
            self.show_error("请先打开一本书")
            return
        self.note_quote_field.value = ""
        self.note_content_field.value = ""
        self.note_editor.visible = True
        self.page.update()

    def open_text_dialog(self, event=None) -> None:
        """兼容工具栏旧回调，将文字批注统一交给侧栏表单。"""
        self.open_note_editor(event)

    def cancel_note(self, _=None) -> None:
        self.note_editor.visible = False
        self.note_quote_field.value = ""
        self.note_content_field.value = ""
        self.page.update()

    def save_text_annotation(self, _=None) -> None:
        """保存右侧表单内容；原文和想法至少填写一项。"""
        if not self.book:
            self.show_error("请先打开一本书")
            return
        quote = (self.note_quote_field.value or "").strip()
        content = (self.note_content_field.value or "").strip()
        if not content and not quote:
            self.show_error("请填写原文或笔记内容")
            return
        try:
            self.store.add_text_annotation(
                self.book.id, self.page_index, "note", content or quote, quote
            )
            self.note_editor.visible = False
            self.note_quote_field.value = ""
            self.note_content_field.value = ""
            self.load_page()
            self.status.value = "文字笔记已保存"
            self.status.color = "#217567"
            self.page.update()
        except Exception as exc:
            logging.getLogger("readdraw").exception("保存文字笔记失败")
            self.show_error(f"保存笔记失败：{exc}")

    def toggle_sync(self, _=None) -> None:
        if self.sync_server.running:
            self.sync_server.stop()
            self.status.value = "局域网同步服务已停止"
        else:
            self.sync_server.start()
            self.status.value = "同步服务已启动：本机 8765 端口"
        self.status.update()

    def export_png(self, _=None) -> None:
        if self.base_image is None or not self.book:
            self.show_error("请先导入并打开一本 PDF")
            return
        composite = compose_page(self.base_image, self.strokes, self.attachments)
        out = config.APP_DIR / f"{self.book.title}-第{self.page_index + 1}页.png"
        composite.save(out)
        self.status.value = f"已导出：{out}"
        self.status.update()

    def show_error(self, message: str) -> None:
        """Show errors in the persistent status bar without opening a native overlay."""
        logging.getLogger("readdraw").error(message)
        # 错误提示留在页面内，避免异常处理再次触发 Flutter 原生浮层。
        self.status.value = message
        self.status.color = "#B42318"
        self.status.update()

    def on_window_event(self, event: Any) -> None:
        if event.type == ft.WindowEventType.CLOSE and not getattr(self, "_closing", False):
            self._closing = True
            self.page.run_task(self._close_window)

    async def _close_window(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.image_dialog.close()
        logger = logging.getLogger("readdraw")
        try:
            self.finish_drawing()
        except Exception:
            logging.getLogger("readdraw").exception("关闭时保存笔迹失败")
        try:
            # 等待后台服务退出时不占用界面事件循环。
            await asyncio.to_thread(self.sync_server.stop)
        except Exception:
            logging.getLogger("readdraw").exception("停止局域网同步服务失败")
        finally:
            if self.document:
                try:
                    self.document.close()
                except Exception:
                    logger.exception("Close document failed")
                finally:
                    self.document = None
            try:
                self.store.close()
            except Exception:
                logger.exception("Close local database failed")
        try:
            # 允许窗口正常关闭，让 Flet 宿主收到退出信号并结束进程。
            self.page.window.prevent_close = False
            self.page.update()
            await self.page.window.close()
        except RuntimeError:
            # 原生窗口可能已先行关闭；此时页面会话也会随客户端退出。
            logging.getLogger("readdraw").info("Window client disconnected during shutdown")


async def main(page: ft.Page) -> None:
    # 将控制器绑定到页面生命周期，避免异步回调期间被垃圾回收。
    page.readdraw_app = ReadDrawApp(page)


if __name__ == "__main__":
    ft.run(main)
