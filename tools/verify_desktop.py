"""Render the real Windows Flet client, capture it, and exercise reader actions.

Uses an isolated library under the output directory; never touches personal books.
Run from the repository root: python tools/verify_desktop.py
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / ".build-deps" / "ui-verification"
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["APPDATA"] = str(OUTPUT)
os.environ["LOCALAPPDATA"] = str(OUTPUT)
os.environ["READDRAW_DATA_DIR"] = str(OUTPUT / "library")

import flet as ft
import pymupdf
from main import ReadDrawApp
from readdraw.diagnostics import configure_logging


async def verify(page: ft.Page) -> None:
    page.enable_screenshots = True
    page.window.width = 1440
    page.window.height = 960
    app = ReadDrawApp(page)
    if "--with-drop" not in sys.argv:
        app.file_drop.stop()
    try:
        await asyncio.sleep(2)
        sample = OUTPUT / "sample.pdf"
        with pymupdf.open() as document:
            for width, height in ((595, 842), (842, 595)):
                sheet = document.new_page(width=width, height=height)
                sheet.draw_rect((45, 50, 300, 140), color=(0, .5, .3), fill=(.88, .96, .92))
                sheet.insert_text((60, 85), "READDRAW / VISIBLE PAGE", fontsize=17)
                sheet.insert_text((60, 115), "If you see this, the page is rendered.", fontsize=11)
                for line in range(12):
                    sheet.insert_text((60, 190 + line * 24), f"Sample paragraph {line + 1}: Read, draw and save.", fontsize=12)
            document.save(sample)
        app.import_book(str(sample))
        await asyncio.sleep(3)
        report = {"page_size": app.drawing_view.page_size, "viewport": app.drawing_view.viewport}
        for name in ("page_frame", "image", "ink", "control"):
            widget = getattr(app.drawing_view, name)
            report[name] = {key: getattr(widget, key, None) for key in ("width", "height", "left", "top", "visible")}
        (OUTPUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        png = await asyncio.wait_for(page.take_screenshot(), timeout=15)
        (OUTPUT / "reader.png").write_bytes(png)
        print("SCREENSHOT:", OUTPUT / "reader.png", flush=True)
        app.go_page(1)
        await asyncio.sleep(1)
        (OUTPUT / "landscape.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), timeout=15))
        app.open_settings()
        await asyncio.sleep(1)
        (OUTPUT / "settings.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), timeout=15))
        page.pop_dialog()
        await asyncio.sleep(2)
        print("UI verification completed", flush=True)
    except Exception:
        logging.exception("Desktop verification failed")
    finally:
        await app._close_window()


if __name__ == "__main__":
    configure_logging()
    ft.run(verify)
