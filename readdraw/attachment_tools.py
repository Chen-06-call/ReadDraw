"""图片编辑工具条与尺寸规则，和数据库、阅读页面解耦。"""

import math
from typing import Callable

import flet as ft


def scaled_image_size(width: int, height: int, factor: float,
                      page_size: tuple[int, int],
                      position: tuple[float, float] = (0, 0)) -> tuple[int, int]:
    """以同一个比例限制长宽，防止触及页面边界时图片被压扁。"""
    if width <= 0 or height <= 0 or not math.isfinite(factor) or factor <= 0:
        raise ValueError("图片尺寸和缩放比例必须为正数")
    minimum = min(1.0, 10 / min(width, height))
    remaining_width = max(1.0, page_size[0] - position[0])
    remaining_height = max(1.0, page_size[1] - position[1])
    maximum = max(minimum, min(remaining_width / width, remaining_height / height))
    scale = max(minimum, min(maximum, factor))
    return max(1, round(width * scale)), max(1, round(height * scale))


def image_toolbar(on_delete: Callable[[], None]) -> ft.Container:
    """选中图片时只显示删除操作，尺寸通过图片角点拖动调整。"""
    button = ft.IconButton(
        ft.Icons.DELETE_OUTLINE, tooltip="删除图片",
        on_click=lambda event: on_delete(), icon_size=18,
        width=36, height=34, icon_color="#B42318",
    )
    return ft.Container(
        content=button, width=36, height=36,
        bgcolor="#FFFFFF", border=ft.Border.all(1, "#D0D5DD"), border_radius=6,
    )
