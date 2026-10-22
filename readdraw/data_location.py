"""Safe, copy-first relocation of a library and its managed files."""

from pathlib import Path
import shutil
import sqlite3
import tempfile

from . import config
from .storage import Store


def migrate_data_dir(store: Store, destination: str | Path) -> Path:
    """Keep the source intact; never merge with or overwrite another library.

    SQLite's backup API includes committed WAL data. References to managed
    files are rewritten in the backup; externally imported books stay in place.
    The settings pointer changes only after a complete copy can be opened.
    """
    if store.database_path is None:
        raise ValueError("内存数据库无法迁移")
    source = store.database_path.parent.resolve()
    target = Path(destination).expanduser().resolve()
    if target == source:
        return target
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("请选择当前数据目录以外的独立文件夹")
    target.mkdir(parents=True, exist_ok=True)
    database_name = store.database_path.name
    if any(target.iterdir()):
        raise ValueError("请选择一个空文件夹，避免覆盖已有文件")

    with tempfile.TemporaryDirectory(prefix=".readdraw-migration-", dir=target) as temporary:
        stage = Path(temporary)
        excluded = {database_name, database_name + "-wal", database_name + "-shm", database_name + "-journal", "settings.json", "settings.json.tmp", "logs"}
        for child in source.iterdir():
            if child.name in excluded:
                continue
            if child.is_dir():
                shutil.copytree(child, stage / child.name)
            else:
                shutil.copy2(child, stage / child.name)
        copied = sqlite3.connect(stage / database_name)
        try:
            with copied:
                store.db.backup(copied)
                for table in ("books", "attachments"):
                    for record_id, file_path in copied.execute(f"SELECT id, path FROM {table}").fetchall():
                        original = Path(file_path).resolve()
                        if original.is_relative_to(source):
                            relocated = target / original.relative_to(source)
                            copied.execute(f"UPDATE {table} SET path=? WHERE id=?", (str(relocated), record_id))
                if copied.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise OSError("复制后的数据库校验失败")
        finally:
            copied.close()
        for child in stage.iterdir():
            child.replace(target / child.name)

    # Check the final paths before publishing the setting. A failed write keeps
    # the running library and its original database open and usable.
    candidate = Store(target / store.database_path.name)
    candidate.close()
    config.save_data_dir(target)
    return target
