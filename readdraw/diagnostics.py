"""Persistent local diagnostics for windowed builds without a console."""

import atexit
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import sys
import threading

from . import config


def configure_logging() -> None:
    directory = config.DEFAULT_APP_DIR / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(directory / "ReadDraw.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    log = logging.getLogger("readdraw")

    def uncaught(kind, value, traceback):
        log.critical("Unhandled exception", exc_info=(kind, value, traceback))

    sys.excepthook = uncaught
    threading.excepthook = lambda args: uncaught(args.exc_type, args.exc_value, args.exc_traceback)
    native_log = (directory / "native-crash.log").open("a", encoding="utf-8")
    faulthandler.enable(native_log)
    # Keep the file handle alive for faulthandler, then release it on shutdown.
    atexit.register(native_log.close)
    atexit.register(faulthandler.disable)
    log.info("Starting ReadDraw; data directory: %s", config.APP_DIR)
