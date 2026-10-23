"""文件选择的桌面适配层，避免 Windows 文件对话框进入 Flutter 引擎。"""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "bmp", "gif", "webp", "tif", "tiff"]


class ImageFileDialog:
    """管理独立选择器进程，应用关闭时一并结束未完成的选择。"""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._closed = False

    async def pick_file(self, fallback_picker) -> str | None:
        """系统选择器与 Flutter / SQLite 分离，文件路径通过本地 JSON 返回。"""
        if self._closed:
            return None
        if os.name != "nt":
            import flet as ft

            files = await fallback_picker.pick_files(
                dialog_title="选择要插入的图片", allow_multiple=False,
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=IMAGE_EXTENSIONS,
            )
            return files[0].path if files else None

        with tempfile.TemporaryDirectory(prefix="readdraw-picker-") as directory:
            result = Path(directory) / "selection.json"
            arguments = [sys.executable]
            if not getattr(sys, "frozen", False):
                arguments.append(str(Path(__file__).resolve().parent.parent / "main.py"))
            arguments.extend(["--select-image-file", str(result)])
            # 独立进程拥有系统对话框。即使第三方 Windows 外壳扩展发生本机异常，
            # 也不会破坏 Python 主进程或 Flutter 窗口的内存。
            process = subprocess.Popen(
                arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self._process = process
            try:
                code = await asyncio.to_thread(process.wait)
                if self._closed:
                    return None
                if code != 0:
                    raise OSError(f"图片选择窗口异常结束（0x{code & 0xFFFFFFFF:08X}），请重试")
                payload = json.loads(result.read_text(encoding="utf-8"))
                if payload.get("error"):
                    raise OSError(payload["error"])
                return payload.get("path") or None
            finally:
                if process.poll() is None:
                    process.terminate()
                    await asyncio.to_thread(process.wait)
                self._process = None

    def close(self) -> None:
        """关闭应用时结束辅助窗口，避免后台残留一个等待选择的进程。"""
        self._closed = True
        if self._process and self._process.poll() is None:
            self._process.terminate()


def run_image_picker_helper(result_path: str) -> None:
    """只在独立进程主线程运行；调用方负责捕获退出码及读取结果。"""
    try:
        payload = {"path": _select_windows_image()}
    except Exception as exc:
        payload = {"error": str(exc)}
    Path(result_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _select_windows_image() -> str | None:
    """调用 Unicode 系统文件选择框；取消返回 None，系统错误明确抛出。"""
    import ctypes
    from ctypes import wintypes

    class OpenFileName(ctypes.Structure):
        # 结构字段按 Windows OPENFILENAMEW 定义，指针字段保持本机位宽。
        _fields_ = [
            ("lStructSize", wintypes.DWORD), ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE), ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR), ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD), ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD), ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD), ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR), ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD), ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR), ("lCustData", ctypes.c_ssize_t),
            ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", ctypes.c_void_p), ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    dialog = ctypes.WinDLL("comdlg32", use_last_error=True)
    dialog.GetOpenFileNameW.argtypes = [ctypes.POINTER(OpenFileName)]
    dialog.GetOpenFileNameW.restype = wintypes.BOOL
    dialog.CommDlgExtendedError.restype = wintypes.DWORD
    ole = ctypes.OleDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    # 每次与本线程的初始化成对释放，避免在线程池中遗留 COM 状态。
    initialized = ole.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    if initialized < 0:
        raise OSError(f"无法初始化图片选择窗口：0x{initialized & 0xFFFFFFFF:08X}")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        pattern = ";".join(f"*.{extension}" for extension in IMAGE_EXTENSIONS)
        options = OpenFileName(
            lStructSize=ctypes.sizeof(OpenFileName),
            lpstrFilter=f"图片文件\0{pattern}\0所有文件\0*.*\0\0",
            nFilterIndex=1,
            lpstrFile=ctypes.cast(buffer, wintypes.LPWSTR),
            nMaxFile=len(buffer),
            lpstrTitle="ReadDraw - 选择要插入的图片",
            # 文件必须存在，不改变工作目录，也不写入 Windows 最近文件列表。
            Flags=0x00080000 | 0x00001000 | 0x00000800 | 0x00000008 | 0x02000000,
        )
        if dialog.GetOpenFileNameW(ctypes.byref(options)):
            return buffer.value
        error = dialog.CommDlgExtendedError()
        if error:
            raise OSError(f"打开图片选择窗口失败：0x{error:08X}")
        return None
    finally:
        ole.CoUninitialize()
