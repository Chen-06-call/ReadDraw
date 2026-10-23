"""Drawing model helpers independent of Flet."""

from __future__ import annotations

import copy
import io
from typing import Any

from PIL import Image as PILImage
from PIL import ImageDraw
from PIL import ImageColor


MARKER_COLOR = "#FFEB3B"
MARKER_OPACITY = 0.32
MARKER_WIDTH_MULTIPLIER = 4


def stroke_rgba(stroke: dict[str, Any]) -> tuple[int, int, int, int]:
    """统一导出笔迹颜色，旧版未保存透明度的普通笔迹仍保持不透明。"""
    red, green, blue, alpha = ImageColor.getcolor(stroke.get("color", "#E45756"), "RGBA")
    opacity = max(0.0, min(1.0, float(stroke.get("opacity", 1.0))))
    return red, green, blue, round(alpha * opacity)


def clone_strokes(strokes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return copy.deepcopy(strokes)


def point_near_stroke(stroke: dict[str, Any], x: float, y: float, radius: float = 20) -> bool:
    points = stroke.get("points", [])
    if any((px - x) ** 2 + (py - y) ** 2 <= radius**2 for px, py in points):
        return True
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        if not length_squared:
            continue
        t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / length_squared))
        if (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2 <= radius**2:
            return True
    return False


def compose_page(base_image: PILImage.Image, strokes: list[dict[str, Any]], attachments: list[Any] | None = None) -> PILImage.Image:
    """Apply vector-like strokes to a page image for display or export."""
    composite = base_image.copy().convert("RGBA")
    for stroke in strokes:
        # 每条笔迹先画到独立透明图层再合成，让底下的正文仍然清晰可见。
        # 不直接给 RGBA 原图写入透明颜色，否则导出后会变成透明洞。
        layer = PILImage.new("RGBA", composite.size)
        draw = ImageDraw.Draw(layer)
        points = [(int(point[0]), int(point[1])) for point in stroke.get("points", [])]
        color = stroke_rgba(stroke)
        width = int(stroke.get("width", 4))
        if len(points) > 1:
            draw.line(points, fill=color, width=width, joint="curve")
        elif points:
            x, y = points[0]
            radius = max(1, width // 2)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        composite.alpha_composite(layer)
    for attachment in attachments or []:
        try:
            image = PILImage.open(attachment.path).convert("RGBA").resize(
                (max(1, attachment.width), max(1, attachment.height)),
                PILImage.Resampling.LANCZOS,
            )
            composite.alpha_composite(image, (attachment.x, attachment.y))
        except (OSError, ValueError):
            continue
    return composite


def image_data(image: PILImage.Image) -> bytes:
    """Encode PNG bytes for Flet's in-memory image source."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
