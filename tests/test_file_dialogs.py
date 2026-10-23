"""验证文件选择辅助进程的通信、异常隔离和关闭行为，不打开真实窗口。"""

import asyncio
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

from readdraw.file_dialogs import ImageFileDialog


@unittest.skipUnless(sys.platform == "win32", "Windows 选择器辅助进程")
class ImageFileDialogTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_and_packaged_helpers_return_unicode_paths(self) -> None:
        for frozen in (False, True):
            with self.subTest(frozen=frozen):
                def launch(arguments, **_kwargs):
                    Path(arguments[-1]).write_text(
                        json.dumps({"path": "C:/图片/示例.png"}), encoding="utf-8"
                    )
                    return Mock(wait=Mock(return_value=0), poll=Mock(return_value=0))

                with (
                    patch.object(sys, "frozen", frozen, create=True),
                    patch("readdraw.file_dialogs.subprocess.Popen", side_effect=launch) as popen,
                ):
                    selected = await ImageFileDialog().pick_file(None)
                self.assertEqual(selected, "C:/图片/示例.png")
                arguments = popen.call_args.args[0]
                self.assertEqual(arguments[0], sys.executable)
                self.assertEqual(arguments[-2], "--select-image-file")
                self.assertEqual(len(arguments), 3 if frozen else 4)

    async def test_native_helper_failure_becomes_recoverable_error(self) -> None:
        process = Mock(wait=Mock(return_value=0xC0000005), poll=Mock(return_value=0xC0000005))
        picker = ImageFileDialog()
        with patch("readdraw.file_dialogs.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(OSError, "C0000005"):
                await picker.pick_file(None)
        self.assertIsNone(picker._process)
        self.assertFalse(picker._closed)

    async def test_close_terminates_pending_helper_without_leaving_it_running(self) -> None:
        finished = threading.Event()
        process = Mock()
        process.wait.side_effect = lambda: (finished.wait(5), 1)[1]
        process.poll.side_effect = lambda: 1 if finished.is_set() else None
        process.terminate.side_effect = finished.set
        picker = ImageFileDialog()
        with patch("readdraw.file_dialogs.subprocess.Popen", return_value=process):
            task = asyncio.create_task(picker.pick_file(None))
            await asyncio.sleep(0)
            picker.close()
            self.assertIsNone(await asyncio.wait_for(task, timeout=3))
        process.terminate.assert_called_once()
        self.assertIsNone(picker._process)


if __name__ == "__main__":
    unittest.main()
