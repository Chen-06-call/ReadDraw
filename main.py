"""ReadDraw: a small local PDF reader with page drawing annotations."""

from __future__ import annotations

import os
import asyncio
from pathlib import Path
from typing import Any

import flet as ft
from PIL import Image as PILImage
from readdraw.config import APP_DIR
from readdraw.drawing import clone_strokes, compose_page, image_data, point_near_stroke
from readdraw.models import Book
from readdraw.reader import open_document, render_page
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
        self.thickness = 4
        self.image = ft.Image(src="", fit=ft.BoxFit.CONTAIN, border_radius=4)
        self.canvas_host = ft.Container(expand=True, alignment=ft.Alignment.CENTER, bgcolor="#E8ECF1", border_radius=8,
            content=ft.Column([ft.Icon(ft.Icons.MENU_BOOK_ROUNDED, size=54, color="#8B95A5"),
                ft.Text("导入一本 PDF 开始阅读", size=20, weight=ft.FontWeight.W_600, color="#344054"),
                ft.Text("你的阅读进度和页码绘画会自动保存在本机", color="#667085")],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=10))
        self.status = ft.Text("准备就绪", size=12, color="#667085")
        self.page_label = ft.Text("未打开书籍", size=13, color="#475467")
        self.file_picker = ft.FilePicker()
        self.image_picker = ft.FilePicker()
        self.sync_server = SyncServer()
        self.pending_release: ReleaseInfo | None = None
        self.build()

    def build(self) -> None:
        self.page.title = "ReadDraw · 阅读与绘画笔记"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.bgcolor = "#F6F8FA"
        self.page.padding = 0
        self.page.window.min_width = 980
        self.page.window.min_height = 680
        self.page.overlay.append(self.file_picker)
        self.page.overlay.append(self.image_picker)
        self.library_list = ft.ListView(expand=True, spacing=4, padding=ft.Padding.only(top=8))
        self.refresh_library()
        sidebar = ft.Container(width=264, padding=ft.Padding.all(18), bgcolor="#FFFFFF", border=ft.Border.only(right=ft.BorderSide(1, "#E4E7EC")),
            content=ft.Column([ft.Row([ft.Icon(ft.Icons.AUTO_STORIES_ROUNDED, color="#3857D6"), ft.Text("ReadDraw", size=21, weight=ft.FontWeight.W_700, color="#1D2939")], spacing=8),
                ft.Text("我的书库", size=12, color="#98A2B3", weight=ft.FontWeight.W_600),
                ft.FilledButton("导入书籍", icon=ft.Icons.UPLOAD_FILE_ROUNDED, on_click=self.open_picker, height=42),
                ft.OutlinedButton("检查更新", icon=ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED, on_click=self.check_updates),
                ft.Text(f"当前版本 {APP_TAG}", size=11, color="#98A2B3"), self.library_list,
                ft.Divider(height=1, color="#EAECF0"), ft.Text("第一版 · 本地模式", size=11, color="#98A2B3")], expand=True, spacing=12))
        self.toolbar = self.make_toolbar()
        self.progress_text = ft.Text("导入 PDF 后开始记录进度", size=13, color="#667085")
        self.notes_text = ft.Text("当前页还没有绘画批注", size=13, color="#98A2B3")
        self.annotation_list = ft.ListView(expand=True, spacing=6)
        right_panel = ft.Container(width=240, padding=ft.Padding.all(18), bgcolor="#FFFFFF", border=ft.Border.only(left=ft.BorderSide(1, "#E4E7EC")),
            content=ft.Column([ft.Text("阅读信息", size=15, weight=ft.FontWeight.W_600, color="#344054"), self.progress_text,
                ft.Divider(height=20, color="#EAECF0"), ft.Text("本页批注", size=15, weight=ft.FontWeight.W_600, color="#344054"), self.notes_text, self.annotation_list,
                ft.Container(expand=True), ft.Text("数据保存位置", size=11, color="#98A2B3"), ft.Text(str(APP_DIR), size=10, color="#667085", selectable=True)], expand=True, spacing=10))
        center = ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=22, vertical=16), content=ft.Column([self.toolbar, self.canvas_host, self.status], expand=True, spacing=12))
        self.page.add(ft.Row([sidebar, center, right_panel], expand=True, spacing=0))

    def make_toolbar(self) -> ft.Control:
        self.prev_btn = ft.IconButton(ft.Icons.CHEVRON_LEFT_ROUNDED, tooltip="上一页", on_click=lambda e: self.go_page(-1))
        self.next_btn = ft.IconButton(ft.Icons.CHEVRON_RIGHT_ROUNDED, tooltip="下一页", on_click=lambda e: self.go_page(1))
        self.page_input = ft.TextField(value="", width=62, height=38, text_align=ft.TextAlign.CENTER, dense=True, on_submit=self.jump_page)
        self.pen_btn = ft.IconButton(ft.Icons.DRAW_ROUNDED, tooltip="画笔", selected=True, on_click=lambda e: self.set_tool("pen"))
        self.eraser_btn = ft.IconButton(ft.Icons.CLEANING_SERVICES_ROUNDED, tooltip="橡皮擦", on_click=lambda e: self.set_tool("eraser"))
        self.highlight_btn = ft.IconButton(ft.Icons.HIGHLIGHT_ROUNDED, tooltip="添加文字高亮", on_click=lambda e: self.open_text_dialog("highlight"))
        self.note_btn = ft.IconButton(ft.Icons.EDIT_NOTE_ROUNDED, tooltip="添加文字批注", on_click=lambda e: self.open_text_dialog("note"))
        self.image_btn = ft.IconButton(ft.Icons.IMAGE_ROUNDED, tooltip="插入图片", on_click=self.open_image_picker)
        self.sync_btn = ft.IconButton(ft.Icons.LAN_ROUNDED, tooltip="启动局域网同步", on_click=self.toggle_sync)
        colors = ft.Row([self.color_button(c) for c in ["#E45756", "#3857D6", "#12B76A", "#F79009", "#101828"]], spacing=2)
        self.thickness_slider = ft.Slider(min=2, max=16, divisions=7, value=4, width=110, tooltip="线条粗细", on_change=self.change_thickness)
        return ft.Container(padding=ft.Padding.symmetric(horizontal=10, vertical=7), bgcolor="#FFFFFF", border_radius=8, border=ft.Border.all(1, "#E4E7EC"),
            content=ft.Row([self.prev_btn, self.page_label, self.page_input, self.next_btn, ft.VerticalDivider(width=16), self.pen_btn, self.eraser_btn, self.highlight_btn, self.note_btn, self.image_btn, colors,
                ft.Row([ft.Icon(ft.Icons.LINE_WEIGHT_ROUNDED, size=17, color="#667085"), self.thickness_slider], spacing=2), ft.Container(expand=True),
                ft.IconButton(ft.Icons.UNDO_ROUNDED, tooltip="撤销", on_click=self.undo), ft.IconButton(ft.Icons.REDO_ROUNDED, tooltip="恢复", on_click=self.redo),
                ft.IconButton(ft.Icons.DOWNLOAD_ROUNDED, tooltip="导出本页 PNG", on_click=self.export_png), self.sync_btn], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=4))

    def color_button(self, color: str) -> ft.Control:
        return ft.Container(width=23, height=23, bgcolor=color, border_radius=12, border=ft.Border.all(2, "#FFFFFF"), tooltip=f"颜色 {color}", on_click=lambda e, c=color: self.set_color(c))

    def refresh_library(self) -> None:
        self.library_list.controls.clear()
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
            self.page.window.close()
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
        self.text_annotations = self.store.text_annotations(self.book.id, self.page_index)
        self.attachments = self.store.attachments(self.book.id, self.page_index)
        quotes = [item.quote for item in self.text_annotations if item.kind == "highlight" and item.quote]
        self.base_image = render_page(self.document, self.page_index, quotes)
        self.strokes = self.store.get_strokes(self.book.id, self.page_index)
        self.history.clear()
        self.redo_stack.clear()
        self.update_canvas()
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
        if self.base_image is None: return
        composite = compose_page(self.base_image, self.strokes, self.attachments)
        self.image.src = image_data(composite)
        self.image.width = composite.width
        self.image.height = composite.height
        detector = ft.GestureDetector(content=self.image, mouse_cursor=ft.MouseCursor.PRECISE, on_pan_start=self.start_stroke, on_pan_update=self.update_stroke, on_pan_end=self.end_stroke)
        self.canvas_host.content = ft.Container(content=detector, padding=8, bgcolor="#D0D5DD", border_radius=8)

    def coords(self, event: Any) -> tuple[float, float]:
        position = getattr(event, "local_position", None)
        if position is not None:
            local_x, local_y = position.x, position.y
        else:
            local_x, local_y = event.local_x, event.local_y
        return max(0, float(local_x) - 8), max(0, float(local_y) - 8)

    def start_stroke(self, event: Any) -> None:
        if not self.book: return
        x, y = self.coords(event)
        if self.tool == "eraser":
            self.history.append(clone_strokes(self.strokes))
            self.strokes = [s for s in self.strokes if not point_near_stroke(s, x, y)]
            self.redo_stack.clear()
            self.update_canvas()
            self.page.update()
            return
        self.history.append(clone_strokes(self.strokes))
        self.redo_stack.clear()
        self.active_stroke = {"color": self.color, "width": self.thickness, "points": [[x, y]]}
        self.strokes.append(self.active_stroke)

    def update_stroke(self, event: Any) -> None:
        if not self.active_stroke: return
        x, y = self.coords(event)
        self.active_stroke["points"].append([x, y])
        self.update_canvas()
        self.page.update()

    def end_stroke(self, _event: Any) -> None:
        if self.active_stroke and self.book:
            self.store.save_strokes(self.book.id, self.page_index, self.strokes)
            self.notes_text.value = f"{len(self.strokes)} 条绘画笔迹"
            self.notes_text.update()
        self.active_stroke = None

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
            self.page_index += delta
            self.store.update_page(self.book.id, self.page_index)
            self.load_page()
            self.refresh_library()

    def jump_page(self, e: Any) -> None:
        if not self.document: return
        try:
            target = int(e.control.value) - 1
            if not 0 <= target < self.document.page_count: raise ValueError
            self.page_index = target
            self.store.update_page(self.book.id, target)
            self.load_page()
            self.refresh_library()
        except ValueError:
            self.page_input.value = str(self.page_index + 1)
            self.page_input.update()

    def undo(self, _=None) -> None:
        if not self.history or not self.book: return
        self.redo_stack.append(clone_strokes(self.strokes))
        self.strokes = self.history.pop()
        self.store.save_strokes(self.book.id, self.page_index, self.strokes)
        self.update_canvas()
        self.page.update()

    def redo(self, _=None) -> None:
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
        out = APP_DIR / f"{self.book.title}-第{self.page_index + 1}页.png"
        composite.save(out)
        self.status.value = f"已导出：{out}"
        self.status.update()

    def show_error(self, message: str) -> None:
        self.page.open(ft.SnackBar(content=ft.Text(message), bgcolor="#B42318"))


def main(page: ft.Page) -> None:
    ReadDrawApp(page)


if __name__ == "__main__":
    ft.run(main)
