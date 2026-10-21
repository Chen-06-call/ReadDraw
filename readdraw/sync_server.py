"""FastAPI LAN synchronization service."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI

from .storage import Store


def create_app(database_path=None) -> FastAPI:
    app = FastAPI(title="ReadDraw Sync", version="1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "readdraw-sync"}

    @app.get("/api/snapshot")
    def snapshot() -> dict[str, Any]:
        store = Store(database_path)
        try:
            return store.export_snapshot()
        finally:
            store.close()

    @app.post("/api/snapshot")
    def import_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        store = Store(database_path)
        try:
            store.import_snapshot(payload)
            return {"ok": True, "books": len(payload.get("books", []))}
        finally:
            store.close()

    return app


class SyncServer:
    """Owns a daemon thread so the desktop UI can start/stop LAN sync."""

    def __init__(self, database_path=None, host: str = "0.0.0.0", port: int = 8765) -> None:
        self.database_path = database_path
        self.host = host
        self.port = port
        self._server = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        import uvicorn

        config = uvicorn.Config(create_app(self.database_path), host=self.host, port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="readdraw-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
