"""Windows Explorer drop bridge used by the packaged desktop application."""

from __future__ import annotations

import atexit
import logging
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable


DROP_PORT = 47831


class NativeDropBridge:
    """Run the tiny native helper that forwards dropped document paths."""

    def __init__(self, on_files: Callable[[list[str]], None]) -> None:
        self.on_files = on_files
        self.process: subprocess.Popen | None = None
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.socket: socket.socket | None = None

    def start(self) -> None:
        if os.name != "nt":
            return
        helper, hook = self._binaries()
        if not helper.exists() or not hook.exists():
            return
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind(("127.0.0.1", 0))
            port = self.socket.getsockname()[1]
            self.socket.settimeout(0.5)
            self.thread = threading.Thread(target=self._listen, daemon=True)
            self.thread.start()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.process = subprocess.Popen(
                [str(helper), str(hook), str(port), str(os.getpid())],
                creationflags=flags,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            atexit.register(self.stop)
        except OSError:
            logging.getLogger(__name__).exception("Unable to start native drop bridge")
            self.stop()

    def stop(self) -> None:
        self.stop_event.set()
        if self.socket:
            self.socket.close()
            self.socket = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.process and self.process.poll() is None:
            # Let the helper unhook and unload its DLL before returning.
            if self.process.stdin:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3.0)
        self.process = None

    def _listen(self) -> None:
        while not self.stop_event.is_set() and self.socket:
            try:
                data, _ = self.socket.recvfrom(65535)
            except (TimeoutError, OSError):
                continue
            path = data.decode("utf-8", errors="replace").strip("\x00\r\n")
            if path:
                try:
                    self.on_files([path])
                except Exception:
                    logging.getLogger(__name__).exception("Unable to import dropped file")
                    continue

    @staticmethod
    def _binaries() -> tuple[Path, Path]:
        roots = [Path(getattr(sys, "_MEIPASS", "")), Path(__file__).resolve().parent.parent]
        for root in roots:
            if not root:
                continue
            for directory in (root, root / "native"):
                helper = directory / "drop_helper.exe"
                hook = directory / "drop_hook.dll"
                if helper.exists() and hook.exists():
                    return helper, hook
        return Path(""), Path("")
