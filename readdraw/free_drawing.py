"""独立绘画工作区。

该模块只负责空白画布上的绘画状态和 Flet 控件，不依赖当前打开的书籍，
这样切换阅读与绘画时不会污染阅读页的笔迹、页码和批注状态。
"""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Any, Callable

import flet as ft
import flet.canvas as cv
from PIL import Image as PILImage

from .drawing import (
    MARKER_OPACITY,
    MARKER_WIDTH_MULTIPLIER,
    SHAPE_TYPES,
    clone_strokes,
    compose_page,
    mouse_speed_pressure,
    point_near_stroke,
    pressure_width,
    shape_points,
)
from .keyboard_state import is_control_pressed


class FreeDrawingBoard:
    """提供不绑定书籍的实时绘画画布。"""

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self.logger = logging.getLogger("readdraw.free_drawing")
        self.strokes: list[dict[str, Any]] = []
        self.history: list[list[dict[str, Any]]] = []
        self.redo_stack: list[list[dict[str, Any]]] = []
        self.tool = "pen"
        self.shape_type = "line"
        self.color = "#217567"
        self.thickness = 5
        self.active_stroke: dict[str, Any] | None = None
        self.active_path: cv.Path | None = None
        self._pressure_pointer: tuple[float, float] | None = None
        self._pressure_sample_time: float | None = None
        self._stroke_pressure = 0.65
        self._device_pressure_active = False
        self.erasing = False
        self.viewport = (760.0, 560.0)
        # 未新建画布前跟随窗口；用户新建画布后固定为指定尺寸。
        self.manual_size = False
        self.on_change = on_change

        self.ink = cv.Canvas()
        self.surface = ft.Container(bgcolor="#FFFFFF", expand=True)
        self.detector = ft.GestureDetector(
            content=ft.Container(bgcolor=ft.Colors.TRANSPARENT, expand=True),
            mouse_cursor=ft.MouseCursor.PRECISE,
            drag_interval=16,
            on_pan_down=self._start_pointer,
            on_pan_update=self._update_pointer,
            on_pan_end=self._end_pointer,
            on_pan_cancel=self._cancel_pointer,
            on_tap_up=self._end_pointer,
            on_force_press_start=self._update_device_pressure,
            on_force_press_peak=self._update_device_pressure,
            on_force_press_update=self._update_device_pressure,
        )
        self.canvas = ft.Stack(
            [self.surface, self.ink, self.detector], expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        self._layout()

    @property
    def control(self) -> ft.Control:
        """返回可以直接放入页面布局的控件。"""
        return self.canvas

    @property
    def stroke_count(self) -> int:
        """返回当前画布中的笔迹数量。"""
        return len(self.strokes)

    def set_viewport(self, width: float, height: float) -> None:
        """保存有效画布尺寸，避免 Flet 尚未完成布局时使用无限尺寸。"""
        if self.manual_size:
            return
        if math.isfinite(width) and math.isfinite(height) and width > 1 and height > 1:
            self.viewport = (width, height)
            self._layout()
            self.refresh()

    def set_canvas_size(self, width: float, height: float, manual: bool = True) -> bool:
        """设置独立画布尺寸，尺寸变更不会清除现有笔迹。"""
        if not all(math.isfinite(value) for value in (width, height)):
            return False
        if not 100 <= width <= 10000 or not 100 <= height <= 10000:
            return False
        self.manual_size = manual
        self.viewport = (float(round(width)), float(round(height)))
        self._layout()
        self.refresh()
        return True

    def use_window_size(self) -> None:
        """恢复为跟随窗口的画布尺寸，下一次窗口布局时会自动适配。"""
        self.manual_size = False

    def _layout(self) -> None:
        width, height = self.viewport
        self.canvas.width = width
        self.canvas.height = height
        self.surface.width = width
        self.surface.height = height
        self.ink.width = width
        self.ink.height = height
        self.detector.width = width
        self.detector.height = height
        self.detector.content.width = width
        self.detector.content.height = height
        self._rebuild_paths()

    @staticmethod
    def _point(event: Any) -> tuple[float, float] | None:
        position = getattr(event, "local_position", None)
        if position is not None:
            x, y = float(position.x), float(position.y)
        else:
            x, y = getattr(event, "local_x", None), getattr(event, "local_y", None)
            if x is None or y is None:
                return None
            x, y = float(x), float(y)
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        return max(0.0, min(x, 10000.0)), max(0.0, min(y, 10000.0))

    def _path(self, stroke: dict[str, Any]) -> cv.Path | None:
        points = stroke.get("points", [])
        if not points:
            return None
        elements = [cv.Path.MoveTo(*points[0]), cv.Path.LineTo(*points[0])]
        elements.extend(cv.Path.LineTo(*point) for point in points[1:])
        opacity = float(stroke.get("opacity", 1.0))
        color = ft.Colors.with_opacity(max(0.0, min(1.0, opacity)), stroke.get("color", self.color))
        width = float(stroke.get("width", self.thickness))
        pressures = stroke.get("pressures", [])
        if stroke.get("tool") == "pen" and len(pressures) == len(points):
            width = pressure_width(width, sum(pressures) / len(pressures))
        return cv.Path(
            elements,
            paint=ft.Paint(
                color=color,
                stroke_width=width,
                style=ft.PaintingStyle.STROKE,
                stroke_cap=ft.StrokeCap.ROUND,
                stroke_join=ft.StrokeJoin.ROUND,
            ),
        )

    def _rebuild_paths(self) -> None:
        """根据模型重建矢量路径，撤销、恢复和窗口调整都走同一条路径。"""
        self.ink.shapes = []
        for stroke in self.strokes:
            points = stroke.get("points", [])
            pressures = stroke.get("pressures", [])
            if stroke.get("tool") == "pen" and len(points) > 1 and len(pressures) == len(points):
                for index in range(len(points) - 1):
                    segment = {**stroke, "points": points[index:index + 2],
                               "pressures": pressures[index:index + 2]}
                    path = self._path(segment)
                    if path is not None:
                        self.ink.shapes.append(path)
            else:
                path = self._path(stroke)
                if path is not None:
                    self.ink.shapes.append(path)
        self.active_path = self.ink.shapes[-1] if self.ink.shapes else None

    def _update_canvas(self) -> None:
        """画布挂载后才请求客户端更新，便于独立测试和后台状态操作。"""
        try:
            self.ink.update()
        except (RuntimeError, AttributeError):
            pass

    def _begin_history(self) -> None:
        # 限制历史快照数量，长时间绘画时避免撤销记录无限占用内存。
        self.history.append(clone_strokes(self.strokes))
        del self.history[:-100]
        self.redo_stack.clear()

    async def _start_pointer(self, event: Any) -> None:
        point = self._point(event)
        if point is None:
            return
        self._begin_history()
        self.active_stroke = None
        self._device_pressure_active = False
        self._stroke_pressure = 0.65
        self.erasing = self.tool == "eraser"
        if self.erasing:
            self._erase(point)
            return
        if self.tool == "shape":
            stroke = {
                "tool": "shape",
                "shape": self.shape_type,
                "shape_start": list(point),
                "color": self.color,
                "width": self.thickness,
                "points": [list(point), list(point)],
            }
        else:
            self._stroke_pressure = self._read_pressure(event, point, reset=True)
            stroke = {
                "tool": self.tool,
                "color": self.color,
                "width": self.thickness * (MARKER_WIDTH_MULTIPLIER if self.tool == "marker" else 1),
                "opacity": MARKER_OPACITY if self.tool == "marker" else 1.0,
                "points": [list(point)],
            }
            if self.tool == "pen":
                stroke["pressures"] = [self._stroke_pressure]
        self.active_stroke = stroke
        self.strokes.append(stroke)
        self.active_path = self._path(stroke)
        if self.active_path is not None:
            self.ink.shapes.append(self.active_path)
            self._update_canvas()

    async def _update_pointer(self, event: Any) -> None:
        point = self._point(event)
        if point is None:
            return
        if self.erasing:
            self._erase(point)
            return
        stroke = self.active_stroke
        if stroke is None:
            return
        if stroke.get("tool") == "shape":
            start = tuple(stroke["shape_start"])
            ctrl = is_control_pressed(bool(getattr(event, "ctrl", False)))
            stroke["points"] = shape_points(self.shape_type, start, point, constrain=ctrl)
            self.active_path = self._path(stroke)
            self.ink.shapes[-1] = self.active_path
        else:
            if stroke.get("tool") == "pen":
                self._stroke_pressure = self._read_pressure(event, point)
            if list(point) == stroke["points"][-1]:
                if stroke.get("tool") == "pen":
                    self._update_device_pressure(event)
                return
            stroke["points"].append(list(point))
            if stroke.get("tool") == "pen":
                stroke["pressures"].append(self._stroke_pressure)
                segment = {**stroke, "points": stroke["points"][-2:],
                           "pressures": stroke["pressures"][-2:]}
                self.active_path = self._path(segment)
                if len(stroke["points"]) == 2:
                    # 首段替换起笔圆点，重载后的形状数量与实时绘制保持一致。
                    self.ink.shapes[-1] = self.active_path
                else:
                    self.ink.shapes.append(self.active_path)
            elif self.active_path is not None:
                # 每次只追加一个线段，保持整条荧光笔为同一条透明路径。
                self.active_path.elements.append(cv.Path.LineTo(*point))
        self._update_canvas()

    async def _end_pointer(self, _event: Any = None) -> None:
        self.active_stroke = None
        self.active_path = None
        self.erasing = False
        self._device_pressure_active = False
        self._pressure_pointer = None
        self._pressure_sample_time = None
        if self.on_change:
            self.on_change()

    async def _cancel_pointer(self, _event: Any = None) -> None:
        await self._end_pointer(_event)

    def _read_pressure(self, event: Any, point: tuple[float, float], reset: bool = False) -> float:
        """优先读取数位笔压力；鼠标则根据移动速度平滑模拟压感。"""
        device_pressure = getattr(event, "pressure", None)
        if device_pressure is not None:
            try:
                value = float(device_pressure)
                if math.isfinite(value) and 0 <= value <= 1:
                    self._device_pressure_active = True
                    self._stroke_pressure = value
                    self._pressure_pointer = point
                    self._pressure_sample_time = time.perf_counter()
                    return value
            except (TypeError, ValueError):
                pass
        if self._device_pressure_active:
            # 压力和移动事件可能分开到达，沿用最近一次真实压力，避免误切换到鼠标模拟。
            return self._stroke_pressure
        sample_time = time.perf_counter()
        if reset or self._pressure_pointer is None or self._pressure_sample_time is None:
            self._pressure_pointer = point
            self._pressure_sample_time = sample_time
            return self._stroke_pressure
        elapsed = max(0.008, min(0.1, sample_time - self._pressure_sample_time))
        speed = math.dist(point, self._pressure_pointer) / elapsed
        target = mouse_speed_pressure(speed)
        self._stroke_pressure += (target - self._stroke_pressure) * 0.4
        self._pressure_pointer = point
        self._pressure_sample_time = sample_time
        return self._stroke_pressure

    def _update_device_pressure(self, event: Any) -> None:
        """实时应用数位笔压力到当前绘画笔迹。"""
        if self.active_stroke is None or self.active_stroke.get("tool") != "pen":
            return
        value = getattr(event, "pressure", None)
        try:
            pressure = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(pressure) or not 0 <= pressure <= 1:
            return
        self._device_pressure_active = True
        self._stroke_pressure = pressure
        if self.active_stroke["pressures"]:
            self.active_stroke["pressures"][-1] = pressure
        if len(self.active_stroke["points"]) > 1:
            segment = {**self.active_stroke,
                       "points": self.active_stroke["points"][-2:],
                       "pressures": self.active_stroke["pressures"][-2:]}
            path = self._path(segment)
            if self.ink.shapes:
                self.ink.shapes[-1] = path
            self.active_path = path
        elif self.active_path is not None:
            self.active_path.paint.stroke_width = pressure_width(self.active_stroke["width"], pressure)
        self._update_canvas()

    def _erase(self, point: tuple[float, float]) -> None:
        radius = max(10.0, self.thickness * 2.5)
        # 检测整条线段，而非只检测采样点，快速画出的直线也能擦除。
        remaining = [stroke for stroke in self.strokes
                     if not point_near_stroke(stroke, *point, radius)]
        if len(remaining) != len(self.strokes):
            self.strokes = remaining
            self._rebuild_paths()
            self._update_canvas()

    def set_tool(self, tool: str) -> bool:
        """切换画笔工具，只接受画板支持的工具名称。"""
        if tool not in {"pen", "marker", "eraser", "shape"}:
            return False
        self.tool = tool
        return True

    def set_shape(self, shape: str) -> bool:
        if shape not in SHAPE_TYPES:
            return False
        self.shape_type = shape
        self.tool = "shape"
        return True

    def set_color(self, color: str) -> None:
        self.color = color

    def set_thickness(self, value: float) -> None:
        self.thickness = max(1, min(40, int(value)))

    def undo(self) -> bool:
        if not self.history:
            return False
        self.redo_stack.append(clone_strokes(self.strokes))
        self.strokes = self.history.pop()
        self._rebuild_paths()
        self._update_canvas()
        if self.on_change:
            self.on_change()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.history.append(clone_strokes(self.strokes))
        self.strokes = self.redo_stack.pop()
        self._rebuild_paths()
        self._update_canvas()
        if self.on_change:
            self.on_change()
        return True

    def clear(self) -> bool:
        if not self.strokes:
            return False
        self._begin_history()
        self.strokes = []
        self._rebuild_paths()
        self._update_canvas()
        if self.on_change:
            self.on_change()
        return True

    def restore(self, strokes: list[dict[str, Any]]) -> None:
        """恢复磁盘草稿，重新打开时不携带上一会话的撤销历史。"""
        self.strokes = clone_strokes(strokes)
        self.history.clear()
        self.redo_stack.clear()
        self._rebuild_paths()

    def reset_to_default(self) -> None:
        """恢复为默认的空白画布，不读取或覆盖磁盘中的旧草稿。"""
        self.strokes = []
        self.history.clear()
        self.redo_stack.clear()
        self.active_stroke = None
        self.active_path = None
        self.erasing = False
        self._pressure_pointer = None
        self._pressure_sample_time = None
        self._stroke_pressure = 0.65
        self._device_pressure_active = False
        self.manual_size = False
        self.viewport = (760.0, 560.0)
        self._layout()
        self._update_canvas()

    def export_png(self, path: str | Path) -> Path:
        """将当前画布导出为白底 PNG，并返回实际文件路径。"""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # 窗口缩小后仍导出全部已有笔迹，避免画布右侧与下方被裁掉。
        points = [point for stroke in self.strokes for point in stroke.get("points", [])]
        margin = max((stroke.get("width", 5) for stroke in self.strokes), default=5)
        width = max(1, int(max([self.viewport[0]] + [p[0] + margin for p in points])))
        height = max(1, int(max([self.viewport[1]] + [p[1] + margin for p in points])))
        image = compose_page(PILImage.new("RGB", (width, height), "white"), self.strokes)
        image.save(target, format="PNG")
        return target

    def refresh(self) -> None:
        """请求 Flet 重绘，控件尚未挂载时忽略运行时异常。"""
        try:
            self.canvas.update()
        except (RuntimeError, AttributeError):
            pass
