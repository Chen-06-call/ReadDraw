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
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / ".build-deps" / "marker-verification"
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
    page.readdraw_app = app
    result = {"success": False}
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
        # 走右侧按钮的真实回调，再向实际 Windows 客户端持续发送荧光笔绘制补丁。
        marker_button = next(button for row in app.notes_panel.content.controls if isinstance(row, ft.Row)
                             for button in row.controls if isinstance(button, ft.TextButton) and button.content == "荧光笔")
        for index in range(12):
            marker_button.on_click(None)
            assert app.tool == "marker"
            assert not page._dialogs.controls
            transform = app.drawing_view.transform
            y = (190 + index * 24) * app.base_image.height / 842
            def pointer(x):
                vx, vy = transform.to_view(x, y)
                return SimpleNamespace(local_x=vx, local_y=vy)
            await app.start_stroke(pointer(45))
            for x in range(50, 350, 15):
                await app.update_stroke(pointer(x))
                await asyncio.sleep(0.016)
            await app.end_stroke(None)
            app.set_tool("pen")
            await asyncio.sleep(0.1)
        app.set_tool("marker")
        await asyncio.sleep(1)
        (OUTPUT / "marker.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), timeout=15))
        app.export_png()
        app.undo()
        app.redo()
        app.go_page(1)
        await asyncio.sleep(1)
        (OUTPUT / "landscape.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), timeout=15))
        app.go_page(-1)
        assert len(app.strokes) == 12
        app.open_settings()
        await asyncio.sleep(1)
        (OUTPUT / "settings.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), timeout=15))
        page.pop_dialog()
        await asyncio.sleep(2)
        print("UI verification completed", flush=True)
        result = {"success": True, "marker_strokes": len(app.strokes), "dialogs_open": len(page._dialogs.controls)}
    except Exception:
        logging.exception("Desktop verification failed")
    finally:
        (OUTPUT / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        await app._close_window()


if __name__ == "__main__":
    configure_logging()
    ft.run(verify)
