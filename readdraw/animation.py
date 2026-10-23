"""可复用的页面转场参数。"""

import flet as ft


def page_slide_offset() -> ft.Animation:
    """为阅读页提供平滑的水平滑入动画。"""
    return ft.Animation(220, curve=ft.AnimationCurve.EASE_OUT_CUBIC)
