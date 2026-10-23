"""用真实 Flet 客户端检查桌面布局，不读取个人书库。"""

import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import flet as ft
import pymupdf

from main import ReadDrawApp
from readdraw import config

OUTPUT = ROOT / ".build-deps" / "desktop-layout-verification"
OUTPUT.mkdir(parents=True, exist_ok=True)
REPORT = {"success": False, "windows": []}


async def verify(page: ft.Page) -> None:
    # 测试独立使用书库、附件和设置，避免改变用户的保存位置。
    config.APP_DIR = OUTPUT / "library"
    config.DB_PATH = config.APP_DIR / "readdraw.sqlite3"
    config.ATTACHMENTS_DIR = config.APP_DIR / "attachments"
    config.SETTINGS_PATH = OUTPUT / "settings.json"
    page.enable_screenshots = True
    app = ReadDrawApp(page)
    try:
        source = OUTPUT / "sample.pdf"
        with pymupdf.open() as document:
            paper = document.new_page(width=600, height=800)
            paper.insert_text((60, 90), "ReadDraw - desktop layout", fontsize=24)
            paper.insert_text((60, 150), "The page should fill the available reading area.")
            document.save(source)
        app.import_book(str(source))
        for name, maximized in (("maximized", True), ("restored", False)):
            page.window.maximized = maximized
            page.update()
            await asyncio.sleep(2)
            screenshot = await asyncio.wait_for(page.take_screenshot(pixel_ratio=1), 15)
            (OUTPUT / f"{name}.png").write_bytes(screenshot)
            width, height = app.drawing_view.viewport
            REPORT["windows"].append({
                "state": name, "page": [page.width, page.height],
                "reader": [width, height],
            })
            # 两侧栏共占 472，顶栏、工具栏、状态栏共占 197。
            if page.width and page.height:
                assert abs(width - (page.width - 472)) < 5, "阅读区域没有填满可用宽度"
                assert abs(height - (page.height - 197)) < 5, "阅读区域没有填满可用高度"
        REPORT["success"] = True
    except Exception as exc:
        REPORT["error"] = repr(exc)
    finally:
        (OUTPUT / "result.json").write_text(
            json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await app._close_window()


if __name__ == "__main__":
    ft.run(verify)
    print(json.dumps(REPORT, ensure_ascii=True))
    raise SystemExit(0 if REPORT["success"] else 1)
