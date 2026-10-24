"""在隔离数据目录验证真实桌面客户端的压感笔迹和色盘显示。

压力事件由脚本注入，用于验证界面渲染；实际数位笔硬件仍需在对应设备上试用。
"""

import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / ".build-deps" / "drawing-tools-verification"
RUN = OUTPUT / f"run-{uuid.uuid4().hex}"
RUN.mkdir(parents=True)
os.environ["APPDATA"] = str(RUN)
os.environ["LOCALAPPDATA"] = str(RUN)
os.environ["READDRAW_DATA_DIR"] = str(RUN / "library")
sys.path.insert(0, str(ROOT))

import flet as ft

from main import ReadDrawApp
from readdraw.version import APP_TAG


REPORT = {"success": False, "version": APP_TAG}


async def verify(page: ft.Page) -> None:
    page.enable_screenshots = True
    app = ReadDrawApp(page)
    try:
        app.show_workspace("drawing")
        await asyncio.sleep(2)
        assert len(app.free_shape_btn.items) == 13
        assert len(app.free_quick_color_buttons) == 6
        board = app.free_board
        board.set_thickness(20)
        for row, color in enumerate(("#217567", "#2E90FA")):
            app.set_free_color(color)
            for index in range(45):
                point = SimpleNamespace(
                    local_position=SimpleNamespace(x=80 + index * 10, y=100 + row * 80),
                    pressure=index / 44,
                )
                if index == 0:
                    await board.detector.on_pan_down(point)
                else:
                    await board.detector.on_pan_update(point)
                await asyncio.sleep(0.016)
            await board.detector.on_pan_end(None)
        widths = [shape.paint.stroke_width for shape in board.ink.shapes]
        assert max(widths) > min(widths) * 2
        board.export_png(OUTPUT / "pressure-export.png")
        await asyncio.sleep(0.3)
        (OUTPUT / "drawing.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), 15))

        app.free_color_palette.on_click(None)
        await asyncio.sleep(0.5)
        picker = app.free_color_picker
        await picker.detector.on_pan_down(SimpleNamespace(local_position=SimpleNamespace(x=190, y=70)))
        picker.brightness.value = 0.85
        picker.brightness.on_change(SimpleNamespace(control=picker.brightness))
        await asyncio.sleep(0.4)
        (OUTPUT / "color-picker.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), 15))
        picker.hex_field.value = "#C12ED4"
        picker.dialog.actions[1].on_click(None)
        assert board.color == "#C12ED4"
        assert app.free_color_palette.icon_color == board.color
        app.save_current_work()
        assert app.free_draft.load()[0]["pressures"] == board.strokes[0]["pressures"]
        REPORT.update(success=True, strokes=board.stroke_count, color=board.color,
                      minimum_width=min(widths), maximum_width=max(widths))
    except Exception as exc:
        REPORT["error"] = repr(exc)
    finally:
        (OUTPUT / "result.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
        await app._close_window()


if __name__ == "__main__":
    ft.run(verify)
    print(json.dumps(REPORT, ensure_ascii=True))
    raise SystemExit(0 if REPORT["success"] else 1)
