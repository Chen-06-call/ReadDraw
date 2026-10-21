"""Drawing model helpers independent of Flet."""

from __future__ import annotations

import base64
import copy
import io
from typing import Any

from PIL import Image as PILImage
from PIL import ImageDraw


def clone_strokes(strokes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return copy.deepcopy(strokes)


def point_near_stroke(stroke: dict[str, Any], x: float, y: float, radius: float = 20) -> bool:
    return any((px - x) ** 2 + (py - y) ** 2 < radius**2 for px, py in stroke.get("points", []))


def compose_page(base_image: PILImage.Image, strokes: list[dict[str, Any]], attachments: list[Any] | None = None) -> PILImage.Image:
    """Apply vector-like strokes to a page image for display or export."""
    composite = base_image.copy().convert("RGBA")
    draw = ImageDraw.Draw(composite, "RGBA")
    for stroke in strokes:
        points = [(int(point[0]), int(point[1])) for point in stroke.get("points", [])]
        color = stroke.get("color", "#E45756")
        width = int(stroke.get("width", 4))
        if len(points) > 1:
            draw.line(points, fill=color, width=width, joint="curve")
        elif points:
            x, y = points[0]
            radius = max(1, width // 2)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    for attachment in attachments or []:
        try:
            image = PILImage.open(attachment.path).convert("RGBA")
            image.thumbnail((attachment.width, attachment.height))
            composite.alpha_composite(image, (attachment.x, attachment.y))
        except (OSError, ValueError):
            continue
    return composite


def image_data(image: PILImage.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:image/png;base64," + encoded
