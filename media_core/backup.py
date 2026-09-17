"""Экспорт / импорт настроек и истории."""

from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from contextlib import closing
from pathlib import Path

from media_core import database as dbmod
from media_core.config import BASE_DIR, DB_FILE
from media_core.constants import APP_VERSION
from media_core.settings_store import _save as save_settings, get_all, settings_transaction, update_settings

SETTINGS_PATH = BASE_DIR / "config" / "app_settings.json"


def _snapshot_database(source: Path, destination: Path) -> None:
    """Include WAL and restore transactionally rather than overwrite an open file."""
    deadline = time.monotonic() + 10

    def progress(status, remaining, total):
        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) and time.monotonic() > deadline:
            raise TimeoutError("База данных занята. Повторите операцию позже.")

    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst, pages=256, progress=progress, sleep=0.05)


def _validate_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("history.db: повреждённая база данных")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(history)")}
        if not {"id", "url", "title", "platform", "created_at"}.issubset(columns):
            raise ValueError("history.db: это не база истории Media App")

    # Migrate and validate staging, never the active database.
    dbmod.init_db(str(path))
    reference = path.with_name("expected_schema.db")
    dbmod.init_db(str(reference))
    with closing(sqlite3.connect(reference)) as expected, closing(sqlite3.connect(path)) as candidate:
        tables = expected.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (name,) in tables:
            required = {row[1] for row in expected.execute(f'PRAGMA table_info("{name}")')}
            actual = {row[1] for row in candidate.execute(f'PRAGMA table_info("{name}")')}
            if not required.issubset(actual):
                raise ValueError(f"history.db: несовместимая таблица {name}")


def export_backup_zip() -> Path:
    """Создать zip во временной папке; вызывающий отдаёт FileResponse и может удалить."""
    tmp = Path(tempfile.mkdtemp(prefix="media_backup_"))
    zip_path = tmp / f"MediaApp-backup-{time.strftime('%Y%m%d-%H%M%S')}.zip"

    settings = dict(get_all())
    # не уносим токен расширения в бэкап
    settings.pop("extension_token", None)

    try:
        db = Path(DB_FILE)
        snapshot = tmp / "history.db"
        if db.is_file():
            _snapshot_database(db, snapshot)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps({
                "app": "MediaApp", "version": APP_VERSION, "created_at": time.time(),
            }, ensure_ascii=False, indent=2))
            zf.writestr("app_settings.json", json.dumps(settings, ensure_ascii=False, indent=2))
            if snapshot.is_file():
                zf.write(snapshot, arcname="history.db")
        return zip_path
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def import_backup_zip(raw: bytes) -> dict:
    if not raw:
        return {"ok": False, "error": "Пустой файл"}

    backup_dir = None
    try:
        with tempfile.TemporaryDirectory(prefix="media_import_") as td:
            tdir = Path(td)
            hist_file = tdir / "history.db"
            data = None
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = set(zf.namelist())
                if "app_settings.json" not in names and "history.db" not in names:
                    raise ValueError("В архиве нет app_settings.json или history.db")
                if "app_settings.json" in names:
                    data = json.loads(zf.read("app_settings.json"))
                    if not isinstance(data, dict):
                        raise ValueError("settings: не объект")
                    data.pop("extension_token", None)
                if "history.db" in names:
                    with zf.open("history.db") as source, hist_file.open("wb") as dest:
                        shutil.copyfileobj(source, dest)
            if hist_file.is_file():
                _validate_database(hist_file)

            with settings_transaction():
                config_dir = BASE_DIR / "config"
                config_dir.mkdir(parents=True, exist_ok=True)
                backup_dir = Path(tempfile.mkdtemp(prefix="backup_before_import_", dir=config_dir))
                original = get_all()
                if SETTINGS_PATH.is_file():
                    shutil.copy2(SETTINGS_PATH, backup_dir / "app_settings.json")
                db = Path(DB_FILE)
                if db.is_file():
                    _snapshot_database(db, backup_dir / "history.db")
                settings_changed = False
                try:
                    if data is not None:
                        update_settings(**data)
                        settings_changed = True
                    if hist_file.is_file():
                        _snapshot_database(hist_file, db)
                except Exception:
                    if settings_changed:
                        save_settings(original)
                    raise
        return {"ok": True, "message": "Бэкап восстановлен", "backup_dir": str(backup_dir)}
    except (OSError, sqlite3.Error, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        result = {"ok": False, "error": str(exc)}
        if backup_dir is not None:
            result["backup_dir"] = str(backup_dir)
        return result
