"""Storage regressions using fresh SQLite files and settings for every test."""

import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import media_core


def load_module(name):
    source = Path(__file__).resolve().parents[1] / "media_core" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"storage_test_{name}", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StorageReliabilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="media-storage-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        config = types.ModuleType("media_core.config")
        config.BASE_DIR = self.root
        config.DB_FILE = str(self.root / "history.db")
        config.DOWNLOAD_DIR = str(self.root / "downloads")
        config.HISTORY_LIMIT = 500
        config.PROXY_LIST = []
        self.enterContext(patch.dict(sys.modules, {"media_core.config": config}))
        self.settings = load_module("settings_store")
        self.db = load_module("database")
        self.enterContext(patch.dict(sys.modules, {
            "media_core.settings_store": self.settings, "media_core.database": self.db,
        }))
        self.enterContext(patch.object(media_core, "database", self.db, create=True))
        self.backup = load_module("backup")
        self.settings.update_settings(theme="dark", extension_token="local-secret")
        self.db.history_add("old-url", "Original", "test")

    def archive(self, entries):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        return data.getvalue()

    def test_invalid_database_import_does_not_change_settings_or_history(self):
        payload = self.archive({
            "app_settings.json": json.dumps({"theme": "light"}),
            "history.db": b"not a SQLite database",
        })
        result = self.backup.import_backup_zip(payload)
        self.assertFalse(result["ok"])
        self.assertEqual(self.settings.get_all()["theme"], "dark")
        self.assertEqual(self.db.history_list()[0]["title"], "Original")

    def test_unrelated_sqlite_database_is_rejected(self):
        other = self.root / "unrelated.db"
        with closing(sqlite3.connect(other)) as conn:
            conn.execute("CREATE TABLE unrelated (value TEXT)")
            conn.commit()
        result = self.backup.import_backup_zip(self.archive({"history.db": other.read_bytes()}))
        self.assertFalse(result["ok"])
        self.assertEqual(self.db.history_list()[0]["title"], "Original")

    def test_export_includes_committed_wal_rows(self):
        connection = sqlite3.connect(self.db.DB_FILE)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("INSERT INTO history (url, title) VALUES ('wal-url', 'WAL title')")
        connection.commit()
        output = self.backup.export_backup_zip()
        self.addCleanup(__import__("shutil").rmtree, output.parent)
        extracted = self.root / "exported.db"
        with zipfile.ZipFile(output) as archive:
            extracted.write_bytes(archive.read("history.db"))
            self.assertNotIn("extension_token", json.loads(archive.read("app_settings.json")))
        with closing(sqlite3.connect(extracted)) as snapshot:
            row = snapshot.execute("SELECT title FROM history WHERE url='wal-url'").fetchone()
        self.assertEqual(row, ("WAL title",))

    def test_roundtrip_restores_history_preserves_local_token(self):
        output = self.backup.export_backup_zip()
        self.addCleanup(__import__("shutil").rmtree, output.parent)
        raw = output.read_bytes()
        self.db.history_add("new-url", "New", "test")
        self.settings.update_settings(theme="light")
        result = self.backup.import_backup_zip(raw)
        self.assertTrue(result["ok"], result)
        self.assertEqual([r["title"] for r in self.db.history_list()], ["Original"])
        self.assertEqual(self.settings.get_all()["theme"], "dark")
        self.assertEqual(self.settings.get_extension_token(), "local-secret")

    def test_restore_failure_rolls_settings_back(self):
        output = self.backup.export_backup_zip()
        self.addCleanup(__import__("shutil").rmtree, output.parent)
        self.settings.update_settings(theme="light")
        self.db.history_add("new-url", "New", "test")
        real_snapshot = self.backup._snapshot_database

        def snapshot(source, destination):
            if destination == Path(self.db.DB_FILE):
                raise sqlite3.OperationalError("database is locked")
            return real_snapshot(source, destination)

        with patch.object(self.backup, "_snapshot_database", side_effect=snapshot):
            result = self.backup.import_backup_zip(output.read_bytes())
        self.assertFalse(result["ok"])
        self.assertEqual(self.settings.get_all()["theme"], "light")
        self.assertEqual(self.db.history_list()[0]["title"], "New")
        self.assertTrue((Path(result["backup_dir"]) / "history.db").exists())

    def test_restore_with_open_wal_connection_is_consistent(self):
        output = self.backup.export_backup_zip()
        self.addCleanup(__import__("shutil").rmtree, output.parent)
        with closing(sqlite3.connect(self.db.DB_FILE)) as live:
            live.execute("PRAGMA journal_mode=WAL")
            live.execute("PRAGMA wal_autocheckpoint=0")
            live.execute("INSERT INTO history(url,title) VALUES ('later','Later')")
            live.commit()
            result = self.backup.import_backup_zip(output.read_bytes())
            self.assertTrue(result["ok"], result)
            self.assertEqual(live.execute("SELECT title FROM history").fetchall(), [("Original",)])
            self.assertEqual(live.execute("PRAGMA integrity_check").fetchone(), ("ok",))

    def test_concurrent_settings_updates_do_not_lose_values(self):
        first_read = threading.Event()
        second_started = threading.Event()
        real_load = self.settings._load

        def load():
            result = real_load()
            if threading.current_thread().name == "settings-first":
                first_read.set()
                self.assertTrue(second_started.wait(2))
                # In old code both writers read the same snapshot; with the
                # settings lock the second writer waits outside this function.
                threading.Event().wait(0.05)
            return result

        def second():
            first_read.wait(2)
            second_started.set()
            self.settings.update_settings(accent="red")

        with patch.object(self.settings, "_load", side_effect=load):
            a = threading.Thread(name="settings-first", target=lambda: self.settings.update_settings(theme="light"))
            b = threading.Thread(target=second)
            a.start()
            b.start()
            a.join(3)
            b.join(3)
        self.assertFalse(a.is_alive() or b.is_alive())
        self.assertEqual(self.settings.get_all()["theme"], "light")
        self.assertEqual(self.settings.get_all()["accent"], "red")

    def test_failed_settings_write_keeps_last_complete_json(self):
        original = self.settings._PATH.read_bytes()
        real_write = Path.write_text

        def fail_write(path, data, *args, **kwargs):
            real_write(path, '{"theme":', encoding="utf-8")
            raise OSError("disk full")

        with patch.object(Path, "write_text", fail_write):
            with self.assertRaises(OSError):
                self.settings.update_settings(theme="light")
        self.assertEqual(self.settings._PATH.read_bytes(), original)

    def test_concurrent_playlist_appends_allocate_distinct_positions(self):
        playlist = self.db.library_playlist_create("test")["id"]
        both_read = threading.Barrier(2)
        errors = []

        class Connection(sqlite3.Connection):
            def execute(conn, sql, parameters=()):
                cursor = super().execute(sql, parameters)
                if "MAX(position)" in sql and not conn.in_transaction:
                    # Materialize old SELECT result before another thread's write.
                    row = cursor.fetchone()
                    both_read.wait(2)
                    return types.SimpleNamespace(fetchone=lambda: row)
                return cursor

        def connect():
            conn = sqlite3.connect(self.db.DB_FILE, factory=Connection)
            conn.row_factory = sqlite3.Row
            return conn

        def append(path):
            try:
                self.db.library_playlist_add_tracks(playlist, [path])
            except Exception as exc:
                errors.append(exc)

        with patch.object(self.db, "_connect", side_effect=connect):
            threads = [threading.Thread(target=append, args=(p,)) for p in ("a.mp3", "b.mp3")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(4)
        self.assertFalse(errors, errors)
        self.assertEqual([r["position"] for r in self.db.library_playlist_tracks(playlist)], [0, 1])


if __name__ == "__main__":
    unittest.main()
