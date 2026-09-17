"""Installer failure checks run only against disposable install trees."""

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from installer import setup_main as installer


def make_install(root, marker=b"old executable"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "MediaApp.exe").write_bytes(marker)
    static = root / "_internal" / "web" / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("test UI", encoding="utf-8")


class InstallerReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="media-installer-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "MediaApp"
        make_install(self.target)

    def test_incomplete_payload_keeps_previous_install_and_backups(self):
        payload = self.root / "payload.zip"
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("MediaApp.exe", b"incomplete update")
        previous_backup = self.root / "MediaApp_old_previous"
        make_install(previous_backup, b"recovery copy")
        with patch.object(installer, "_payload_zip", return_value=payload), patch.object(
            installer, "_stop_running_app"
        ):
            ok, _ = installer._do_install(self.target, False, Mock())
        self.assertFalse(ok)
        self.assertEqual((self.target / "MediaApp.exe").read_bytes(), b"old executable")
        self.assertTrue(previous_backup.is_dir())

    def test_failed_replacement_restores_complete_old_install(self):
        src = self.root / "staged"
        make_install(src, b"new executable")

        def fail_move(source, destination):
            destination = Path(destination)
            destination.mkdir(exist_ok=True)
            (destination / "partial").write_bytes(b"partial")
            raise OSError("disk write failed")

        with patch.object(installer.shutil, "move", side_effect=fail_move):
            with self.assertRaises(OSError):
                installer._replace_install_dir(src, self.target)
        self.assertEqual((self.target / "MediaApp.exe").read_bytes(), b"old executable")
        self.assertIsNone(installer._verify_install(self.target))

    def test_locked_install_is_not_deleted_as_fallback(self):
        src = self.root / "staged"
        make_install(src, b"new executable")
        real_rename = Path.rename

        def locked_rename(path, dest):
            if path == self.target:
                raise PermissionError("install is locked")
            return real_rename(path, dest)

        with patch.object(Path, "rename", locked_rename):
            with self.assertRaises(PermissionError):
                installer._replace_install_dir(src, self.target)
        self.assertEqual((self.target / "MediaApp.exe").read_bytes(), b"old executable")

    def test_success_keeps_userdata_and_installs_new_executable(self):
        (self.target / "history.db").write_bytes(b"user database")
        payload = self.root / "payload.zip"
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("MediaApp/MediaApp.exe", b"new executable")
            archive.writestr("MediaApp/_internal/web/static/index.html", "new UI")
        with patch.object(installer, "_payload_zip", return_value=payload), patch.object(
            installer, "_stop_running_app"
        ), patch.object(installer, "START_MENU", self.root / "menu"), patch.object(
            installer, "_create_shortcut"
        ), patch.object(installer, "_unblock_tree"), patch.object(
            installer, "_bundle_dir", return_value=self.root / "bundle"
        ):
            ok, detail = installer._do_install(self.target, False, Mock())
        self.assertTrue(ok, detail)
        self.assertEqual((self.target / "MediaApp.exe").read_bytes(), b"new executable")
        self.assertEqual((self.target / "history.db").read_bytes(), b"user database")


if __name__ == "__main__":
    unittest.main()
