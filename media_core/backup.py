"""Экспорт / импорт настроек и истории."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from media_core.config import BASE_DIR, DB_FILE
from media_core.constants import APP_VERSION
from media_core.settings_store import get_all, get_extension_token, update_settings

SETTINGS_PATH = BASE_DIR / "config" / "app_settings.json"


def export_backup_zip() -> Path:
    """Создать zip во временной папке; вызывающий отдаёт FileResponse и может удалить."""
    tmp = Path(tempfile.mkdtemp(prefix="media_backup_"))
    zip_path = tmp / f"MediaApp-backup-{time.strftime('%Y%m%d-%H%M%S')}.zip"

    settings = dict(get_all())
    # не уносим токен расширения в бэкап
    settings.pop("extension_token", None)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {"app": "MediaApp", "version": APP_VERSION, "created_at": time.time()},
                ensure_ascii=False,
                indent=2,
            ),
        )
        zf.writestr("app_settings.json", json.dumps(settings, ensure_ascii=False, indent=2))
        db = Path(DB_FILE)
        if db.is_file():
            zf.write(db, arcname="history.db")
    return zip_path


def import_backup_zip(raw: bytes) -> dict:
    if not raw:
        return {"ok": False, "error": "Пустой файл"}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = BASE_DIR / "config" / f"backup_before_import_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # сохранить текущее
    if SETTINGS_PATH.is_file():
        shutil.copy2(SETTINGS_PATH, backup_dir / "app_settings.json")
    db = Path(DB_FILE)
    if db.is_file():
        shutil.copy2(db, backup_dir / "history.db")

    with tempfile.TemporaryDirectory(prefix="media_import_") as td:
        tdir = Path(td)
        zip_path = tdir / "in.zip"
        zip_path.write_bytes(raw)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = set(zf.namelist())
                if "app_settings.json" not in names and "history.db" not in names:
                    return {"ok": False, "error": "В архиве нет app_settings.json или history.db"}
                zf.extractall(tdir)
        except zipfile.BadZipFile:
            return {"ok": False, "error": "Некорректный zip"}

        settings_file = tdir / "app_settings.json"
        hist_file = tdir / "history.db"
        token = get_extension_token()

        if settings_file.is_file():
            try:
                data = json.loads(settings_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                return {"ok": False, "error": f"settings: {e}"}
            if not isinstance(data, dict):
                return {"ok": False, "error": "settings: не объект"}
            data.pop("extension_token", None)
            # replace settings but keep local extension token
            update_settings(**{k: v for k, v in data.items() if k != "extension_token"})
            if token:
                update_settings(extension_token=token)

        if hist_file.is_file():
            # заменить БД (нужно закрыть соединения — sqlite обычно ок после копирования)
            try:
                shutil.copy2(hist_file, db)
            except OSError as e:
                return {"ok": False, "error": f"history.db: {e}"}
            # переинициализировать схему на случай старого бэкапа
            from media_core import database as dbmod

            dbmod.init_db()

    return {
        "ok": True,
        "message": "Бэкап восстановлен",
        "backup_dir": str(backup_dir),
    }
