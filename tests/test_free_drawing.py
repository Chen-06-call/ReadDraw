"""独立绘画工作区的核心行为测试，不依赖系统临时目录。"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from readdraw.free_drawing import FreeDrawingBoard


class FreeDrawingBoardTests(unittest.TestCase):
    """验证绘画状态模型和导出结果。"""

    def setUp(self) -> None:
        self.board = FreeDrawingBoard()

    def test_tool_shape_and_color_settings(self) -> None:
        self.assertTrue(self.board.set_tool("marker"))
        self.assertEqual(self.board.tool, "marker")
        self.assertTrue(self.board.set_shape("triangle"))
        self.assertEqual((self.board.tool, self.board.shape_type), ("shape", "triangle"))
        self.board.set_color("#E45756")
        self.board.set_thickness(18)
        self.assertEqual((self.board.color, self.board.thickness), ("#E45756", 18))
        self.assertFalse(self.board.set_tool("unknown"))

    def test_pointer_updates_render_live_stroke(self) -> None:
        async def draw() -> None:
            await self.board._start_pointer(SimpleNamespace(local_x=20, local_y=30))
            await self.board._update_pointer(SimpleNamespace(local_x=40, local_y=50))
            await self.board._end_pointer()

        asyncio.run(draw())
        self.assertEqual(self.board.stroke_count, 1)
        self.assertEqual(self.board.strokes[0]["points"], [[20.0, 30.0], [40.0, 50.0]])
        self.assertEqual(len(self.board.ink.shapes), 1)

    def test_undo_redo_and_clear(self) -> None:
        async def draw() -> None:
            await self.board._start_pointer(SimpleNamespace(local_x=10, local_y=10))
            await self.board._end_pointer()

        asyncio.run(draw())
        self.assertTrue(self.board.undo())
        self.assertEqual(self.board.stroke_count, 0)
        self.assertTrue(self.board.redo())
        self.assertEqual(self.board.stroke_count, 1)
        self.assertTrue(self.board.clear())
        self.assertEqual(self.board.stroke_count, 0)
        self.assertTrue(self.board.undo())
        self.assertEqual(self.board.stroke_count, 1)

    def test_shape_pointer_uses_constraint_flag(self) -> None:
        self.board.set_shape("circle")

        async def draw() -> None:
            await self.board._start_pointer(SimpleNamespace(local_x=10, local_y=20))
            await self.board._update_pointer(
                SimpleNamespace(local_x=90, local_y=60, ctrl=True)
            )
            await self.board._end_pointer()

        with patch("readdraw.free_drawing.is_control_pressed", side_effect=lambda value: value):
            asyncio.run(draw())
        points = self.board.strokes[0]["points"]
        width = max(point[0] for point in points) - min(point[0] for point in points)
        height = max(point[1] for point in points) - min(point[1] for point in points)
        self.assertAlmostEqual(width, height)

    def test_png_export_contains_canvas(self) -> None:
        target = Path(".build-deps") / "free-drawing-test.png"
        target.unlink(missing_ok=True)
        self.board.set_viewport(320, 240)
        self.board.strokes = [{
            "tool": "pen",
            "color": "#E45756",
            "width": 6,
            "points": [[20, 20], [80, 80]],
        }]
        self.board.export_png(target)
        self.assertTrue(target.exists())
        with Image.open(target) as image:
            self.assertEqual(image.size, (320, 240))
            self.assertEqual(image.format, "PNG")


if __name__ == "__main__":
    unittest.main()
