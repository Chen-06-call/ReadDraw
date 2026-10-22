"""Stable raster background and a lightweight, responsive vector ink layer."""

from dataclasses import dataclass
import math
from typing import Any, Callable

import flet as ft
import flet.canvas as cv
from PIL import Image

from .drawing import compose_page, image_data


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


class ReadingCanvas:
    """Keep the gesture detector mounted throughout an entire pen gesture.

    The page is encoded only when loaded. Pointer moves append a vector path
    segment and update Canvas only, never rebuilding the page or detector.
    All handlers run on Flet's event loop, in arrival order without awaits.
    """

    def __init__(self, on_start: Callable, on_move: Callable, on_end: Callable) -> None:
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
            on_pan_update=on_move,
            on_pan_end=on_end,
            on_pan_cancel=on_end,
            on_tap_up=on_end,
        )
        # Never use expand=True on Canvas: Flet serializes it as infinite
        # width/height. A centered container supplies loose constraints, which
        # then produces a Flutter layout error (a grey rectangle in release).
        self.ink = cv.Canvas()
        self.control = ft.Stack([self.page_frame, self.ink, self.detector], fit=ft.StackFit.EXPAND)
        self.viewport = (640.0, 700.0)
        self.page_size = (1, 1)
        self.transform = PageTransform.fit(1, 1, *self.viewport)
        self.strokes: list[dict[str, Any]] = []
        self.active_path: cv.Path | None = None
        self.layout()

    def set_page(self, base: Image.Image, attachments: list, strokes: list[dict]) -> None:
        self.image.src = image_data(compose_page(base, [], attachments))
        self.image.visible = True
        self.page_size = base.size
        self.strokes = strokes
        self.layout()

    def layout(self) -> None:
        width, height = self.viewport
        self.control.width, self.control.height = width, height
        self.ink.width, self.ink.height = width, height
        self.detector.width, self.detector.height = width, height
        self.detector.content.width, self.detector.content.height = width, height
        self.transform = PageTransform.fit(*self.page_size, *self.viewport)
        t = self.transform
        self.page_frame.left, self.page_frame.top = t.left, t.top
        self.page_frame.width, self.page_frame.height = t.width, t.height
        self.set_strokes(self.strokes)

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

    def _shape(self, stroke: dict) -> cv.Path:
        points = [self.transform.to_view(*point) for point in stroke["points"]]
        elements = [cv.Path.MoveTo(*points[0]), cv.Path.LineTo(*points[0])]
        elements.extend(cv.Path.LineTo(*point) for point in points[1:])
        return cv.Path(elements, paint=ft.Paint(
            color=stroke["color"], stroke_width=stroke["width"] * self.transform.scale,
            style=ft.PaintingStyle.STROKE, stroke_cap=ft.StrokeCap.ROUND, stroke_join=ft.StrokeJoin.ROUND))

    def set_strokes(self, strokes: list[dict]) -> None:
        self.strokes = strokes
        self.ink.shapes = [self._shape(stroke) for stroke in strokes if stroke.get("points")]
        self.active_path = None

    def begin(self, stroke: dict) -> None:
        self.active_path = self._shape(stroke)
        self.ink.shapes.append(self.active_path)
        self.ink.update()

    def append(self, x: float, y: float) -> None:
        if self.active_path is not None:
            self.active_path.elements.append(cv.Path.LineTo(*self.transform.to_view(x, y)))
        else:
            # A resize during drawing has reprojected all shapes.
            self.set_strokes(self.strokes)
            if self.ink.shapes:
                self.active_path = self.ink.shapes[-1]
        self.ink.update()
