"""Application paths and rendering limits."""

import os
import json
import sys
from pathlib import Path


def _writable_candidates() -> list[Path]:
    """Return a writable per-user data directory, with a development fallback."""
    candidates = []
    for variable in ("APPDATA", "LOCALAPPDATA"):
        value = os.environ.get(variable)
        if value:
            candidates.append(Path(value) / "ReadDraw")
    # A one-file executable extracts __file__ into a disposable _MEI folder.
    # Never put user data there, even if the per-user folders are unavailable.
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    candidates.append(root / ".readdraw-data")

    return candidates


def choose_app_dir() -> Path:
    """Return the default writable per-user data directory."""
    for candidate in _writable_candidates():
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            continue
    raise OSError("无法创建 ReadDraw 数据目录")


DEFAULT_APP_DIR = choose_app_dir()
SETTINGS_PATH = DEFAULT_APP_DIR / "settings.json"


def load_settings() -> dict:
    """Read user preferences without allowing a malformed file to break startup."""
    try:
        payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def get_setting(name: str, default=None):
    return load_settings().get(name, default)


def _configured_app_dir() -> Path:
    override = os.environ.get("READDRAW_DATA_DIR")
    if override:
        path = Path(override).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    try:
        configured = str(get_setting("data_dir", "")).strip()
        if configured:
            candidate = Path(configured).expanduser()
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
    except (OSError, ValueError, TypeError):
        pass
    return DEFAULT_APP_DIR


APP_DIR = _configured_app_dir()
DB_PATH = APP_DIR / "readdraw.sqlite3"
ATTACHMENTS_DIR = APP_DIR / "attachments"
MAX_PAGE_WIDTH = 760
MAX_PAGE_HEIGHT = 900
DEFAULT_BACKGROUND = "#E8ECF1"
DEFAULT_PAGE_ANIMATION_ENABLED = True
BACKGROUND_OPTIONS = {
    "浅灰": "#E8ECF1",
    "暖白": "#FFFDF7",
    "浅蓝": "#EEF4FF",
    "深灰": "#263238",
}


def save_settings(**updates) -> None:
    """Merge preferences so changing one setting keeps all other settings."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    settings.update(updates)
    temporary = SETTINGS_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SETTINGS_PATH)


def save_data_dir(target: Path) -> None:
    """Persist a directory atomically, then switch runtime paths."""
    global APP_DIR, DB_PATH, ATTACHMENTS_DIR
    save_settings(data_dir=str(target))
    APP_DIR = target
    DB_PATH = target / "readdraw.sqlite3"
    ATTACHMENTS_DIR = target / "attachments"
