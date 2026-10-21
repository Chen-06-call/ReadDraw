"""Simple, dependency-light EPUB reader for the first cross-format release."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from ebooklib import epub, ITEM_DOCUMENT


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = html.unescape(data).strip()
        if text:
            self.parts.append(text)


def html_to_text(value: bytes) -> str:
    parser = _TextParser()
    parser.feed(value.decode("utf-8", errors="ignore"))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


class EpubDocument:
    """Presents EPUB chapters as paginated, searchable raster pages."""

    def __init__(self, path: str) -> None:
        self.path = path
        book = epub.read_epub(path)
        self.title = next((value for key, value in book.get_metadata("DC", "title") if value), Path(path).stem)
        self.pages: list[str] = []
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            if Path(item.get_name()).stem.lower() in {"nav", "toc"}:
                continue
            text = html_to_text(item.get_content())
            if not text:
                continue
            self.pages.extend(text[index:index + 2200] for index in range(0, len(text), 2200))
        if not self.pages:
            raise ValueError("EPUB 没有可阅读的文本")
        self.page_count = len(self.pages)

    def close(self) -> None:
        return None

    def render_page(self, page_index: int, highlights: list[str] | None = None) -> Image.Image:
        image = Image.new("RGB", (760, 900), "#FFFEFA")
        draw = ImageDraw.Draw(image)
        font = self._font(24)
        small_font = self._font(15)
        draw.text((56, 42), self.title, font=small_font, fill="#667085")
        lines = self._wrap(self.pages[page_index], font, 650)
        y = 92
        for line in lines[:30]:
            if any(quote and quote in line for quote in highlights or []):
                draw.rounded_rectangle((50, y - 2, 710, y + 31), radius=4, fill="#FEF3A6")
            draw.text((56, y), line, font=font, fill="#1D2939")
            y += 29
        draw.text((56, 850), f"{page_index + 1} / {self.page_count}", font=small_font, fill="#98A2B3")
        return image

    @staticmethod
    def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        for path in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        return ImageFont.load_default()

    @staticmethod
    def _wrap(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
        lines: list[str] = []
        current = ""
        for char in text:
            candidate = current + char
            if font.getlength(candidate) > max_width and current:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines
