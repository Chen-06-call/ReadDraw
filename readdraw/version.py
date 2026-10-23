"""Application and GitHub release version information."""

import os


APP_VERSION = os.environ.get("READDRAW_VERSION", "0.1.1").lstrip("v")
APP_TAG = f"v{APP_VERSION}"
GITHUB_REPOSITORY = "Chen-06-call/ReadDraw"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
