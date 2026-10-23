"""启动隔离的完整桌面程序，供手工或 UI 自动化验证图片插入。

运行后用工具栏的“插入图片”选择输出目录中的 sample.png / sample.jpg。
每次成功插入会记录数据库数量并保存客户端截图；关闭窗口即可结束。
本工具不模拟文件选择结果，也不访问个人书库。
"""

import asyncio
import json
import logging
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / ".build-deps" / "image-insert-verification"
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ["APPDATA"] = str(OUTPUT)
os.environ["LOCALAPPDATA"] = str(OUTPUT)
os.environ["READDRAW_DATA_DIR"] = str(OUTPUT / "library")

import flet as ft
from PIL import Image, ImageDraw
import pymupdf

from main import ReadDrawApp
from readdraw.diagnostics import configure_logging


async def verify(page: ft.Page) -> None:
    page.enable_screenshots = True
    sample = OUTPUT / "sample.pdf"
    if not sample.exists():
        with pymupdf.open() as document:
            sheet = document.new_page(width=595, height=842)
            sheet.insert_text((50, 60), "ReadDraw image insertion test", fontsize=20)
            document.new_page(width=595, height=842)
            document.save(sample)
    image = Image.new("RGB", (320, 180), "#217567")
    ImageDraw.Draw(image).text((30, 60), "INSERT IMAGE TEST", fill="white")
    image.save(OUTPUT / "sample.png")
    image.save(OUTPUT / "sample.jpg")
    app = ReadDrawApp(page)
    page.readdraw_app = app
    app.import_book(str(sample))
    print(f"TEST FILES: {OUTPUT}", flush=True)
    report = {"insertions": [], "picker_calls": 0, "picker_returns": 0}
    original_pick = app.open_image_picker

    async def insert(event=None):
        report["picker_calls"] += 1
        save_report()
        await original_pick(event)
        report["picker_returns"] += 1
        save_report()

    def save_report():
        (OUTPUT / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    app.image_btn.on_click = insert
    page.update()
    previous_count = len(app.attachments)
    save_report()
    # 可自动调用工具栏的同一回调；文件选择仍由实际系统窗口完成，不注入假结果。
    if "--pick-now" in sys.argv:
        page.run_task(insert)
    while not app._closed:
        await asyncio.sleep(0.5)
        count = len(app.attachments)
        if count != previous_count:
            previous_count = count
            report["insertions"].append({"count": count, "page": app.page_index})
            save_report()
            try:
                # 原生客户端解码新图片需要一帧以上，不能在发送补丁后立即截图。
                await asyncio.sleep(1)
                png = await asyncio.wait_for(page.take_screenshot(), timeout=10)
                (OUTPUT / f"inserted-{count}.png").write_bytes(png)
            except Exception:
                logging.exception("截图失败")


if __name__ == "__main__":
    configure_logging()
    ft.run(verify)
