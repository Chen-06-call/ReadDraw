"""独立画板的草稿持久化，不与书籍批注表耦合。"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable


class DrawingDraft:
    """按需读取保存路径，数据迁移后自动跟随新的数据目录。"""

    def __init__(self, path: Callable[[], Path]) -> None:
        self._path = path

    def load(self) -> list[dict]:
        """只接受有效的矢量笔迹，损坏的草稿由调用方报告。"""
        path = self._path()
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("format") != 1:
            raise ValueError("不支持的绘画草稿格式")
        strokes = data.get("strokes")
        if not isinstance(strokes, list):
            raise ValueError("绘画草稿缺少笔迹列表")
        for stroke in strokes:
            if not isinstance(stroke, dict) or not isinstance(stroke.get("points"), list):
                raise ValueError("绘画草稿笔迹数据损坏")
            for point in stroke["points"]:
                if (not isinstance(point, list) or len(point) != 2
                        or any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in point)):
                    raise ValueError("绘画草稿包含无效坐标")
            width = stroke.get("width", 5)
            opacity = stroke.get("opacity", 1)
            if (not isinstance(width, (float, int)) or not math.isfinite(width) or not 0 < width <= 160
                    or not isinstance(opacity, (float, int)) or not 0 <= opacity <= 1):
                raise ValueError("绘画草稿包含无效笔宽或透明度")
            color = stroke.get("color", "#217567")
            if not isinstance(color, str) or len(color) != 7 or not color.startswith("#"):
                raise ValueError("绘画草稿包含无效颜色")
            int(color[1:], 16)
        return strokes

    def save(self, strokes: list[dict]) -> None:
        """先写完整的新文件再替换，写入失败时保留上一份草稿。"""
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"format": 1, "strokes": strokes}, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(path)
