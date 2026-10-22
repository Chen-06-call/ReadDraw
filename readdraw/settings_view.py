"""Build the settings panel; application callbacks own persistence and migration."""

from collections.abc import Awaitable, Callable

import flet as ft

from . import config


def create_settings_dialog(
    background: str,
    path_label: ft.Text,
    change_background: Callable[[str], bool],
    choose_data_dir: Callable[..., Awaitable[None]],
    close: Callable,
) -> ft.AlertDialog:
    """Create fresh controls on each open, with the current saved preferences."""
    def select_background(event) -> None:
        if not change_background(event.control.value):
            event.control.value = config.get_setting("background", config.DEFAULT_BACKGROUND)
            event.control.update()

    return ft.AlertDialog(
        modal=True,
        title=ft.Text("设置"),
        content=ft.Column(
            [
                ft.Dropdown(
                    label="阅读区背景",
                    value=background,
                    options=[
                        ft.DropdownOption(key=color, text=label)
                        for label, color in config.BACKGROUND_OPTIONS.items()
                    ],
                    on_select=select_background,
                    width=400,
                ),
                ft.Divider(height=24, color="#EAECF0"),
                ft.Text("数据保存位置", weight=ft.FontWeight.W_600),
                path_label,
                ft.Text("请选择空文件夹。数据库和附件将复制到新位置，原目录保留。", size=12, color="#667085"),
                ft.OutlinedButton(
                    "修改数据保存位置", icon=ft.Icons.FOLDER_SPECIAL_ROUNDED,
                    on_click=choose_data_dir,
                ),
            ],
            tight=True,
            width=420,
            spacing=12,
        ),
        scrollable=True,
        actions=[ft.TextButton("关闭", on_click=close)],
    )
