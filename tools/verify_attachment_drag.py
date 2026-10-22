"""在隔离的真实 Windows Flet 窗口中验证连续拖动，不访问用户书库。

运行：python tools/verify_attachment_drag.py
会临时移动鼠标、按住左键，并在结束后还原鼠标位置。
"""

import asyncio
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import flet as ft
from PIL import Image

from readdraw.canvas_view import ReadingCanvas
from readdraw.models import Attachment

OUTPUT = ROOT / ".build-deps" / "attachment-drag-verification"
OUTPUT.mkdir(parents=True, exist_ok=True)
REPORT = {"success": False, "moves": []}
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]


async def verify(page: ft.Page) -> None:
    title = f"ReadDraw Drag Verification {os.getpid()}"
    page.title = title
    page.padding = 0
    page.spacing = 0
    page.window.width, page.window.height = 820, 760
    page.enable_screenshots = True
    saved = []
    original_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original_cursor))
    try:
        with tempfile.TemporaryDirectory(dir=OUTPUT) as directory:
            source = Path(directory) / "image.png"
            Image.new("RGB", (160, 90), "#E45756").save(source)
            attachment = Attachment("test", "book", 0, str(source), "image.png", 150, 160, 160, 90, "now")
            canvas = ReadingCanvas(lambda e: None, lambda e: None, lambda e: None,
                                   on_attachment_end=lambda item: saved.append((item.x, item.y)))
            canvas.set_viewport(640, 600)
            canvas.set_page(Image.new("RGB", (600, 600), "white"), [attachment], [])
            page.add(canvas.control)
            await asyncio.sleep(2)
            position = canvas.attachment_controls[attachment.id]
            detector = position.content
            original_start, original_move = detector.on_pan_start, detector.on_pan_update

            def start(event):
                original_start(event)
                REPORT["start"] = {
                    "pointer": [event.global_position.x, event.global_position.y],
                    "position": [position.left, position.top],
                }

            def move(event):
                original_move(event)
                REPORT["moves"].append({
                    "pointer": [event.global_position.x, event.global_position.y],
                    "position": [position.left, position.top],
                })

            detector.on_pan_start, detector.on_pan_update = start, move
            page.update()
            handle = user32.FindWindowW(None, title)
            if not handle:
                raise RuntimeError("找不到测试窗口")
            origin = wintypes.POINT(0, 0)
            if not user32.ClientToScreen(handle, ctypes.byref(origin)):
                raise ctypes.WinError(ctypes.get_last_error())
            user32.SetForegroundWindow(handle)
            x, y = origin.x + round(position.left + 40), origin.y + round(position.top + 40)
            if not user32.SetCursorPos(x, y):
                raise ctypes.WinError(ctypes.get_last_error())
            await asyncio.sleep(0.3)
            user32.mouse_event(0x0002, 0, 0, 0, 0)  # 鼠标左键按下。
            # 前进、反向再前进，实际事件应始终保持鼠标抓取点与图片的相对位置。
            for offset in (*range(6, 157, 6), *range(150, 59, -6), *range(66, 211, 6)):
                user32.SetCursorPos(x + offset, y + offset // 2)
                await asyncio.sleep(0.04)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            await asyncio.sleep(0.8)
            (OUTPUT / "after-drag.png").write_bytes(await asyncio.wait_for(page.take_screenshot(), 10))
            start = REPORT.get("start")
            if not start or len(REPORT["moves"]) < 15:
                raise AssertionError("客户端未产生足够的连续拖动事件")
            errors = []
            for frame in REPORT["moves"]:
                expected = [start["position"][i] + frame["pointer"][i] - start["pointer"][i] for i in (0, 1)]
                errors.extend(abs(frame["position"][i] - expected[i]) for i in (0, 1))
            REPORT["max_tracking_error"] = max(errors)
            REPORT["saved"] = saved
            assert max(errors) < 0.01, "图片出现回跳或累计位移误差"
            assert len(saved) == 1, "松开鼠标后应只保存一次"
            assert saved[0][0] > 300, "图片未跟随鼠标移动完整距离"
            REPORT["success"] = True
    except Exception as exc:
        REPORT["error"] = repr(exc)
    finally:
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        user32.SetCursorPos(original_cursor.x, original_cursor.y)
        (OUTPUT / "result.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
        await page.window.close()


if __name__ == "__main__":
    ft.run(verify)
    print(json.dumps({key: value for key, value in REPORT.items() if key != "moves"}, ensure_ascii=True))
    raise SystemExit(0 if REPORT["success"] else 1)
