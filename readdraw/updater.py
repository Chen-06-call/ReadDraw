"""GitHub Releases update checking and Windows self-update helpers."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .version import APP_VERSION, GITHUB_RELEASES_API


@dataclass
class ReleaseInfo:
    tag: str
    version: str
    name: str
    notes: str
    asset_name: str
    asset_url: str


def parse_release(payload: dict) -> ReleaseInfo | None:
    """Convert GitHub's release payload to a newer downloadable release."""
    tag = str(payload.get("tag_name", "")).strip()
    if not tag or version_tuple(tag) <= version_tuple(APP_VERSION):
        return None
    assets = payload.get("assets", [])
    # The installer is also an exe, but self-update must replace the running
    # portable application with the windows-x64 build.
    asset = next(
        (
            item
            for item in assets
            if str(item.get("name", "")).lower().endswith("windows-x64.exe")
        ),
        None,
    )
    if asset is None:
        asset = next(
            (
                item
                for item in assets
                if str(item.get("name", "")).lower().endswith(".exe")
            ),
            None,
        )
    if not asset:
        return None
    asset_url = str(asset.get("browser_download_url") or "").strip()
    if not asset_url:
        return None
    return ReleaseInfo(
        tag=tag,
        version=tag.lstrip("v"),
        name=str(payload.get("name") or tag),
        notes=str(payload.get("body") or ""),
        asset_name=str(asset.get("name") or "ReadDraw.exe"),
        asset_url=asset_url,
    )


def version_tuple(value: str) -> tuple[int, ...]:
    parts = value.lstrip("v").split(".")
    result: list[int] = []
    for part in parts:
        digits = "".join(char for char in part if char.isdigit())
        result.append(int(digits or 0))
    return tuple(result or [0])


def check_latest_release(timeout: float = 8.0) -> ReleaseInfo | None:
    """Read the latest public GitHub release and return it only when newer."""
    request = urllib.request.Request(
        GITHUB_RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ReadDraw-Updater"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return parse_release(payload)


def is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False))


def download_update(release: ReleaseInfo) -> Path:
    """Download a release exe to a temporary location and return its path."""
    target = Path(tempfile.gettempdir()) / f"ReadDraw-{release.version}-update.exe"
    request = urllib.request.Request(release.asset_url, headers={"User-Agent": "ReadDraw-Updater"})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    return target


def schedule_windows_replace(downloaded_exe: Path) -> None:
    """Replace the running exe after exit, then restart it."""
    if not is_packaged():
        raise RuntimeError("源码运行模式不能自动替换 Python 解释器")
    current_exe = Path(sys.executable).resolve()
    script = Path(tempfile.gettempdir()) / "readdraw-update.cmd"
    script.write_text(
        "@echo off\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'copy /Y "{downloaded_exe}" "{current_exe}" >nul\r\n'
        f'start "" "{current_exe}"\r\n'
        f'del "%~f0"\r\n',
        encoding="utf-8",
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(["cmd.exe", "/c", str(script)], creationflags=creation_flags)
