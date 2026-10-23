"""使用隔离书库验证翻页动画设置和真实桌面客户端的画布更新。"""

import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / ".build-deps" / "page-animation-verification"
OUTPUT.mkdir(parents=True, exist_ok=True)
# 继承父目录权限，兼容受限 Windows 环境中的 Python 3.13。
RUN = OUTPUT / f"run-{uuid.uuid4().hex}"
RUN.mkdir()
os.environ["APPDATA"] = str(RUN)
os.environ["LOCALAPPDATA"] = str(RUN)
os.environ["READDRAW_DATA_DIR"] = str(RUN / "library")
sys.path.insert(0, str(ROOT))

import flet as ft
import pymupdf

from main import ReadDrawApp
from readdraw import config
from readdraw.version import APP_VERSION


REPORT = {"success": False, "version": APP_VERSION}


async def verify(page: ft.Page) -> None:
    page.enable_screenshots = True
    app = ReadDrawApp(page)
    try:
        source = RUN / "sample.pdf"
        with pymupdf.open() as document:
            for number in range(3):
                paper = document.new_page(width=600, height=800)
                paper.insert_text((60, 90), f"ReadDraw animations / page {number + 1}", fontsize=24)
                paper.insert_text((60, 140), "Page remains readable after every transition.", fontsize=16)
            document.save(source)
        app.import_book(str(source))
        await asyncio.sleep(1.5)
        app.open_settings()
        await asyncio.sleep(0.4)
        dialog = page._dialogs.controls[-1]
        switch = dialog.content.controls[2]
        selector = dialog.content.controls[3]
        (OUTPUT / "settings.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), 15))
        page.pop_dialog()
        for kind in ("slide", "fade", "scale"):
            assert app.apply_page_animation(True, kind)
            app.go_page(1 if app.page_index == 0 else -1)
            await asyncio.sleep(0.05)
            (OUTPUT / f"{kind}-transition.png").write_bytes(
                await asyncio.wait_for(page.take_screenshot(), 15)
            )
            await asyncio.sleep(0.3)
            assert app.canvas_host.opacity == 1
            assert app.canvas_host.scale == 1
            assert app.canvas_host.offset == (0, 0)
            assert app.drawing_view.image.visible
        app.open_settings()
        dialog = page._dialogs.controls[-1]
        switch = dialog.content.controls[2]
        selector = dialog.content.controls[3]
        assert selector.value == "scale"
        switch.value = False
        switch.on_change(SimpleNamespace(control=switch))
        assert selector.disabled
        assert config.get_setting("page_animation_enabled") is False
        (OUTPUT / "disabled-settings.png").write_bytes(
            await asyncio.wait_for(page.take_screenshot(), 15)
        )
        page.pop_dialog()
        app.go_to_last_page()
        assert app.page_index == 2
        assert app.canvas_host.opacity == 1
        assert app.canvas_host.animate_offset is None
        assert app.canvas_host.animate_opacity is None
        assert app.canvas_host.animate_scale is None
        (OUTPUT / "disabled-page.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), 15))
        REPORT.update(success=True, modes=["slide", "fade", "scale"], disabled_navigation=True)
    except Exception as exc:
        REPORT["error"] = repr(exc)
    finally:
        (OUTPUT / "result.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
        await app._close_window()


if __name__ == "__main__":
    ft.run(verify)
    print(json.dumps(REPORT, ensure_ascii=True))
    raise SystemExit(0 if REPORT["success"] else 1)
