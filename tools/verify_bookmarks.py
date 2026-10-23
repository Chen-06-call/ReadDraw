"""在隔离书库中验证真实桌面客户端的书签显示与跳页回调。"""

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / ".build-deps" / "bookmark-verification"
OUTPUT.mkdir(parents=True, exist_ok=True)
RUN = Path(tempfile.mkdtemp(prefix="run-", dir=OUTPUT))
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
    app = ReadDrawApp(page)
    try:
        source = RUN / "sample.pdf"
        with pymupdf.open() as document:
            for number in range(3):
                paper = document.new_page(width=600, height=800)
                paper.insert_text((60, 90), f"ReadDraw bookmarks - page {number + 1}", fontsize=24)
            document.save(source)
        app.import_book(str(source))
        await asyncio.sleep(2)
        app.bookmark_btn.on_click(None)
        app.go_to_last_page()
        app.bookmark_btn.on_click(None)
        await asyncio.sleep(1)
        (OUTPUT / "bookmarks.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), 15))
        assert [entry.data for entry in app.bookmark_list.controls] == [0, 2]
        app.bookmark_list.controls[0].on_click(None)
        assert app.page_index == 0
        assert app.bookmark_btn.icon == ft.Icons.BOOKMARK
        app.bookmark_btn.on_click(None)
        assert app.store.bookmark_pages(app.book.id) == [2]
        app.bookmark_list.controls[0].on_click(None)
        assert app.page_index == 2
        await asyncio.sleep(1)
        (OUTPUT / "after-delete-and-jump.png").write_bytes(
            await asyncio.wait_for(page.take_screenshot(), 15)
        )
        REPORT.update(success=True, page=app.page_index + 1, bookmarks=[3])
    except Exception as exc:
        REPORT["error"] = repr(exc)
    finally:
        (OUTPUT / "result.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
        await app._close_window()


if __name__ == "__main__":
    ft.run(verify)
    print(json.dumps(REPORT, ensure_ascii=True))
    raise SystemExit(0 if REPORT["success"] else 1)
