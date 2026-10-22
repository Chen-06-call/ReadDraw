"""ReadDraw: a small local PDF reader with page drawing annotations."""

from __future__ import annotations

import os
import asyncio
import logging
from pathlib import Path
from typing import Any

from readdraw import config
from readdraw.diagnostics import configure_logging

# Start native crash capture before importing any third-party DLLs. A windowed
# build has no console, so crashes during imports would otherwise be invisible.
if __name__ == "__main__":
    configure_logging()

import flet as ft
from PIL import Image as PILImage
from readdraw.data_location import migrate_data_dir
from readdraw.canvas_view import ReadingCanvas
from readdraw.drawing import clone_strokes, compose_page, point_near_stroke
from readdraw.models import Book
from readdraw.reader import open_document, render_page
from readdraw.settings_view import create_settings_dialog
from readdraw.desktop_view import build_desktop
from readdraw.storage import Store
from readdraw.sync_server import SyncServer
from readdraw.updater import ReleaseInfo, check_latest_release, download_update, is_packaged, schedule_windows_replace
from readdraw.version import APP_TAG, APP_VERSION
from readdraw.window_drop import NativeDropBridge


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
        self.thickness = 4
        self._closed = False
        self._closing = False
        configured_background = config.get_setting("background", config.DEFAULT_BACKGROUND)
        self.background_color = configured_background if configured_background in config.BACKGROUND_OPTIONS.values() else config.DEFAULT_BACKGROUND
        self.drawing_view = ReadingCanvas(self.start_stroke, self.update_stroke, self.end_stroke)
        self.erasing = False
        self.directory_picker = ft.FilePicker()
        self.data_path_text = ft.Text(str(config.APP_DIR), size=10, color="#667085", selectable=True)
        self.settings_path_text = ft.Text(str(config.APP_DIR), size=12, color="#667085", selectable=True)
        self.canvas_host = ft.Container(expand=True, alignment=ft.Alignment.CENTER, bgcolor=self.background_color, border_radius=8,
            content=ft.Column([ft.Icon(ft.Icons.MENU_BOOK_ROUNDED, size=54, color="#8B95A5"),
                ft.Text("打开或拖入 PDF / EPUB 开始阅读", size=20, weight=ft.FontWeight.W_600, color="#344054"),
                ft.Text("支持点击下方按钮选择文件，也可以把文件直接拖到阅读区域", color="#667085"),
                ft.FilledButton("打开文件", icon=ft.Icons.FOLDER_OPEN_ROUNDED, on_click=self.open_picker, height=42)],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=10))
        self.status = ft.Text("准备就绪", size=12, color="#667085")
        self.page_label = ft.Text("未打开书籍", size=13, color="#475467")
        self.file_picker = ft.FilePicker()
        self.image_picker = ft.FilePicker()
        self.sync_server = SyncServer()
        self.pending_release: ReleaseInfo | None = None
        self.file_drop = NativeDropBridge(self.on_files_dropped)
        self.build()
        self.file_drop.start()

    def build(self) -> None:
        build_desktop(self)

    def toggle_library(self, _=None) -> None:
        self.library_panel.visible = not self.library_panel.visible
        self.page.update()

    def toggle_notes(self, _=None) -> None:
        self.notes_panel.visible = not self.notes_panel.visible
        self.page.update()

    def fit_page(self, _=None) -> None:
        self.drawing_view.layout()
        self.page.update()

    def on_page_error(self, event: Any) -> None:
        logging.getLogger("readdraw").error("Client event error: %s", getattr(event, "data", event))

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

    def on_files_dropped(self, paths: list[str]) -> None:
        """Import the first supported document dropped from Windows Explorer."""
        if paths:
            self.page.run_task(self._import_dropped_file, paths[0])

    async def _import_dropped_file(self, path: str) -> None:
        self.import_book(path)

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
        if not self.book:
            self.show_error("请先打开一本书")
            return
        files = await self.image_picker.pick_files(
            dialog_title="选择要插入的图片",
            allow_multiple=False,
            file_type=ft.FilePickerFileType.IMAGE,
        )
        if files and files[0].path:
            self.store.add_attachment(self.book.id, self.page_index, files[0].path)
            self.load_page()

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
        quotes = [item.quote for item in self.text_annotations if item.kind == "highlight" and item.quote]
        self.base_image = render_page(self.document, self.page_index, quotes)
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
        if not self.book or self.base_image is None:
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
        self.active_stroke = {"color": self.color, "width": self.thickness, "points": [list(position)]}
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
            self.active_stroke["points"].append(list(position))
            self.drawing_view.append(*position)

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
        self.drawing_view.active_path = None

    async def end_stroke(self, _event: Any) -> None:
        self.finish_drawing()
        self.notes_text.update()

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self.pen_btn.selected = tool == "pen"
        self.eraser_btn.selected = tool == "eraser"
        self.pen_btn.update()
        self.eraser_btn.update()

    def set_color(self, color: str) -> None:
        self.color = color
        self.set_tool("pen")

    def change_thickness(self, e: Any) -> None:
        self.thickness = int(e.control.value)

    def go_page(self, delta: int) -> None:
        if self.document and 0 <= self.page_index + delta < self.document.page_count:
            self.finish_drawing()
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

    def open_text_dialog(self, kind: str) -> None:
        if not self.book:
            self.show_error("请先打开一本书")
            return
        quote_field = ft.TextField(label="原文或选段", hint_text="用于定位高亮，可留空", multiline=True, min_lines=2, max_lines=4)
        content_field = ft.TextField(label="批注内容", hint_text="写下你的想法", multiline=True, min_lines=3, max_lines=6)
        title = "添加文字高亮" if kind == "highlight" else "添加文字批注"

        def save_annotation(_=None) -> None:
            quote = quote_field.value.strip()
            content = content_field.value.strip() or quote
            if not content:
                self.show_error("请输入内容")
                return
            self.store.add_text_annotation(self.book.id, self.page_index, kind, content, quote)
            self.page.pop_dialog()
            self.load_page()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Column([quote_field, content_field], tight=True, width=460),
            actions=[ft.TextButton("取消", on_click=lambda e: self.page.pop_dialog()), ft.FilledButton("保存", on_click=save_annotation)],
        )
        self.page.show_dialog(dialog)

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
        logging.getLogger("readdraw").error(message)
        self.page.show_dialog(ft.SnackBar(content=ft.Text(message), bgcolor="#B42318"))

    def on_window_event(self, event: Any) -> None:
        if event.type == ft.WindowEventType.CLOSE and not getattr(self, "_closing", False):
            self._closing = True
            self.page.run_task(self._close_window)

    async def _close_window(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.finish_drawing()
        self.file_drop.stop()
        self.sync_server.stop()
        if self.document:
            self.document.close()
            self.document = None
        self.store.close()
        try:
            await self.page.window.destroy()
        except RuntimeError:
            # The Flet client may already have disconnected during shutdown.
            logging.getLogger("readdraw").info("Window client disconnected during shutdown")


async def main(page: ft.Page) -> None:
    ReadDrawApp(page)


if __name__ == "__main__":
    ft.run(main)
