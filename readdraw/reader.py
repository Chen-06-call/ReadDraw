"""Unified document opening and rendering for PDF and EPUB."""

from pathlib import Path
from typing import Any

from PIL import Image

from .epub import EpubDocument
from .pdf import open_pdf, render_page as render_pdf_page


def open_document(path: str) -> Any:
    if Path(path).suffix.lower() == ".epub":
        return EpubDocument(path)
    return open_pdf(path)


def render_page(document: Any, page_index: int, highlights: list[str] | None = None) -> Image.Image:
    if isinstance(document, EpubDocument):
        return document.render_page(page_index, highlights)
    return render_pdf_page(document, page_index, highlights)
