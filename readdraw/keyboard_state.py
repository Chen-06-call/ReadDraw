"""读取滚轮触发时的修饰键状态，不参与界面布局。"""

import sys


def is_alt_pressed(fallback: bool = False) -> bool:
    """Windows 读取即时状态，避免页面只发按下事件造成 Alt 松开后仍缩放。"""
    if sys.platform != "win32":
        return fallback
    import ctypes

    # VK_MENU 表示左右 Alt 键；最高位表示当前仍处于按下状态。
    return bool(ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000)


def is_control_pressed(fallback: bool = False) -> bool:
    """读取 Ctrl 即时状态，让形状约束跟随按下和松开动作。"""
    if sys.platform != "win32":
        return fallback
    import ctypes

    # VK_CONTROL 表示左右 Ctrl 键；最高位表示当前仍处于按下状态。
    return bool(ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000)
