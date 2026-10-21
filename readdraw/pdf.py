"""PDF opening and raster rendering."""

from __future__ import annotations

from typing import Any

try:
    import pymupdf as fitz
except ImportError:
    import fitz

from PIL import Image as PILImage
from PIL import ImageDraw

from .config import MAX_PAGE_HEIGHT, MAX_PAGE_WIDTH


def open_pdf(path: str) -> Any:
    """Open a PDF and reject empty documents."""
    document = fitz.open(path)
    if not document.page_count:
        document.close()
        raise ValueError("PDF 没有页面")
    return document


def render_page(document: Any, page_index: int, highlights: list[str] | None = None) -> PILImage.Image:
    """Render one page to a reasonably sized RGB image for the Flet UI."""
    page = document.load_page(page_index)
    scale = min(MAX_PAGE_WIDTH / page.rect.width, MAX_PAGE_HEIGHT / page.rect.height, 2.0)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = PILImage.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
    if highlights:
        draw = ImageDraw.Draw(image, "RGBA")
        for quote in highlights:
            for rect in page.search_for(quote):
                draw.rectangle((rect.x0 * scale, rect.y0 * scale, rect.x1 * scale, rect.y1 * scale), fill=(253, 230, 138, 130))
    return image
