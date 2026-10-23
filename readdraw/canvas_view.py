"""Stable raster background and a lightweight, responsive vector ink layer."""

from dataclasses import dataclass, replace
import inspect
import math
from typing import Any, Callable

import flet as ft
import flet.canvas as cv
from PIL import Image

from .drawing import compose_page, image_data, pressure_width
from .attachment_tools import image_toolbar, scaled_image_size


@dataclass(frozen=True)
class PageTransform:
    """Map stored page pixels to the actual, centered image rectangle."""

    scale: float
    left: float
    top: float
    width: float
    height: float

    @classmethod
    def fit(cls, page_width: float, page_height: float, width: float, height: float):
        scale = max(0.001, min((max(1, width - 16)) / page_width, (max(1, height - 16)) / page_height))
        w, h = page_width * scale, page_height * scale
        return cls(scale, (width - w) / 2, (height - h) / 2, w, h)

    def to_page(self, x: float, y: float, clamp: bool = False) -> tuple[float, float] | None:
        px, py = (x - self.left) / self.scale, (y - self.top) / self.scale
        w, h = self.width / self.scale, self.height / self.scale
        if not clamp and not (0 <= px <= w and 0 <= py <= h):
            return None
        return max(0, min(w, px)), max(0, min(h, py))

    def to_view(self, x: float, y: float) -> tuple[float, float]:
        return self.left + x * self.scale, self.top + y * self.scale


@dataclass(frozen=True)
class AttachmentDrag:
    """记录拖动开始时的固定基准，避免图片移动后局部坐标发生反馈。"""

    pointer_x: float
    pointer_y: float
    image_x: float
    image_y: float
    scale: float


@dataclass(frozen=True)
class AttachmentResizeDrag:
    """记录缩放手势的起点和初始尺寸，保证连续拖动不累计误差。"""

    pointer_x: float
    pointer_y: float
    width: int
    height: int
    scale: float


@dataclass(frozen=True)
class PagePan:
    """固定手势开始点和画页偏移，避免拖动过程中产生坐标反馈。"""

    pointer_x: float
    pointer_y: float
    offset_x: float
    offset_y: float


class ReadingCanvas:
    """Keep the gesture detector mounted throughout an entire pen gesture.

    The page is encoded only when loaded. Pointer moves append a vector path
    segment and update Canvas only, never rebuilding the page or detector.
    All handlers run on Flet's event loop, in arrival order without awaits.
    """

    def __init__(self, on_start: Callable, on_move: Callable, on_end: Callable,
                 on_attachment_move: Callable | None = None,
                 on_attachment_end: Callable | None = None,
                 on_attachment_resize: Callable | None = None,
                 on_attachment_delete: Callable | None = None,
                 can_drag_attachments: Callable[[], bool] | None = None,
                 can_pan_page: Callable[[], bool] | None = None,
                 on_pressure: Callable[[float], None] | None = None) -> None:
        self.image = ft.Image(
            src=b"", fit=ft.BoxFit.FILL, visible=False,
            error_content=ft.Text("书页显示失败，请重新打开文件", color="#B42318"),
        )
        # Container owns the positioned bounds. Image handles only decoding and
        # painting; its width/height serialization differs across Flet versions.
        self.page_frame = ft.Container(content=self.image)
        # Keep the gesture surface separate from Canvas. Canvas's content slot
        # can otherwise cover the raster page on desktop Flet builds.
        self.detector = ft.GestureDetector(
            content=ft.Container(bgcolor=ft.Colors.TRANSPARENT),
            mouse_cursor=ft.MouseCursor.PRECISE,
            drag_interval=16,
            on_pan_down=on_start,
            on_pan_start=self._begin_page_pan,
            on_pan_update=self._update_pointer,
            on_pan_end=self._end_pointer,
            on_pan_cancel=self._cancel_pointer,
            on_tap_up=on_end,
            on_force_press_start=self._update_pressure,
            on_force_press_peak=self._update_pressure,
            on_force_press_update=self._update_pressure,
        )
        # Never use expand=True on Canvas: Flet serializes it as infinite
        # width/height. A centered container supplies loose constraints, which
        # then produces a Flutter layout error (a grey rectangle in release).
        self.ink = cv.Canvas()
        self.attachment_layer = ft.Stack([], fit=ft.StackFit.EXPAND)
        self.control = ft.Stack([self.page_frame, self.ink, self.detector, self.attachment_layer], fit=ft.StackFit.EXPAND)
        self.viewport = (640.0, 700.0)
        self.page_size = (1, 1)
        self.transform = PageTransform.fit(1, 1, *self.viewport)
        self.zoom = 1.0
        self.pan_offset = (0.0, 0.0)
        self._page_pan: PagePan | None = None
        self.attachments: list[Any] = []
        self.attachment_controls: dict[str, ft.Container] = {}
        self.attachment_detectors: dict[str, ft.GestureDetector] = {}
        self.attachment_images: dict[str, ft.Image] = {}
        self.attachment_resize_handles: dict[str, ft.GestureDetector] = {}
        self.attachment_toolbars: dict[str, ft.Container] = {}
        self.selected_attachment_id: str | None = None
        self._attachment_drags: dict[str, AttachmentDrag] = {}
        self._attachment_resize_drags: dict[str, AttachmentResizeDrag] = {}
        self.on_attachment_move = on_attachment_move
        self.on_attachment_end = on_attachment_end
        self.on_attachment_resize = on_attachment_resize
        self.on_attachment_delete = on_attachment_delete
        self.can_drag_attachments = can_drag_attachments or (lambda: True)
        self.can_pan_page = can_pan_page or (lambda: False)
        self.on_pressure = on_pressure
        self.on_pointer_move = on_move
        self.on_pointer_end = on_end
        self.strokes: list[dict[str, Any]] = []
        self.active_path: cv.Path | None = None
        self.layout()

    def set_page(self, base: Image.Image, attachments: list, strokes: list[dict]) -> None:
        # 附件单独放在图片层，才能在鼠标模式下命中并拖动；导出时仍由 compose_page 合成。
        self.image.src = image_data(compose_page(base, [], []))
        self.image.visible = True
        self.page_size = base.size
        self.attachments = attachments
        self.selected_attachment_id = None
        self.strokes = strokes
        self.layout()

    def layout(self) -> None:
        width, height = self.viewport
        self.control.width, self.control.height = width, height
        self.ink.width, self.ink.height = width, height
        self.detector.width, self.detector.height = width, height
        self.detector.content.width, self.detector.content.height = width, height
        fitted = PageTransform.fit(*self.page_size, *self.viewport)
        scale = fitted.scale * self.zoom
        width, height = self.page_size[0] * scale, self.page_size[1] * scale
        base_left = (self.viewport[0] - width) / 2
        base_top = (self.viewport[1] - height) / 2
        offset_x, offset_y = self._clamp_pan(*self.pan_offset, width, height, base_left, base_top)
        self.pan_offset = (offset_x, offset_y)
        self.transform = PageTransform(scale, base_left + offset_x,
                                       base_top + offset_y, width, height)
        t = self.transform
        self.page_frame.left, self.page_frame.top = t.left, t.top
        self.page_frame.width, self.page_frame.height = t.width, t.height
        self.set_strokes(self.strokes)
        self._build_attachment_layer()

    def _build_attachment_layer(self) -> None:
        """按当前缩放重建附件控件，附件位置始终保存为书页像素。"""
        # 页面或尺寸变化会替换手势控件，旧手势不应继续修改新页面。
        self._attachment_drags.clear()
        self._attachment_resize_drags.clear()
        self.attachment_layer.controls.clear()
        self.attachment_controls.clear()
        self.attachment_detectors.clear()
        self.attachment_images.clear()
        self.attachment_resize_handles.clear()
        self.attachment_toolbars.clear()
        for attachment in self.attachments:
            try:
                with Image.open(attachment.path) as source:
                    image = source.convert("RGBA").resize(
                        (max(1, attachment.width), max(1, attachment.height)),
                        Image.Resampling.LANCZOS,
                    )
                    payload = image_data(image)
            except (OSError, ValueError):
                continue
            image_control = ft.Image(payload, fit=ft.BoxFit.CONTAIN,
                                     width=attachment.width * self.transform.scale,
                                     height=attachment.height * self.transform.scale)
            detector = ft.GestureDetector(
                content=image_control,
                width=attachment.width * self.transform.scale,
                height=attachment.height * self.transform.scale,
                mouse_cursor=ft.MouseCursor.MOVE,
                drag_interval=16,
                on_tap_up=lambda event, item=attachment: self._select_attachment(item),
                on_pan_start=lambda event, item=attachment: self._begin_attachment_drag(item, event),
                on_pan_update=lambda event, item=attachment: self._move_attachment(item, event),
                on_pan_end=lambda event, item=attachment: self._end_attachment_drag(item, event),
                on_pan_cancel=lambda event, item=attachment: self._end_attachment_drag(item),
            )
            children = [detector]
            resize_handle = ft.GestureDetector(
                content=ft.Container(
                    content=ft.Icon(ft.Icons.OPEN_IN_FULL, size=12, color="#FFFFFF"),
                    width=20, height=20, bgcolor="#217567", border_radius=3,
                    alignment=ft.Alignment.CENTER,
                ),
                width=20, height=20,
                visible=attachment.id == self.selected_attachment_id,
                mouse_cursor=ft.MouseCursor.RESIZE_DOWN_RIGHT,
                tooltip="拖动以调整图片大小",
                drag_interval=16,
                on_pan_start=lambda event, item=attachment: self._begin_attachment_resize(item, event),
                on_pan_update=lambda event, item=attachment: self._resize_attachment_from_drag(item, event),
                on_pan_end=lambda event, item=attachment: self._end_attachment_resize(item, event),
                on_pan_cancel=lambda event, item=attachment: self._end_attachment_resize(item),
            )
            children.append(ft.Container(content=resize_handle, right=-1, bottom=-1))
            self.attachment_resize_handles[attachment.id] = resize_handle
            image_stack = ft.Stack(children, fit=ft.StackFit.EXPAND)
            position = ft.Container(content=image_stack,
                                    left=self.transform.to_view(attachment.x, attachment.y)[0],
                                    top=self.transform.to_view(attachment.x, attachment.y)[1],
                                    width=attachment.width * self.transform.scale,
                                    height=attachment.height * self.transform.scale,
                                    border=ft.Border.all(
                                        2 if attachment.id == self.selected_attachment_id else 0,
                                        "#217567",
                                    ))
            self.attachment_layer.controls.append(position)
            self.attachment_controls[attachment.id] = position
            self.attachment_detectors[attachment.id] = detector
            self.attachment_images[attachment.id] = image_control
            if attachment.id == self.selected_attachment_id:
                self._add_attachment_toolbar(attachment, position)

    def _attachment_toolbar(self, attachment: Any, position: ft.Container) -> ft.Container:
        """选中图片时显示独立工具条，避免把编辑操作藏在右键菜单中。"""
        toolbar = image_toolbar(lambda: self._delete_attachment(attachment))
        self._position_attachment_toolbar(toolbar, position)
        return toolbar

    def _position_attachment_toolbar(self, toolbar: ft.Container, position: ft.Container) -> None:
        toolbar.left = max(0, min(position.left, self.viewport[0] - toolbar.width))
        toolbar.top = max(0, min(position.top - 38, self.viewport[1] - toolbar.height))

    def _add_attachment_toolbar(self, attachment: Any, position: ft.Container) -> None:
        toolbar = self._attachment_toolbar(attachment, position)
        self.attachment_layer.controls.append(toolbar)
        self.attachment_toolbars[attachment.id] = toolbar

    def _update_attachment_layer(self) -> None:
        """控件未挂载时保留模型状态，等页面挂载后再由 Flet 绘制。"""
        try:
            self.attachment_layer.update()
        except RuntimeError:
            pass

    def _select_attachment(self, attachment: Any) -> None:
        if not self.can_drag_attachments() or not self._has_attachment(attachment):
            return
        if self.selected_attachment_id == attachment.id:
            return
        previous = self.attachment_controls.get(self.selected_attachment_id)
        if previous is not None:
            previous.border = ft.Border.all(0, "#217567")
            previous_handle = self.attachment_resize_handles.get(self.selected_attachment_id)
            if previous_handle is not None:
                previous_handle.visible = False
            toolbar = self.attachment_toolbars.pop(self.selected_attachment_id, None)
            if toolbar in self.attachment_layer.controls:
                self.attachment_layer.controls.remove(toolbar)
        self.selected_attachment_id = attachment.id
        position = self.attachment_controls[attachment.id]
        position.border = ft.Border.all(2, "#217567")
        self.attachment_resize_handles[attachment.id].visible = True
        self._add_attachment_toolbar(attachment, position)
        self._update_attachment_layer()

    def _has_attachment(self, attachment: Any) -> bool:
        """页面切换后到达的旧控件事件不能操作新页面的数据。"""
        return any(item is attachment for item in self.attachments)

    def clear_attachment_selection(self) -> None:
        """切换为绘画工具时移除编辑边框和工具条，不重建图片控件。"""
        position = self.attachment_controls.get(self.selected_attachment_id)
        if position is not None:
            position.border = ft.Border.all(0, "#217567")
        handle = self.attachment_resize_handles.get(self.selected_attachment_id)
        if handle is not None:
            handle.visible = False
        for toolbar in self.attachment_toolbars.values():
            self.attachment_layer.controls.remove(toolbar)
        self.attachment_toolbars.clear()
        self.selected_attachment_id = None

    def _begin_attachment_resize(self, attachment: Any, event: Any) -> None:
        pointer = self._global_pointer(event)
        if (self.can_drag_attachments() and self._has_attachment(attachment)
                and attachment.id == self.selected_attachment_id and pointer is not None):
            self._attachment_resize_drags[attachment.id] = AttachmentResizeDrag(
                *pointer, attachment.width, attachment.height, self.transform.scale,
            )

    def _resize_attachment_from_drag(self, attachment: Any, event: Any) -> None:
        drag = self._attachment_resize_drags.get(attachment.id)
        pointer = self._global_pointer(event)
        if (not self.can_drag_attachments() or drag is None or pointer is None
                or not self._has_attachment(attachment)):
            return
        # 沿右下角的对角方向计算缩放量，并保持原始宽高比。
        dx = (pointer[0] - drag.pointer_x) / drag.scale
        dy = (pointer[1] - drag.pointer_y) / drag.scale
        factor = 1 + (dx * drag.width + dy * drag.height) / (drag.width ** 2 + drag.height ** 2)
        target_width, target_height = scaled_image_size(
            drag.width, drag.height, factor, self.page_size,
            position=(attachment.x, attachment.y),
        )
        attachment.width, attachment.height = target_width, target_height
        self._sync_attachment_size(attachment)

    def _sync_attachment_size(self, attachment: Any) -> None:
        position = self.attachment_controls.get(attachment.id)
        image_control = self.attachment_images.get(attachment.id)
        if position is None or image_control is None:
            return
        position.width = attachment.width * self.transform.scale
        position.height = attachment.height * self.transform.scale
        image_control.width, image_control.height = position.width, position.height
        detector = self.attachment_detectors.get(attachment.id)
        if detector is None:
            return
        detector.width, detector.height = position.width, position.height
        self._update_attachment_layer()

    def _end_attachment_resize(self, attachment: Any, event: Any = None) -> None:
        drag = self._attachment_resize_drags.get(attachment.id)
        if drag is None:
            return
        if event is not None:
            self._resize_attachment_from_drag(attachment, event)
        self._attachment_resize_drags.pop(attachment.id, None)
        if not self._has_attachment(attachment):
            return
        if (attachment.width, attachment.height) == (drag.width, drag.height):
            return
        candidate = replace(attachment)
        if self.on_attachment_resize and self.on_attachment_resize(candidate) is False:
            attachment.width, attachment.height = drag.width, drag.height
            self._sync_attachment_size(attachment)

    def _delete_attachment(self, attachment: Any) -> None:
        if not self.can_drag_attachments() or not self._has_attachment(attachment):
            return
        # 控制器先处理持久化；只有删除成功后才移除页面上的图片。
        if self.on_attachment_delete and self.on_attachment_delete(attachment) is False:
            return
        self.selected_attachment_id = None
        remaining = [item for item in self.attachments if item.id != attachment.id]
        self.set_attachments(remaining)

    def set_attachments(self, attachments: list) -> None:
        """只更新附件层，插入图片时保留书页、笔迹和正在使用的画布控件。"""
        self.attachments = attachments
        self._build_attachment_layer()
        self._update_attachment_layer()

    @staticmethod
    def _global_pointer(event: Any) -> tuple[float, float] | None:
        """全局坐标不随图片移动；不使用会随控件原点改变的局部位移。"""
        point = getattr(event, "global_position", None)
        if point is None:
            return None
        x, y = float(point.x), float(point.y)
        return (x, y) if math.isfinite(x) and math.isfinite(y) else None

    def _begin_attachment_drag(self, attachment: Any, event: Any) -> None:
        pointer = self._global_pointer(event)
        if self.can_drag_attachments() and self._has_attachment(attachment) and pointer is not None:
            self._select_attachment(attachment)
            self._attachment_drags[attachment.id] = AttachmentDrag(
                *pointer, float(attachment.x), float(attachment.y), self.transform.scale
            )

    def _move_attachment(self, attachment: Any, event: Any) -> None:
        drag = self._attachment_drags.get(attachment.id)
        pointer = self._global_pointer(event)
        if not self.can_drag_attachments() or drag is None or pointer is None:
            return
        # 每一帧都相对同一窗口坐标基准计算，事件合并、重复或反向拖动均不会累积误差。
        x = max(0.0, drag.image_x + (pointer[0] - drag.pointer_x) / drag.scale)
        y = max(0.0, drag.image_y + (pointer[1] - drag.pointer_y) / drag.scale)
        attachment.x, attachment.y = round(x), round(y)
        position = self.attachment_controls.get(attachment.id)
        if position is not None:
            # 显示保留亚像素精度，避免缩放后整像素取整使图片一格一格跳动。
            position.left, position.top = self.transform.to_view(x, y)
            toolbar = self.attachment_toolbars.get(attachment.id)
            if toolbar is not None:
                self._position_attachment_toolbar(toolbar, position)
            try:
                position.update()
                if toolbar is not None:
                    toolbar.update()
            except RuntimeError:
                # 控件尚未挂载到真实页面时只保留模型位置，挂载后会按当前状态重绘。
                pass
        if self.on_attachment_move:
            self.on_attachment_move(attachment)

    def _end_attachment_drag(self, attachment: Any, event: Any = None) -> None:
        if attachment.id not in self._attachment_drags:
            return
        # 拖动事件有节流，结束事件中的坐标可能比最后一次移动更新更靠后。
        if event is not None:
            self._move_attachment(attachment, event)
        self._attachment_drags.pop(attachment.id)
        if self.on_attachment_end:
            self.on_attachment_end(attachment)

    def set_zoom(self, value: float) -> bool:
        """限制缩放范围，避免页面过小或放大后控件尺寸溢出。"""
        value = max(0.5, min(3.0, float(value)))
        if abs(value - self.zoom) < 0.001:
            return False
        self.zoom = value
        if self.can_pan_page():
            self.detector.mouse_cursor = (
                ft.MouseCursor.GRAB if value > 1.0 else ft.MouseCursor.BASIC
            )
        else:
            self.detector.mouse_cursor = ft.MouseCursor.PRECISE
        self.layout()
        return True

    def reset_view(self, relayout: bool = True) -> bool:
        """翻页或适合窗口操作时恢复默认比例和居中位置。"""
        changed = self.zoom != 1.0 or self.pan_offset != (0.0, 0.0)
        self.zoom = 1.0
        self.pan_offset = (0.0, 0.0)
        self._page_pan = None
        self.detector.mouse_cursor = (
            ft.MouseCursor.BASIC if self.can_pan_page() else ft.MouseCursor.PRECISE
        )
        if relayout:
            self.layout()
        return changed

    def _clamp_pan(self, x: float, y: float, width: float, height: float,
                   base_left: float, base_top: float) -> tuple[float, float]:
        """缩放后允许拖动画页，但不让边缘露出空白。"""
        minimum_x, maximum_x = self.viewport[0] - width - base_left, -base_left
        minimum_y, maximum_y = self.viewport[1] - height - base_top, -base_top
        bounded_x = max(minimum_x, min(maximum_x, x)) if width > self.viewport[0] else 0.0
        bounded_y = max(minimum_y, min(maximum_y, y)) if height > self.viewport[1] else 0.0
        return bounded_x, bounded_y

    @staticmethod
    def _pointer(event: Any) -> tuple[float, float] | None:
        point = getattr(event, "global_position", None)
        if point is not None:
            x, y = float(point.x), float(point.y)
        else:
            x = getattr(event, "global_x", None)
            y = getattr(event, "global_y", None)
            if x is None or y is None:
                return None
            x, y = float(x), float(y)
        return (x, y) if math.isfinite(x) and math.isfinite(y) else None

    def _begin_page_pan(self, event: Any) -> None:
        pointer = self._pointer(event)
        if self.zoom <= 1.0 or not self.can_pan_page() or pointer is None:
            return
        self._page_pan = PagePan(*pointer, *self.pan_offset)
        self.detector.mouse_cursor = ft.MouseCursor.GRABBING

    def _move_page_pan(self, event: Any) -> bool:
        drag = self._page_pan
        pointer = self._pointer(event)
        if drag is None or pointer is None:
            return False
        offset = (drag.offset_x + pointer[0] - drag.pointer_x,
                  drag.offset_y + pointer[1] - drag.pointer_y)
        if offset == self.pan_offset:
            return True
        self.pan_offset = offset
        self.layout()
        try:
            self.control.update()
        except RuntimeError:
            pass
        return True

    def _end_page_pan(self, event: Any = None) -> bool:
        if self._page_pan is None:
            return False
        if event is not None:
            self._move_page_pan(event)
        self._page_pan = None
        self.detector.mouse_cursor = ft.MouseCursor.GRAB
        return True

    async def _dispatch_pointer(self, callback: Callable, event: Any) -> None:
        """转发手势事件，并等待异步笔迹回调完成。"""
        result = callback(event)
        if inspect.isawaitable(result):
            await result

    async def _update_pointer(self, event: Any) -> None:
        if self._page_pan is not None and (self.zoom <= 1.0 or not self.can_pan_page()):
            self._page_pan = None
        if not self._move_page_pan(event):
            await self._dispatch_pointer(self.on_pointer_move, event)

    async def _end_pointer(self, event: Any = None) -> None:
        if not self._end_page_pan(event):
            await self._dispatch_pointer(self.on_pointer_end, event)

    async def _cancel_pointer(self, event: Any) -> None:
        if not self._end_page_pan():
            await self._dispatch_pointer(self.on_pointer_end, event)

    def set_viewport(self, width: float, height: float) -> bool:
        """Accept measured finite host bounds, never the renderer's own size."""
        if not all(math.isfinite(value) and value > 1 for value in (width, height)):
            return False
        if abs(width - self.viewport[0]) < 0.5 and abs(height - self.viewport[1]) < 0.5:
            return False
        self.viewport = (width, height)
        self.layout()
        return True

    async def resize(self, event: ft.LayoutSizeChangeEvent) -> None:
        if not self.set_viewport(event.width, event.height):
            return
        if self.image.visible:
            self.control.update()

    def coords(self, event: Any, clamp: bool = False) -> tuple[float, float] | None:
        position = getattr(event, "local_position", None)
        if position is not None:
            x, y = float(position.x), float(position.y)
        else:
            x, y = float(event.local_x), float(event.local_y)
        return self.transform.to_page(x, y, clamp)

    def _shape(self, stroke: dict, start: int = 0, end: int | None = None) -> cv.Path:
        points = [self.transform.to_view(*point) for point in stroke["points"]]
        if end is None:
            end = len(points)
        points = points[start:end]
        elements = [cv.Path.MoveTo(*points[0]), cv.Path.LineTo(*points[0])]
        elements.extend(cv.Path.LineTo(*point) for point in points[1:])
        # 界面与 PNG 导出使用同一份透明度，重启或翻页后荧光笔颜色保持一致。
        color = ft.Colors.with_opacity(stroke.get("opacity", 1.0), stroke["color"])
        pressures = stroke.get("pressures", [])
        width = stroke["width"]
        if pressures:
            selected = pressures[start:end]
            width = pressure_width(width, sum(selected) / len(selected))
        return cv.Path(elements, paint=ft.Paint(
            color=color, stroke_width=width * self.transform.scale,
            style=ft.PaintingStyle.STROKE, stroke_cap=ft.StrokeCap.ROUND, stroke_join=ft.StrokeJoin.ROUND))

    def _stroke_shapes(self, stroke: dict) -> list[cv.Path]:
        points = stroke.get("points", [])
        pressures = stroke.get("pressures", [])
        if len(points) < 2 or len(pressures) != len(points):
            return [self._shape(stroke)] if points else []
        return [self._shape(stroke, index, index + 2) for index in range(len(points) - 1)]

    def set_strokes(self, strokes: list[dict]) -> None:
        self.strokes = strokes
        self.ink.shapes = [shape for stroke in strokes for shape in self._stroke_shapes(stroke)]
        self.active_path = None

    def begin(self, stroke: dict) -> None:
        shapes = self._stroke_shapes(stroke)
        self.ink.shapes.extend(shapes)
        self.active_path = shapes[-1] if shapes else None
        self.ink.update()

    def append(self, x: float, y: float, pressure: float = 0.65,
               stroke: dict | None = None) -> None:
        if self.active_path is not None and stroke is not None:
            previous_index = len(stroke["points"]) - 2
            self.active_path = self._shape(stroke, previous_index, previous_index + 2)
            self.ink.shapes.append(self.active_path)
        else:
            # A resize during drawing has reprojected all shapes.
            self.set_strokes(self.strokes)
            if self.ink.shapes:
                self.active_path = self.ink.shapes[-1]
            if self.active_path is not None:
                self.active_path.elements.append(cv.Path.LineTo(*self.transform.to_view(x, y)))
        self.ink.update()

    def update_active_pressure(self, pressure: float) -> None:
        """更新当前笔迹末端的压力和实时显示粗细。"""
        if self.active_path is None or not self.strokes:
            return
        stroke = self.strokes[-1]
        pressures = stroke.get("pressures")
        if not pressures:
            return
        pressures[-1] = pressure
        if len(pressures) > 1:
            segment_pressure = (pressures[-2] + pressure) / 2
        else:
            segment_pressure = pressure
        self.active_path.paint.stroke_width = pressure_width(
            stroke["width"], segment_pressure
        ) * self.transform.scale
        self.active_path.update()

    def _update_pressure(self, event: Any) -> None:
        pressure = getattr(event, "pressure", None)
        if pressure is not None and self.on_pressure:
            self.on_pressure(pressure)
