"""可复用的页面转场参数。"""

import flet as ft


DEFAULT_PAGE_ANIMATION = "slide"
PAGE_ANIMATION_OPTIONS = {
    "slide": "水平滑入",
    "fade": "柔和淡入",
    "scale": "轻微缩放",
}


def page_animation() -> ft.Animation:
    """三种动画共用时长与缓动曲线。"""
    return ft.Animation(220, curve=ft.AnimationCurve.EASE_OUT_CUBIC)


def configure_page_animation(control, enabled: bool, kind: str) -> None:
    """将选定的隐式动画绑定到画布容器，并清除未使用的效果。"""
    if kind not in PAGE_ANIMATION_OPTIONS:
        kind = DEFAULT_PAGE_ANIMATION
    animation = page_animation() if enabled else None
    control.animate_offset = animation if enabled and kind == "slide" else None
    control.animate_opacity = animation if enabled and kind == "fade" else None
    control.animate_scale = animation if enabled and kind == "scale" else None
    control.offset = (0, 0)
    control.opacity = 1
    control.scale = 1
