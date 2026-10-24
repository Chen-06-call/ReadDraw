"""独立绘画工作区的核心行为测试，不依赖系统临时目录。"""

from __future__ import annotations

import asyncio
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from readdraw.free_drawing import FreeDrawingBoard
from readdraw.drawing_draft import DrawingDraft


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

    def test_pen_pressure_is_saved_and_changes_live_segment_width(self) -> None:
        """独立画布保存压力采样，并在绘制过程中实时改变线宽。"""
        async def draw() -> None:
            await self.board._start_pointer(SimpleNamespace(local_x=20, local_y=30, pressure=0.05))
            await self.board._update_pointer(SimpleNamespace(local_x=40, local_y=50, pressure=0.95))
            await self.board._end_pointer()

        asyncio.run(draw())
        stroke = self.board.strokes[0]
        self.assertEqual(stroke["pressures"], [0.05, 0.95])
        self.assertEqual(len(self.board.ink.shapes), 1)
        live_width = self.board.ink.shapes[0].paint.stroke_width
        self.board._rebuild_paths()
        self.assertEqual(len(self.board.ink.shapes), 1)
        self.assertEqual(self.board.ink.shapes[0].paint.stroke_width, live_width)

    def test_mouse_movement_simulates_pressure(self) -> None:
        """鼠标慢速移动模拟较大压力，快速移动模拟较小压力。"""
        with patch("readdraw.free_drawing.time.perf_counter", side_effect=[1.0, 1.04, 2.0, 2.01]):
            slow = self.board._read_pressure(SimpleNamespace(), (0, 0), reset=True)
            slow = self.board._read_pressure(SimpleNamespace(), (1, 0))
            self.board._read_pressure(SimpleNamespace(), (1, 0), reset=True)
            fast = self.board._read_pressure(SimpleNamespace(), (101, 0))
        self.assertGreater(slow, fast)

    def test_pressure_round_trip_keeps_widths_and_export(self) -> None:
        """真实压力影响每一段，保存、撤销重做与导出后仍保持粗细变化。"""
        async def draw() -> None:
            for index, pressure in enumerate((0, 0, 1, 1)):
                event = SimpleNamespace(local_x=20 + index * 50, local_y=40, pressure=pressure)
                if index == 0:
                    await self.board._start_pointer(event)
                else:
                    await self.board._update_pointer(event)
            await self.board._end_pointer()

        self.board.set_thickness(20)
        asyncio.run(draw())
        widths = [shape.paint.stroke_width for shape in self.board.ink.shapes]
        self.assertEqual(widths, [7, 17, 27])
        with tempfile.TemporaryDirectory() as directory:
            draft = DrawingDraft(lambda: Path(directory) / "drawing.json")
            draft.save(self.board.strokes, *self.board.viewport)
            restored = FreeDrawingBoard()
            restored.restore(draft.load())
            self.assertEqual([shape.paint.stroke_width for shape in restored.ink.shapes], widths)
            target = restored.export_png(Path(directory) / "pressure.png")
            with Image.open(target) as image:
                self.assertEqual(image.getpixel((40, 50)), (255, 255, 255, 255))
                self.assertNotEqual(image.getpixel((140, 50)), (255, 255, 255, 255))
        self.assertTrue(self.board.undo())
        self.assertTrue(self.board.redo())
        self.assertEqual([shape.paint.stroke_width for shape in self.board.ink.shapes], widths)

    def test_force_event_and_next_stroke_reset_pressure(self) -> None:
        """独立压力事件更新起笔圆点和末段；下次鼠标起笔不会沿用设备状态。"""
        async def draw() -> None:
            await self.board._start_pointer(SimpleNamespace(local_x=10, local_y=10))
            self.board.detector.on_force_press_update(SimpleNamespace(pressure=0.1))
            self.assertAlmostEqual(self.board.ink.shapes[-1].paint.stroke_width, 2.25)
            await self.board._update_pointer(SimpleNamespace(local_x=30, local_y=10))
            self.board.detector.on_force_press_update(SimpleNamespace(pressure=0.9))
            await self.board._update_pointer(SimpleNamespace(local_x=50, local_y=10))
            self.assertEqual(self.board.active_stroke["pressures"], [0.1, 0.9, 0.9])
            await self.board._end_pointer()
            await self.board._start_pointer(SimpleNamespace(local_x=10, local_y=20))
            self.assertEqual(self.board.active_stroke["pressures"], [0.65])
            self.assertFalse(self.board._device_pressure_active)
            await self.board._end_pointer()

        asyncio.run(draw())

    def test_marker_stays_one_transparent_path(self) -> None:
        """荧光笔不逐段叠加透明度，也不受普通画笔压力影响。"""
        async def draw() -> None:
            self.board.set_tool("marker")
            await self.board._start_pointer(SimpleNamespace(local_x=10, local_y=10, pressure=0.1))
            for x in range(11, 60):
                await self.board._update_pointer(SimpleNamespace(local_x=x, local_y=10, pressure=0.9))
            await self.board._end_pointer()
        asyncio.run(draw())
        self.assertNotIn("pressures", self.board.strokes[0])
        self.assertEqual(len(self.board.ink.shapes), 1)
        self.board._rebuild_paths()
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

    def test_custom_canvas_size_is_persisted_and_old_draft_is_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "drawing.json"
            draft = DrawingDraft(lambda: path)
            self.assertTrue(self.board.set_canvas_size(1200, 800))
            draft.save(self.board.strokes, *self.board.viewport)
            state = draft.load_state()
            self.assertEqual((state["width"], state["height"]), (1200.0, 800.0))
            draft.save([])
            self.assertEqual(draft.load(), [])


if __name__ == "__main__":
    unittest.main()
