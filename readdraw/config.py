"""Application paths and rendering limits."""

import os
from pathlib import Path


def choose_app_dir() -> Path:
    """Return a writable per-user data directory, with a development fallback."""
    candidates = []
    for variable in ("APPDATA", "LOCALAPPDATA"):
        value = os.environ.get(variable)
        if value:
            candidates.append(Path(value) / "ReadDraw")
    candidates.append(Path(__file__).resolve().parent.parent / ".readdraw-data")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            continue
    raise OSError("无法创建 ReadDraw 数据目录")


APP_DIR = choose_app_dir()
DB_PATH = APP_DIR / "readdraw.sqlite3"
ATTACHMENTS_DIR = APP_DIR / "attachments"
MAX_PAGE_WIDTH = 760
MAX_PAGE_HEIGHT = 900
