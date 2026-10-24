"""在隔离数据目录中检查阅读 / 绘画入口和翻页转场。"""

import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / ".build-deps" / "workspace-verification"
OUTPUT.mkdir(parents=True, exist_ok=True)
RUN = OUTPUT / f"run-{uuid.uuid4().hex}"
RUN.mkdir(parents=True, exist_ok=True)
os.environ["APPDATA"] = str(RUN)
os.environ["LOCALAPPDATA"] = str(RUN)
os.environ["READDRAW_DATA_DIR"] = str(RUN / "library")
sys.path.insert(0, str(ROOT))

import flet as ft
import pymupdf

from main import ReadDrawApp

REPORT = {"success": False}


async def verify(page: ft.Page) -> None:
    page.enable_screenshots = True
    page.window.width = 1440
    page.window.height = 960
    app = ReadDrawApp(page)
    try:
        source = RUN / "sample.pdf"
        with pymupdf.open() as document:
            for number in range(3):
                paper = document.new_page(width=600, height=800)
                paper.insert_text((60, 90), f"ReadDraw workspace / page {number + 1}", fontsize=24)
            document.save(source)
        app.import_book(str(source))
        await asyncio.sleep(2)
        (OUTPUT / "reading.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), 15))
        app.drawing_nav.on_click(None)
        await asyncio.sleep(0.35)
        assert app.workspace == "drawing"
        (OUTPUT / "drawing.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), 15))
        app.reading_nav.on_click(None)
        await asyncio.sleep(0.35)
        assert app.workspace == "reading"
        app.go_page(1)
        await asyncio.sleep(0.06)
        (OUTPUT / "page-transition.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), 15))
        await asyncio.sleep(0.35)
        assert app.page_index == 1 and app.canvas_host.offset == (0, 0)
        REPORT.update(
            success=True,
            page=2,
            workspace=app.workspace,
            animation_duration_ms=220,
            drawing_workspace_ready=(
                len(app.drawing_workspace.controls) == 2
                and app.drawing_workspace.controls[1].content is app.free_board.control
            ),
        )
    except Exception as exc:
        REPORT["error"] = repr(exc)
    finally:
        (OUTPUT / "result.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
        await app._close_window()


if __name__ == "__main__":
    ft.run(verify)
    print(json.dumps(REPORT, ensure_ascii=True))
    raise SystemExit(0 if REPORT["success"] else 1)
