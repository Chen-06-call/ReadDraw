"""Drawing model helpers independent of Flet."""

from __future__ import annotations

import copy
import io
import math
from typing import Any

from PIL import Image as PILImage
from PIL import ImageDraw
from PIL import ImageColor


MARKER_COLOR = "#FFEB3B"
# 荧光笔保持较低透明度，底层文字在长时间涂画后仍然清晰可见。
MARKER_OPACITY = 0.20
MARKER_WIDTH_MULTIPLIER = 4
SHAPE_TYPES = {
    "line": "直线",
    "wave": "波浪线",
    "circle": "圆形 / 椭圆",
    "rectangle": "方框",
    "arrow": "箭头",
    "triangle": "三角形",
    "diamond": "菱形",
    "rounded_rectangle": "圆角矩形",
    "pentagon": "五边形",
    "hexagon": "六边形",
    "star": "五角星",
    "heart": "爱心",
    "cross": "十字",
}
QUICK_COLORS = ("#FFEB3B", "#E45756", "#3857D6", "#12B76A", "#F79009", "#101828")


def _regular_polygon(cx: float, cy: float, radius_x: float, radius_y: float,
                     sides: int, rotation: float = -math.pi / 2) -> list[list[float]]:
    """生成闭合正多边形，供五边形、六边形和星形复用。"""
    points = [
        [cx + radius_x * math.cos(rotation + index * math.tau / sides),
         cy + radius_y * math.sin(rotation + index * math.tau / sides)]
        for index in range(sides)
    ]
    return points + [points[0]]


def shape_points(shape: str, start: tuple[float, float],
                 end: tuple[float, float], constrain: bool = False) -> list[list[float]]:
    """根据拖动边界生成可保存、可预览和可导出的形状点序列。"""
    x1, y1 = start
    x2, y2 = end
    if shape == "line":
        return [[x1, y1], [x2, y2]]

    if constrain and shape in {"circle", "rectangle"}:
        # Ctrl 将拖动矩形约束为等宽等高；起点仍固定在按下鼠标的位置。
        side = max(abs(x2 - x1), abs(y2 - y1))
        x2 = x1 + (side if x2 >= x1 else -side)
        y2 = y1 + (side if y2 >= y1 else -side)

    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    width, height = right - left, bottom - top
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    if shape in {"rectangle", "triangle", "diamond", "rounded_rectangle"}:
        if shape == "rectangle":
            points = [(left, top), (right, top), (right, bottom), (left, bottom)]
        elif shape == "rounded_rectangle":
            radius = min(width, height) * 0.2
            points = []
            for center_x, center_y, start_angle in (
                (right - radius, top + radius, -math.pi / 2),
                (right - radius, bottom - radius, 0),
                (left + radius, bottom - radius, math.pi / 2),
                (left + radius, top + radius, math.pi),
            ):
                points.extend(
                    (center_x + radius * math.cos(start_angle + step * math.pi / 2 / 8),
                     center_y + radius * math.sin(start_angle + step * math.pi / 2 / 8))
                    for step in range(9)
                )
        elif shape == "triangle":
            # 从上向下拖动绘制正三角形，反向拖动则将尖端翻到下方。
            if y2 >= y1:
                points = [((left + right) / 2, top), (right, bottom), (left, bottom)]
            else:
                points = [(left, top), (right, top), ((left + right) / 2, bottom)]
        else:
            points = [((left + right) / 2, top), (right, (top + bottom) / 2),
                      ((left + right) / 2, bottom), (left, (top + bottom) / 2)]
        points.append(points[0])
        return [[x, y] for x, y in points]

    if shape in {"pentagon", "hexagon", "star"}:
        radius_x, radius_y = width / 2, height / 2
        if shape == "star":
            points = []
            for index in range(10):
                radius = 1.0 if index % 2 == 0 else 0.42
                angle = -math.pi / 2 + index * math.tau / 10
                points.append([center_x + radius_x * radius * math.cos(angle),
                               center_y + radius_y * radius * math.sin(angle)])
            return points + [points[0]]
        sides = 5 if shape == "pentagon" else 6
        return _regular_polygon(center_x, center_y, radius_x, radius_y, sides)

    if shape == "heart":
        # 参数方程形成平滑爱心，起点与终点闭合，缩放后仍保持边界在拖动框内。
        points = []
        for index in range(65):
            angle = math.tau * index / 64
            x = 16 * math.sin(angle) ** 3
            y = -(13 * math.cos(angle) - 5 * math.cos(2 * angle)
                  - 2 * math.cos(3 * angle) - math.cos(4 * angle))
            points.append([center_x + x * width / 34, center_y + y * height / 34])
        return points

    if shape == "cross":
        arm_x, arm_y = width * 0.25, height * 0.25
        points = [(left + arm_x, top), (right - arm_x, top),
                  (right - arm_x, center_y - arm_y), (right, center_y - arm_y),
                  (right, center_y + arm_y), (right - arm_x, center_y + arm_y),
                  (right - arm_x, bottom), (left + arm_x, bottom),
                  (left + arm_x, center_y + arm_y), (left, center_y + arm_y),
                  (left, center_y - arm_y), (left + arm_x, center_y - arm_y)]
        return [[x, y] for x, y in points + [points[0]]]

    if shape == "circle":
        return [[(left + right) / 2 + width / 2 * math.cos(index * math.tau / 48),
                 (top + bottom) / 2 + height / 2 * math.sin(index * math.tau / 48)]
                for index in range(49)]

    if shape == "arrow":
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 1:
            return [[x1, y1], [x2, y2]]
        head_length = min(22.0, length * 0.35)
        angle = math.atan2(y2 - y1, x2 - x1)
        left_head = (x2 - head_length * math.cos(angle - math.pi / 6),
                     y2 - head_length * math.sin(angle - math.pi / 6))
        right_head = (x2 - head_length * math.cos(angle + math.pi / 6),
                      y2 - head_length * math.sin(angle + math.pi / 6))
        return [[x1, y1], [x2, y2], [left_head[0], left_head[1]],
                [x2, y2], [right_head[0], right_head[1]]]

    if shape == "wave":
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 1:
            return [[x1, y1], [x2, y2]]
        normal_x, normal_y = -(y2 - y1) / length, (x2 - x1) / length
        amplitude = min(8.0, length / 12)
        return [[x1 + (x2 - x1) * t + normal_x * amplitude * math.sin(t * math.tau * 6),
                 y1 + (y2 - y1) * t + normal_y * amplitude * math.sin(t * math.tau * 6)]
                for t in (index / 48 for index in range(49))]

    return [[x1, y1], [x2, y2]]


def normalize_pressure(value: Any, fallback: float = 0.65) -> float:
    """将设备压感限制在稳定的 0 到 1 范围内。"""
    try:
        pressure = float(value)
    except (TypeError, ValueError):
        pressure = fallback
    if not 0.0 <= pressure <= 1.0:
        pressure = fallback
    return pressure


def pressure_width(base_width: float, pressure: Any) -> float:
    """将归一化压力换算为笔宽，并保持鼠标笔迹的默认粗细。"""
    return max(0.5, float(base_width) * (0.35 + normalize_pressure(pressure)))


def mouse_speed_pressure(speed: Any, maximum_speed: float = 1800.0) -> float:
    """将鼠标移动速度反向映射为模拟压力，慢速更粗、快速更细。"""
    try:
        pixels_per_second = max(0.0, float(speed))
        speed_limit = max(1.0, float(maximum_speed))
    except (TypeError, ValueError):
        return 0.65
    return max(0.0, min(1.0, 1.0 - pixels_per_second / speed_limit))


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
        pressures = stroke.get("pressures")
        if len(points) > 1 and pressures and len(pressures) == len(points):
            for index, ((x1, y1), (x2, y2)) in enumerate(zip(points, points[1:])):
                pressure = (float(pressures[index]) + float(pressures[index + 1])) / 2
                segment_width = max(1, round(pressure_width(width, pressure)))
                draw.line((x1, y1, x2, y2), fill=color, width=segment_width)
                radius = segment_width // 2
                for x, y in ((x1, y1), (x2, y2)):
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        elif points:
            width = round(pressure_width(width, pressures[0])) if pressures else width
            if len(points) > 1:
                draw.line(points, fill=color, width=width, joint="curve")
            else:
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
