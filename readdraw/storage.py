"""SQLite persistence for local books and page drawing annotations."""

from __future__ import annotations

import json
import base64
import shutil
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from pathlib import Path

from . import config
from .models import Attachment, Book, TextAnnotation


class Store:
    """Small storage facade that can later be replaced by a sync repository."""

    def __init__(self, database_path=None) -> None:
        database_path = database_path or config.DB_PATH
        self.database_path = Path(database_path) if database_path != ":memory:" else None
        if self.database_path is not None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.attachment_dir = config.ATTACHMENTS_DIR if self.database_path is None else self.database_path.parent / "attachments"
        self.db = sqlite3.connect(database_path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS books (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
            pages INTEGER NOT NULL, current_page INTEGER NOT NULL DEFAULT 0,
            added_at TEXT NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS page_annotations (
            book_id TEXT NOT NULL, page INTEGER NOT NULL, strokes TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY(book_id, page),
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE)""")
        self._migrate_books()
        self.db.execute("""CREATE TABLE IF NOT EXISTS text_annotations (
            id TEXT PRIMARY KEY, book_id TEXT NOT NULL, page INTEGER NOT NULL,
            kind TEXT NOT NULL, content TEXT NOT NULL, quote TEXT NOT NULL DEFAULT '',
            color TEXT NOT NULL DEFAULT '#FDE68A', created_at TEXT NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY, book_id TEXT NOT NULL, page INTEGER NOT NULL,
            path TEXT NOT NULL, name TEXT NOT NULL, x INTEGER NOT NULL DEFAULT 24,
            y INTEGER NOT NULL DEFAULT 24, width INTEGER NOT NULL DEFAULT 240,
            height INTEGER NOT NULL DEFAULT 180, created_at TEXT NOT NULL)""")
        self.db.commit()

    def _migrate_books(self) -> None:
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(books)")}
        if "format" not in columns:
            self.db.execute("ALTER TABLE books ADD COLUMN format TEXT NOT NULL DEFAULT 'pdf'")

    def books(self) -> list[Book]:
        rows = self.db.execute("SELECT * FROM books ORDER BY added_at DESC").fetchall()
        return [Book(**dict(row)) for row in rows]

    def add_book(self, title: str, path: str, pages: int, book_format: str = "pdf") -> Book:
        book = Book(str(uuid.uuid4()), title, path, pages, 0, datetime.now().isoformat(timespec="seconds"), book_format)
        self.db.execute("""INSERT OR REPLACE INTO books
            (id,title,path,pages,current_page,added_at,format) VALUES(?,?,?,?,?,?,?)""", tuple(book.__dict__.values()))
        self.db.commit()
        return book

    def update_page(self, book_id: str, page: int) -> None:
        self.db.execute("UPDATE books SET current_page=? WHERE id=?", (page, book_id))
        self.db.commit()

    def get_strokes(self, book_id: str, page: int) -> list[dict[str, Any]]:
        row = self.db.execute("SELECT strokes FROM page_annotations WHERE book_id=? AND page=?", (book_id, page)).fetchone()
        return json.loads(row[0]) if row else []

    def save_strokes(self, book_id: str, page: int, strokes: list[dict[str, Any]]) -> None:
        self.db.execute("""INSERT INTO page_annotations(book_id,page,strokes,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(book_id,page) DO UPDATE SET strokes=excluded.strokes, updated_at=excluded.updated_at""",
            (book_id, page, json.dumps(strokes), datetime.now().isoformat(timespec="seconds")))
        self.db.commit()

    def add_text_annotation(self, book_id: str, page: int, kind: str, content: str, quote: str = "", color: str = "#FDE68A") -> TextAnnotation:
        annotation = TextAnnotation(str(uuid.uuid4()), book_id, page, kind, content, quote, color, datetime.now().isoformat(timespec="seconds"))
        self.db.execute("INSERT INTO text_annotations VALUES(?,?,?,?,?,?,?,?)", tuple(annotation.__dict__.values()))
        self.db.commit()
        return annotation

    def text_annotations(self, book_id: str, page: int) -> list[TextAnnotation]:
        rows = self.db.execute("SELECT * FROM text_annotations WHERE book_id=? AND page=? ORDER BY created_at", (book_id, page)).fetchall()
        return [TextAnnotation(**dict(row)) for row in rows]

    def add_attachment(self, book_id: str, page: int, source_path: str) -> Attachment:
        self.attachment_dir.mkdir(parents=True, exist_ok=True)
        attachment_id = str(uuid.uuid4())
        source = Path(source_path)
        target = self.attachment_dir / f"{attachment_id}{source.suffix.lower()}"
        shutil.copy2(source, target)
        attachment = Attachment(attachment_id, book_id, page, str(target), source.name, 24, 24, 240, 180, datetime.now().isoformat(timespec="seconds"))
        self.db.execute("INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?,?,?)", tuple(attachment.__dict__.values()))
        self.db.commit()
        return attachment

    def attachments(self, book_id: str, page: int) -> list[Attachment]:
        rows = self.db.execute("SELECT * FROM attachments WHERE book_id=? AND page=? ORDER BY created_at", (book_id, page)).fetchall()
        return [Attachment(**dict(row)) for row in rows]

    def update_attachment_position(self, attachment_id: str, x: int, y: int) -> None:
        """保存图片附件在书页坐标中的位置。"""
        self.db.execute("UPDATE attachments SET x=?, y=? WHERE id=?", (int(x), int(y), attachment_id))
        self.db.commit()

    def export_snapshot(self) -> dict[str, Any]:
        snapshot = {
            "books": [dict(row) for row in self.db.execute("SELECT * FROM books")],
            "page_annotations": [dict(row) for row in self.db.execute("SELECT * FROM page_annotations")],
            "text_annotations": [dict(row) for row in self.db.execute("SELECT * FROM text_annotations")],
            "attachments": [],
        }
        for row in self.db.execute("SELECT * FROM attachments"):
            item = dict(row)
            file_path = Path(item["path"])
            item["data_base64"] = base64.b64encode(file_path.read_bytes()).decode("ascii") if file_path.exists() else ""
            snapshot["attachments"].append(item)
        return snapshot

    def import_snapshot(self, snapshot: dict[str, Any]) -> None:
        for row in snapshot.get("books", []):
            columns = ["id", "title", "path", "pages", "current_page", "added_at", "format"]
            values = [row.get(column, "pdf" if column == "format" else None) for column in columns]
            self.db.execute(f"INSERT OR REPLACE INTO books({','.join(columns)}) VALUES(?,?,?,?,?,?,?)", values)
        for row in snapshot.get("page_annotations", []):
            self.db.execute("INSERT OR REPLACE INTO page_annotations VALUES(?,?,?,?)", [row[k] for k in ("book_id", "page", "strokes", "updated_at")])
        for row in snapshot.get("text_annotations", []):
            self.db.execute("INSERT OR REPLACE INTO text_annotations VALUES(?,?,?,?,?,?,?,?)", [row[k] for k in ("id", "book_id", "page", "kind", "content", "quote", "color", "created_at")])
        for row in snapshot.get("attachments", []):
            data = row.get("data_base64", "")
            if data:
                path = Path(row["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(data))
            self.db.execute("INSERT OR REPLACE INTO attachments VALUES(?,?,?,?,?,?,?,?,?,?)", [row[k] for k in ("id", "book_id", "page", "path", "name", "x", "y", "width", "height", "created_at")])
        self.db.commit()

    def close(self) -> None:
        self.db.close()
