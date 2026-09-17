"""Updater regressions; no network, real installer or application shutdown."""

from __future__ import annotations

import importlib.util
import logging
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch


def load_updater():
    spec = importlib.util.spec_from_file_location(
        "updater_under_test", Path(__file__).resolve().parents[1] / "media_core" / "updater.py"
    )
    module = importlib.util.module_from_spec(spec)
    logging_stub = types.ModuleType("media_core.logging_setup")
    logging_stub.log = logging.Logger("updater-tests")
    logging_stub.log.addHandler(logging.NullHandler())
    with patch.dict(sys.modules, {"media_core.logging_setup": logging_stub}):
        spec.loader.exec_module(module)
    return module


class UpdaterReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.updater = load_updater()
        self.tmp = tempfile.TemporaryDirectory(prefix="updater_test_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def release(self):
        return {"ok": True, "update": True, "url": "https://github.com/owner/repo/releases/download/v2/MediaApp.zip"}

    def test_download_failure_is_reported_with_real_logger(self):
        job_dir = self.root / "job"
        job_dir.mkdir()
        with patch.object(self.updater.tempfile, "mkdtemp", return_value=str(job_dir)), patch.object(
            self.updater, "_download_file", side_effect=OSError("network interrupted")
        ), patch.object(sys, "frozen", True, create=True):
            self.updater._run_update_job(self.release()["url"])
        self.assertEqual(self.updater.get_update_job()["status"], "error")
        self.assertIn("network interrupted", self.updater.get_update_job()["error"])
        self.assertFalse(job_dir.exists())

    def test_active_zero_byte_download_cannot_be_restarted(self):
        self.updater._set_job(status="downloading", bytes_done=0, pct=0)
        with patch.object(self.updater, "check_github_update", return_value=self.release()) as check, patch.object(
            self.updater.threading, "Thread"
        ) as thread, patch.object(sys, "frozen", True, create=True):
            result = self.updater.start_update_job()
        self.assertTrue(result["ok"])
        check.assert_not_called()
        thread.assert_not_called()

    def test_concurrent_start_only_checks_release_once(self):
        entered = threading.Event()
        release = threading.Event()

        def check_release():
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test timed out")
            return self.release()

        results = []
        with patch.object(self.updater, "check_github_update", side_effect=check_release) as check, patch.object(
            self.updater, "_run_update_job"
        ) as worker, patch.object(sys, "frozen", True, create=True):
            first = threading.Thread(target=lambda: results.append(self.updater.start_update_job()))
            first.start()
            self.assertTrue(entered.wait(5))
            second = threading.Thread(target=lambda: results.append(self.updater.start_update_job()))
            second.start()
            second.join(0.2)
            release.set()
            first.join(5)
            second.join(5)
            self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(check.call_count, 1)
        self.assertEqual(worker.call_count, 1)

    def test_release_failure_is_not_reported_as_success(self):
        with patch.object(self.updater, "check_github_update", return_value={
            "ok": False, "update": False, "error": "GitHub HTTP 403", "message": "rate limited"
        }), patch.object(sys, "frozen", True, create=True):
            result = self.updater.start_update_job()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.updater.get_update_job()["status"], "error")

    def test_caller_download_url_is_ignored(self):
        with patch.object(self.updater, "check_github_update", return_value=self.release()), patch.object(
            self.updater.threading, "Thread"
        ) as thread, patch.object(sys, "frozen", True, create=True):
            self.updater.start_update_job("https://evil.example/payload.exe")
        self.assertEqual(thread.call_args.kwargs["args"], (self.release()["url"],))

    def test_source_checkout_cannot_be_replaced(self):
        with patch.object(sys, "frozen", False, create=True), patch.object(
            self.updater, "check_github_update", return_value=self.release()
        ), patch.object(self.updater.threading, "Thread") as thread:
            result = self.updater.start_update_job()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        thread.assert_not_called()

    def test_incomplete_download_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "(?i)(incomplete|непол|ожид)"):
            self.updater._write_stream_to_file(self.root / "download.zip", 2048, iter([b"x" * 1024]))

    def test_temp_directory_failure_is_reported(self):
        with patch.object(self.updater.tempfile, "mkdtemp", side_effect=OSError("disk full")), patch.object(
            sys, "frozen", True, create=True
        ):
            self.updater._run_update_job(self.release()["url"])
        self.assertEqual(self.updater.get_update_job()["status"], "error")
        self.assertIn("disk full", self.updater.get_update_job()["error"])

    def run_zip(self, entries):
        job_dir = self.root / "job"
        job_dir.mkdir()

        def download(_url, destination):
            with zipfile.ZipFile(destination, "w") as archive:
                for name, content in entries.items():
                    archive.writestr(name, content)

        cleanup = types.ModuleType("media_core.process_cleanup")
        cleanup.preserve_child_process = Mock()
        cleanup.arm_hard_exit = Mock()
        with patch.object(self.updater.tempfile, "mkdtemp", return_value=str(job_dir)), patch.object(
            self.updater, "_download_file", side_effect=download
        ), patch.object(self.updater, "_write_apply_script", return_value=job_dir / "apply.ps1") as script, patch.object(
            self.updater.subprocess, "Popen", return_value=Mock(pid=9876)
        ) as popen, patch.object(sys, "frozen", True, create=True), patch.dict(
            sys.modules, {"media_core.process_cleanup": cleanup}
        ):
            self.updater._run_update_job(self.release()["url"])
        return popen, script, cleanup

    def test_zip_missing_application_is_rejected_before_launch(self):
        popen, script, _ = self.run_zip({"readme.txt": "wrong release package"})
        self.assertEqual(self.updater.get_update_job()["status"], "error")
        popen.assert_not_called()
        script.assert_not_called()

    def test_zip_traversal_is_rejected_before_launch(self):
        popen, _, _ = self.run_zip({
            "MediaApp.exe": "binary", "_internal/web/static/index.html": "UI", "../outside.txt": "bad"
        })
        self.assertEqual(self.updater.get_update_job()["status"], "error")
        popen.assert_not_called()

    def test_valid_zip_handoff_preserves_helper_process(self):
        popen, _, cleanup = self.run_zip({
            "MediaApp/MediaApp.exe": "binary", "MediaApp/_internal/web/static/index.html": "UI"
        })
        self.assertEqual(self.updater.get_update_job()["status"], "done")
        popen.assert_called_once()
        cleanup.preserve_child_process.assert_called_once_with(9876)
        cleanup.arm_hard_exit.assert_called_once()

    def test_installer_handoff_preserves_installer_process(self):
        job_dir = self.root / "job"
        job_dir.mkdir()
        cleanup = types.ModuleType("media_core.process_cleanup")
        cleanup.preserve_child_process = Mock()
        cleanup.arm_hard_exit = Mock()
        with patch.object(self.updater.tempfile, "mkdtemp", return_value=str(job_dir)), patch.object(
            self.updater, "_download_file"
        ), patch.object(self.updater.subprocess, "Popen", return_value=Mock(pid=8765)), patch.object(
            sys, "frozen", True, create=True
        ), patch.dict(sys.modules, {"media_core.process_cleanup": cleanup}):
            self.updater._run_update_job("https://github.com/owner/repo/releases/download/v2/MediaApp-Installer.exe")
        self.assertEqual(self.updater.get_update_job()["status"], "done")
        cleanup.preserve_child_process.assert_called_once_with(8765)
        cleanup.arm_hard_exit.assert_called_once()

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell is required")
    def test_apply_script_extract_failure_keeps_installation_intact(self):
        target = self.root / "Медиа ' [test]"
        target.mkdir()
        (target / "MediaApp.exe").write_bytes(b"old working application")
        (target / "history.db").write_bytes(b"user database")
        package = self.root / "broken.zip"
        package.write_bytes(b"not a zip")
        script = self.updater._write_apply_script(package, target)
        self.assertEqual(script.suffix, ".ps1")
        self.assertTrue(script.read_bytes().startswith(b"\xef\xbb\xbf"))
        # This deliberately fails before the wait/rename section. It never
        # launches/kills a process or replaces an installation.
        result = subprocess.run([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)
        ], capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((target / "MediaApp.exe").read_bytes(), b"old working application")
        self.assertEqual((target / "history.db").read_bytes(), b"user database")
        self.assertTrue((self.root / "update-error.txt").is_file(), result.stderr)

    def test_apply_script_does_not_target_unknown_directory(self):
        with self.assertRaises(RuntimeError):
            self.updater._write_apply_script(self.root / "update.zip", self.root)

    def test_worker_start_failure_releases_reservation(self):
        with patch.object(self.updater, "check_github_update", return_value=self.release()), patch.object(
            self.updater.threading, "Thread", side_effect=RuntimeError("cannot start thread")
        ), patch.object(sys, "frozen", True, create=True):
            result = self.updater.start_update_job()
        self.assertFalse(result["ok"])
        self.assertEqual(self.updater.get_update_job()["status"], "error")


if __name__ == "__main__":
    unittest.main()
