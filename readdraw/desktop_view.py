"""Desktop presentation: a quiet library, a bounded reader, and page notes.

Only control construction lives here. Document and persistence operations stay
in the application controller; drawing coordinates stay in canvas_view.py.
"""

import flet as ft

from .version import APP_TAG

ACCENT = "#217567"
INK = "#233C3A"
MUTED = "#7C8C88"
LINE = "#E4EBE7"
PAPER = "#FCFDFB"


def label(text, size=12, color=MUTED, **kwargs):
    return ft.Text(text, size=size, color=color, **kwargs)


def icon_button(icon, tooltip, callback, **kwargs):
    return ft.IconButton(icon, tooltip=tooltip, on_click=callback, icon_size=19,
                         icon_color=INK, width=36, height=36, **kwargs)


def empty_reader(app):
    return ft.Column(
        [
            ft.Container(ft.Icon(ft.Icons.AUTO_STORIES_ROUNDED, size=38, color=ACCENT),
                         bgcolor="#E3EFE7", padding=22, border_radius=24),
            label("留一点时间，给阅读与思考", 23, INK, weight=ft.FontWeight.W_600),
            label("打开 PDF / EPUB，随手记录你的灵感", 13),
            ft.Container(height=6),
            ft.FilledButton("打开文件", icon=ft.Icons.ADD_ROUNDED,
                            on_click=app.open_picker, height=42),
            label("选择本地 PDF / EPUB 文件即可", 11),
        ],
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=14,
    )


def build_toolbar(app):
    """Two bounded rows avoid Wrap + Expanded and unpredictable toolbar height."""
    app.prev_btn = icon_button(ft.Icons.CHEVRON_LEFT_ROUNDED, "上一页", lambda e: app.go_page(-1), disabled=True)
    app.next_btn = icon_button(ft.Icons.CHEVRON_RIGHT_ROUNDED, "下一页", lambda e: app.go_page(1), disabled=True)
    app.page_input = ft.TextField(value="", width=48, height=34, dense=True,
        content_padding=ft.Padding.all(6), text_size=12, text_align=ft.TextAlign.CENTER,
        on_submit=app.jump_page, border_color=LINE, border_radius=7)
    app.pen_btn = icon_button(ft.Icons.DRAW_OUTLINED, "画笔", lambda e: app.set_tool("pen"), selected=True)
    app.mouse_btn = icon_button(ft.Icons.PAN_TOOL_OUTLINED, "鼠标", lambda e: app.set_tool("mouse"))
    app.eraser_btn = icon_button(ft.Icons.CLEANING_SERVICES_OUTLINED, "橡皮擦", lambda e: app.set_tool("eraser"))
    app.marker_btn = icon_button(ft.Icons.HIGHLIGHT_ROUNDED, "荧光笔", lambda e: app.set_tool("marker"))
    app.note_btn = icon_button(ft.Icons.EDIT_NOTE_ROUNDED, "文字批注", app.open_text_dialog)
    app.image_btn = icon_button(ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED, "插入图片", app.open_image_picker)
    app.sync_btn = icon_button(ft.Icons.LAN_OUTLINED, "局域网同步", app.toggle_sync)
    app.thickness_slider = ft.Slider(min=2, max=16, divisions=7, value=4, width=94,
        active_color=ACCENT, on_change=app.change_thickness, tooltip="画笔粗细")
    tools = ft.Row([
        app.mouse_btn, app.pen_btn, app.eraser_btn, app.marker_btn, app.note_btn, app.image_btn,
        ft.VerticalDivider(width=12, color=LINE),
        ft.Row([app.color_button(c) for c in ("#FFEB3B", "#E45756", "#3857D6", "#12B76A", "#F79009", "#101828")], spacing=3),
        app.thickness_slider,
        ft.Container(expand=True),
        icon_button(ft.Icons.UNDO_ROUNDED, "撤销", app.undo),
        icon_button(ft.Icons.REDO_ROUNDED, "恢复", app.redo),
    ], spacing=1)
    navigation = ft.Row([
        app.prev_btn, app.page_input, app.next_btn, app.page_label,
        ft.Container(expand=True),
        icon_button(ft.Icons.FIT_SCREEN_OUTLINED, "适合窗口", app.fit_page),
        icon_button(ft.Icons.DOWNLOAD_OUTLINED, "导出本页 PNG", app.export_png), app.sync_btn,
    ], spacing=4)
    return ft.Container(
        content=ft.Column([navigation, ft.Divider(height=1, color=LINE), tools], spacing=3),
        bgcolor="#FFFFFF", padding=ft.Padding.symmetric(horizontal=12, vertical=6),
        border=ft.Border.only(bottom=ft.BorderSide(1, LINE)), height=91,
    )


def build_desktop(app):
    page = app.page
    page.title = f"ReadDraw {APP_TAG} · 阅读与绘画笔记"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=ACCENT, font_family="Microsoft YaHei")
    page.bgcolor = PAPER
    page.padding = 0
    page.spacing = 0
    page.window.width = 1440
    page.window.height = 960
    page.window.min_width = 1180
    page.window.min_height = 740
    page.window.prevent_close = True
    page.window.on_event = app.on_window_event
    page.on_keyboard_event = app.on_keyboard_event
    page.on_error = app.on_page_error
    for picker in (app.file_picker, app.image_picker, app.directory_picker):
        page.services.append(picker)

    app.book_title = label("阅读，让灵感留下来", 17, INK, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS, weight=ft.FontWeight.W_600)
    app.book_subtitle = label("你的本地书库与绘画笔记", 11)
    app.header = ft.Container(
        bgcolor=PAPER, height=76, padding=ft.Padding.symmetric(horizontal=24),
        border=ft.Border.only(bottom=ft.BorderSide(1, LINE)),
        content=ft.Row([
            ft.Container(ft.Icon(ft.Icons.AUTO_STORIES_ROUNDED, color="#FFFFFF", size=22),
                         bgcolor=ACCENT, padding=10, border_radius=12),
            ft.Column([label("ReadDraw", 18, INK, weight=ft.FontWeight.W_700), label("READ · DRAW · REMEMBER", 9)], spacing=1, width=156,
                      alignment=ft.MainAxisAlignment.CENTER),
            ft.VerticalDivider(width=16, color=LINE),
            ft.Column([app.book_title, app.book_subtitle], spacing=3, expand=True,
                      alignment=ft.MainAxisAlignment.CENTER),
            icon_button(ft.Icons.SPACE_DASHBOARD_OUTLINED, "显示 / 隐藏书库", app.toggle_library),
            icon_button(ft.Icons.VIEW_SIDEBAR_OUTLINED, "显示 / 隐藏笔记", app.toggle_notes),
            icon_button(ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED, "检查更新", app.check_updates),
            icon_button(ft.Icons.SETTINGS_OUTLINED, "设置", app.open_settings),
            ft.FilledButton("打开文件", icon=ft.Icons.FOLDER_OPEN_OUTLINED,
                            height=38, on_click=app.open_picker),
        ], spacing=10),
    )

    app.library_list = ft.ListView(expand=True, spacing=7)
    app.library_count = label("0 本", 11)
    app.refresh_library()
    app.library_panel = ft.Container(
        width=214, bgcolor=PAPER, padding=ft.Padding.symmetric(horizontal=16, vertical=22),
        border=ft.Border.only(right=ft.BorderSide(1, LINE)),
        content=ft.Column([
            ft.Row([label("我的书库", 14, INK, weight=ft.FontWeight.W_600), ft.Container(expand=True), app.library_count]),
            label("继续上一次的阅读", 11), ft.Container(height=8), app.library_list,
            ft.Divider(color=LINE),
            label("离线可用 · 自动保存", 10), label(APP_TAG, 10),
        ], spacing=9, expand=True),
    )

    app.progress_text = label("打开书籍后记录阅读进度", 12, INK)
    app.progress_bar = ft.ProgressBar(value=0, height=4, color=ACCENT, bgcolor=LINE, border_radius=2)
    app.notes_text = label("在页面留下第一条笔记", 11)
    app.annotation_list = ft.ListView(expand=True, spacing=8)
    app.note_quote_field = ft.TextField(
        label="原文或选段（可选）", multiline=True, min_lines=2, max_lines=3,
        border_radius=6,
    )
    app.note_content_field = ft.TextField(
        label="笔记内容", multiline=True, min_lines=3, max_lines=5,
        border_radius=6,
    )
    app.note_editor = ft.Container(
        visible=False,
        content=ft.Column([
            app.note_quote_field,
            app.note_content_field,
            ft.Row([
                ft.TextButton("取消", on_click=app.cancel_note),
                ft.FilledButton("保存笔记", icon=ft.Icons.SAVE_OUTLINED, on_click=app.save_text_annotation),
            ], alignment=ft.MainAxisAlignment.END),
        ], spacing=8),
    )
    app.notes_panel = ft.Container(
        width=258, bgcolor=PAPER, padding=ft.Padding.all(20),
        border=ft.Border.only(left=ft.BorderSide(1, LINE)),
        content=ft.Column([
            ft.Row([ft.Icon(ft.Icons.STICKY_NOTE_2_OUTLINED, color=ACCENT, size=18),
                    label("阅读笔记", 14, INK, weight=ft.FontWeight.W_600)], spacing=8),
            ft.Container(height=5), app.progress_text, app.progress_bar,
            ft.Divider(height=28, color=LINE),
            label("本页批注", 12, INK, weight=ft.FontWeight.W_600), app.notes_text,
            ft.Row([ft.TextButton("荧光笔", icon=ft.Icons.HIGHLIGHT_ROUNDED, on_click=lambda e: app.set_tool("marker")),
                    ft.TextButton("文字", icon=ft.Icons.EDIT_NOTE_ROUNDED, on_click=app.open_note_editor)], spacing=0),
            app.note_editor,
            app.annotation_list,
            ft.Divider(color=LINE), label("数据保存位置", 10), app.data_path_text,
        ], spacing=10, expand=True),
    )
    app.toolbar = build_toolbar(app)
    app.canvas_host.content = empty_reader(app)
    app.canvas_host.bgcolor = app.background_color
    app.canvas_host.on_size_change = app.drawing_view.resize
    app.canvas_host.border_radius = 0
    app.canvas_host.alignment = ft.Alignment.CENTER
    app.canvas_host.clip_behavior = ft.ClipBehavior.HARD_EDGE
    center = ft.Container(
        expand=True,
        content=ft.Column([
            app.toolbar,
            app.canvas_host,
            ft.Container(ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED, color=ACCENT, size=13),
                                app.status], spacing=6),
                         height=30, padding=ft.Padding.symmetric(horizontal=16), bgcolor=PAPER),
        ], expand=True, spacing=0),
    )
    page.add(ft.Column([app.header, ft.Row([app.library_panel, center, app.notes_panel], expand=True, spacing=0)],
                       expand=True, spacing=0))
