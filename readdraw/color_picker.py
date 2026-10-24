"""可复用的圆形色盘：拖动选色、调节明暗，也可输入十六进制颜色。"""

from __future__ import annotations

import colorsys
import io
import math
import re
from functools import lru_cache
from typing import Callable

import flet as ft
from PIL import Image, ImageDraw, ImageEnhance


WHEEL_SIZE = 240
WHEEL_RADIUS = WHEEL_SIZE / 2 - 8


def normalize_hex_color(value: str) -> str:
    """只接受六位 RGB 颜色，确保画布显示与草稿保存使用同一格式。"""
    color = value.strip().upper()
    if not color.startswith("#"):
        color = "#" + color
    if re.fullmatch(r"#[0-9A-F]{6}", color) is None:
        raise ValueError("请输入六位颜色代码，例如 #217567")
    return color


@lru_cache(maxsize=1)
def _wheel_image() -> Image.Image:
    """色相和饱和度的底图只生成一次，拖动时仅调节亮度与选中位置。"""
    image = Image.new("RGBA", (WHEEL_SIZE, WHEEL_SIZE))
    pixels = image.load()
    center = WHEEL_SIZE / 2
    for y in range(WHEEL_SIZE):
        for x in range(WHEEL_SIZE):
            dx, dy = x - center, y - center
            saturation = math.hypot(dx, dy) / WHEEL_RADIUS
            if saturation <= 1:
                hue = (math.atan2(dy, dx) / math.tau) % 1
                rgb = colorsys.hsv_to_rgb(hue, saturation, 1)
                pixels[x, y] = (*[round(channel * 255) for channel in rgb], 255)
    return image


class ColorPicker:
    """把选色状态与对话框封装在一起，确定后才修改外部画笔颜色。"""

    def __init__(self, color: str, on_apply: Callable[[str], None], on_close: Callable[[], None]) -> None:
        self.on_apply = on_apply
        self.on_close = on_close
        self.hue = 0.0
        self.saturation = 0.0
        self.value = 1.0
        self._set_color(color)
        self.wheel = ft.Image(src=b"", width=WHEEL_SIZE, height=WHEEL_SIZE,
                              fit=ft.BoxFit.FILL, gapless_playback=True)
        self.detector = ft.GestureDetector(
            content=self.wheel, width=WHEEL_SIZE, height=WHEEL_SIZE,
            mouse_cursor=ft.MouseCursor.PRECISE, drag_interval=16,
            on_pan_down=self._pick_color, on_pan_update=self._pick_color,
        )
        self.preview = ft.Container(width=40, height=40, border_radius=8,
                                    border=ft.Border.all(1, "#D0D5DD"))
        self.hex_field = ft.TextField(label="颜色代码", value=color, width=180,
                                      on_submit=self._submit_hex)
        self.brightness = ft.Slider(min=0, max=1, value=self.value,
                                     on_change=self._change_brightness, width=WHEEL_SIZE,
                                     tooltip="明暗：左侧为黑色，右侧为原色")
        self.dialog = ft.AlertDialog(
            modal=True, title=ft.Text("画笔色盘"),
            content=ft.Column([
                self.detector,
                ft.Text("明暗", size=12, color="#667085"),
                self.brightness,
                ft.Row([self.preview, self.hex_field], spacing=12),
                ft.Text("拖动色盘选色，调节滑杆改变明暗", size=12, color="#667085"),
            ], width=280, height=435, tight=True, scroll=ft.ScrollMode.AUTO,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            actions=[ft.TextButton("取消", on_click=lambda e: self.on_close()),
                     ft.FilledButton("使用此颜色", on_click=self._apply)],
        )
        self._refresh()

    @property
    def color(self) -> str:
        rgb = colorsys.hsv_to_rgb(self.hue, self.saturation, self.value)
        return "#" + "".join(f"{round(channel * 255):02X}" for channel in rgb)

    def _set_color(self, color: str) -> None:
        color = normalize_hex_color(color)
        rgb = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        self.hue, self.saturation, self.value = colorsys.rgb_to_hsv(*rgb)

    def _refresh(self) -> None:
        """预览、滑杆、颜色代码和选中标记始终由同一份 HSV 状态生成。"""
        image = ImageEnhance.Brightness(_wheel_image()).enhance(self.value)
        distance = self.saturation * WHEEL_RADIUS
        x = WHEEL_SIZE / 2 + math.cos(self.hue * math.tau) * distance
        y = WHEEL_SIZE / 2 + math.sin(self.hue * math.tau) * distance
        draw = ImageDraw.Draw(image)
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), outline="black", width=3)
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), outline="white", width=2)
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        self.wheel.src = stream.getvalue()
        self.preview.bgcolor = self.color
        self.hex_field.value = self.color
        self.hex_field.error_text = None
        self.brightness.value = self.value
        try:
            self.dialog.update()
        except RuntimeError:
            # 对话框首次创建时尚未挂载，只需准备好控件状态。
            pass

    async def _pick_color(self, event) -> None:
        """点击与拖动使用同一个坐标系；超出圆周时停在最近的边缘。"""
        position = event.local_position
        dx, dy = float(position.x) - WHEEL_SIZE / 2, float(position.y) - WHEEL_SIZE / 2
        self.hue = (math.atan2(dy, dx) / math.tau) % 1
        self.saturation = min(1.0, math.hypot(dx, dy) / WHEEL_RADIUS)
        self._refresh()

    def _change_brightness(self, event) -> None:
        self.value = max(0.0, min(1.0, float(event.control.value)))
        self._refresh()

    def _read_hex(self) -> bool:
        try:
            self._set_color(self.hex_field.value or "")
        except ValueError as exc:
            self.hex_field.error_text = str(exc)
            self.dialog.update()
            return False
        self._refresh()
        return True

    def _submit_hex(self, _event=None) -> None:
        self._read_hex()

    def _apply(self, _event=None) -> None:
        if self._read_hex():
            self.on_apply(self.color)
            self.on_close()
