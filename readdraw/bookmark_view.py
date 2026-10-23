"""书签目录的展示控件；保存和跳页逻辑交给调用方。"""

from collections.abc import Callable

import flet as ft


def bookmark_entries(pages: list[int], current_page: int,
                     on_select: Callable[[int], None]) -> list[ft.Control]:
    """生成按页码排列的目录，突出显示当前页。"""
    if not pages:
        return [ft.Text("暂无书签，点击工具栏书签图标添加", size=11, color="#98A2B3")]
    return [
        ft.Container(
            padding=8, border_radius=6,
            bgcolor="#E3EFE7" if page == current_page else None,
            tooltip=f"跳转到第 {page + 1} 页",
            data=page,
            on_click=lambda event, target=page: on_select(target),
            content=ft.Row([
                ft.Icon(ft.Icons.BOOKMARK, size=16, color="#217567"),
                ft.Text(f"第 {page + 1} 页", size=12, color="#233C3A"),
            ], spacing=8),
        )
        for page in pages
    ]
