"""书签目录的展示控件；保存和跳页逻辑交给调用方。"""

from collections.abc import Callable

import flet as ft


def bookmark_entries(bookmarks: list[dict], current_page: int,
                     on_select: Callable[[int], None],
                     on_delete: Callable[[int], None]) -> list[ft.Control]:
    """生成按页码排列的目录，突出显示当前页。"""
    if not bookmarks:
        return [ft.Text("暂无书签，点击工具栏书签图标添加", size=11, color="#98A2B3")]
    return [
        ft.Row([
            ft.Container(
                expand=True, padding=8, border_radius=6,
                bgcolor="#E3EFE7" if bookmark["page"] == current_page else None,
                tooltip=f"跳转到第 {bookmark['page'] + 1} 页",
                data=bookmark["page"],
                on_click=lambda event, target=bookmark["page"]: on_select(target),
                content=ft.Row([
                    ft.Icon(ft.Icons.BOOKMARK, size=16, color="#217567"),
                    ft.Column([
                        ft.Text(f"第 {bookmark['page'] + 1} 页", size=12, color="#233C3A"),
                        ft.Text(bookmark.get("note", ""), size=10, color="#7C8C88",
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                visible=bool(bookmark.get("note"))),
                    ], spacing=1, expand=True),
                ], spacing=8),
            ),
            ft.IconButton(
                ft.Icons.DELETE_OUTLINE_ROUNDED,
                tooltip=f"删除第 {bookmark['page'] + 1} 页书签",
                icon_size=17,
                on_click=lambda event, target=bookmark["page"]: on_delete(target),
            ),
        ], spacing=0)
        for bookmark in bookmarks
    ]
