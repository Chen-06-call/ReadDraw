"""验证色盘连续选色、明暗和手动输入，不依赖系统颜色选择窗口。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from readdraw.color_picker import ColorPicker, WHEEL_RADIUS, WHEEL_SIZE, normalize_hex_color


class ColorPickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_wheel_brightness_and_hex_use_same_color(self) -> None:
        picker = ColorPicker("#217567", Mock(), Mock())
        # 圆周右侧为纯红，圆心为白；明暗滑杆可进一步选择灰和黑。
        picker.brightness.on_change(SimpleNamespace(control=SimpleNamespace(value=1)))
        await picker.detector.on_pan_down(SimpleNamespace(
            local_position=SimpleNamespace(x=WHEEL_SIZE / 2 + WHEEL_RADIUS, y=WHEEL_SIZE / 2)))
        self.assertEqual(picker.color, "#FF0000")
        await picker.detector.on_pan_update(SimpleNamespace(
            local_position=SimpleNamespace(x=WHEEL_SIZE / 2, y=WHEEL_SIZE / 2)))
        picker.brightness.on_change(SimpleNamespace(control=SimpleNamespace(value=1)))
        self.assertEqual(picker.color, "#FFFFFF")
        picker.brightness.on_change(SimpleNamespace(control=SimpleNamespace(value=0)))
        self.assertEqual(picker.color, "#000000")
        picker.hex_field.value = "2e90fa"
        picker.hex_field.on_submit(None)
        self.assertEqual(picker.color, "#2E90FA")
        self.assertEqual(picker.preview.bgcolor, picker.color)
        self.assertTrue(picker.wheel.src.startswith(b"\x89PNG"))

    async def test_confirm_cancel_and_invalid_input(self) -> None:
        applied, closed = Mock(), Mock()
        picker = ColorPicker("#217567", applied, closed)
        picker.dialog.actions[0].on_click(None)
        applied.assert_not_called()
        closed.assert_called_once()
        picker.hex_field.value = "#FA10B8"
        picker.dialog.actions[1].on_click(None)
        applied.assert_called_once_with("#FA10B8")
        with self.assertRaises(ValueError):
            normalize_hex_color("#GGHHII")

    async def test_outside_wheel_clamps_to_edge(self) -> None:
        picker = ColorPicker("#FF0000", Mock(), Mock())
        await picker.detector.on_pan_update(SimpleNamespace(
            local_position=SimpleNamespace(x=WHEEL_SIZE * 2, y=WHEEL_SIZE / 2)))
        self.assertEqual(picker.saturation, 1)
        self.assertEqual(picker.color, "#FF0000")
