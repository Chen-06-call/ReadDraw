"""Build the settings panel; application callbacks own persistence and migration."""

from collections.abc import Awaitable, Callable

import flet as ft

from . import config
from .animation import DEFAULT_PAGE_ANIMATION, PAGE_ANIMATION_OPTIONS


def create_settings_dialog(
    background: str,
    path_label: ft.Text,
    change_background: Callable[[str], bool],
    choose_data_dir: Callable[..., Awaitable[None]],
    change_page_animation: Callable[[bool, str], bool],
    close: Callable,
    page_animation_enabled: bool = config.DEFAULT_PAGE_ANIMATION_ENABLED,
    page_animation_type: str = DEFAULT_PAGE_ANIMATION,
    check_updates: Callable[..., Awaitable[None]] | None = None,
    change_auto_save: Callable[[bool], bool] | None = None,
    auto_save_enabled: bool = config.DEFAULT_AUTO_SAVE_ENABLED,
) -> ft.AlertDialog:
    """Create fresh controls on each open, with the current saved preferences."""
    def select_background(event) -> None:
        if not change_background(event.control.value):
            event.control.value = config.get_setting("background", config.DEFAULT_BACKGROUND)
            event.control.update()

    def select_page_animation(event) -> None:
        nonlocal page_animation_type
        enabled = bool(animation_switch.value)
        if not change_page_animation(enabled, event.control.value):
            event.control.value = page_animation_type
            event.control.update()
        else:
            page_animation_type = event.control.value

    def toggle_page_animation(event) -> None:
        nonlocal page_animation_enabled
        selected = animation_type.value or page_animation_type
        enabled = bool(event.control.value)
        if not change_page_animation(enabled, selected):
            event.control.value = page_animation_enabled
            event.control.update()
            return
        page_animation_enabled = enabled
        animation_type.disabled = not enabled
        animation_type.update()

    animation_switch = ft.Switch(
        label="启用翻页动画",
        value=page_animation_enabled,
        on_change=toggle_page_animation,
    )
    animation_type = ft.Dropdown(
        label="翻页动画类型",
        value=page_animation_type if page_animation_type in PAGE_ANIMATION_OPTIONS else DEFAULT_PAGE_ANIMATION,
        options=[
            ft.DropdownOption(key=key, text=label)
            for key, label in PAGE_ANIMATION_OPTIONS.items()
        ],
        on_select=select_page_animation,
        width=400,
        disabled=not page_animation_enabled,
    )

    def toggle_auto_save(event) -> None:
        nonlocal auto_save_enabled
        enabled = bool(event.control.value)
        if change_auto_save is None or change_auto_save(enabled):
            auto_save_enabled = enabled
            return
        event.control.value = auto_save_enabled
        event.control.update()

    auto_save_switch = ft.Switch(
        label="自动保存绘画和工作位置",
        value=auto_save_enabled,
        on_change=toggle_auto_save,
    )

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
                animation_switch,
                animation_type,
                ft.Divider(height=24, color="#EAECF0"),
                auto_save_switch,
                ft.Text("关闭后仍可使用绘画区的“保存当前工作”按钮。", size=12, color="#667085"),
                ft.Divider(height=24, color="#EAECF0"),
                ft.OutlinedButton(
                    "检查更新", icon=ft.Icons.SYSTEM_UPDATE_ALT_ROUNDED,
                    on_click=check_updates,
                    disabled=check_updates is None,
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
