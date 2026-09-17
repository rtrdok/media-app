"""Deterministic queue regressions; no network, user database or GUI."""

import asyncio
import importlib
import logging
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


def load_server():
    # Importing server initializes logging; keep all import-time data isolated.
    import media_core.config as config

    logger = logging.getLogger("media_app")
    handler = logging.NullHandler()
    logger.addHandler(handler)
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(
                config, BASE_DIR=root, DB_FILE=str(root / "history.db"),
                LOG_FILE=str(root / "app.log"), FILE_CACHE_DIR=str(root / "cache"),
            ):
                return importlib.import_module("web.server")
    finally:
        logger.removeHandler(handler)


class QueueReliabilityTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = load_server()

    def setUp(self):
        s = self.server
        for name, value in {
            "_queue": [], "_queue_id": 0, "_paused": False,
            "_soft_pause": False, "_shutting_down": False, "_busy": False,
            "_current_job": None, "_pump_task": None, "_job_tasks": set(),
            "_queue_lock": asyncio.Lock(), "_cancel": threading.Event(),
            "_last": {"error": "", "message": "", "shazam": None, "notify_pending": False},
            "_progress": s._blank_progress(),
        }.items():
            self.enterContext(patch.object(s, name, value))
        self.enterContext(patch.object(s, "get_bool", return_value=False))
        self.enterContext(patch.object(s, "_max_concurrent", return_value=2))

    async def asyncTearDown(self):
        s = self.server
        s._shutting_down = True
        tasks = list(s._job_tasks)
        if s._pump_task is not None:
            tasks.append(s._pump_task)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def item(self, suffix):
        return self.server._enqueue_one(self.server.JobIn(url=f"https://youtu.be/{suffix}"))

    async def test_parallel_success_does_not_inherit_other_jobs_error(self):
        s = self.server
        first = self.item("success")
        second = self.item("failure")
        first_entered = asyncio.Event()
        let_first_finish = asyncio.Event()

        async def run(body, **kwargs):
            result = kwargs.get("result_state", s._last)
            if body.url.endswith("success"):
                result["message"] = "Готово"
                first_entered.set()
                await let_first_finish.wait()
            else:
                await first_entered.wait()
                result["error"] = "download failed"
                let_first_finish.set()

        with patch.object(s, "_run", side_effect=run), patch.object(s, "_schedule_pump"):
            await s._pump_queue()
            await asyncio.gather(*s._job_tasks)
        self.assertEqual(second["status"], "error")
        self.assertEqual(first["status"], "done")
        self.assertEqual(first.get("error"), "")

    async def test_parallel_downloads_keep_their_own_title_from_worker_thread(self):
        s = self.server
        from media_core import download_ytdlp as ytdlp

        first = self.item("first")
        second = self.item("second")
        first_extracted = asyncio.Event()
        second_extracted = asyncio.Event()
        saved = {}

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"video")

            async def download(url, **kwargs):
                if url.endswith("first"):
                    await asyncio.to_thread(ytdlp._set_last_extract_info, {"title": "First video"})
                    first_extracted.set()
                    await second_extracted.wait()
                else:
                    await first_extracted.wait()
                    await asyncio.to_thread(ytdlp._set_last_extract_info, {"title": "Second video"})
                    second_extracted.set()
                return str(source)

            def save(path, url, audio, title):
                saved[url] = title
                return path

            with patch.object(s, "process_url", side_effect=download), \
                    patch.object(s, "save_to_downloads", side_effect=save), \
                    patch.object(s, "history_add"), patch.object(s, "_thumb", new=AsyncMock()), \
                    patch.object(s, "_schedule_pump"), patch.object(ytdlp, "_last_extract_info", None):
                await s._pump_queue()
                await asyncio.gather(*s._job_tasks)
            self.assertEqual(saved[first["url"]], "First video")
            self.assertEqual(saved[second["url"]], "Second video")

    async def test_pause_then_immediate_resume_requeues_cancelled_job(self):
        s = self.server
        item = self.item("pause")
        entered = asyncio.Event()
        finish = asyncio.Event()

        async def run(body, **kwargs):
            entered.set()
            await finish.wait()
            self.assertTrue(kwargs["cancel_event"].is_set())
            kwargs.get("result_state", s._last)["message"] = "Отменено"

        with patch.object(s, "_run", side_effect=run), patch.object(s, "_schedule_pump"):
            await s._pump_queue()
            await entered.wait()
            await s.queue_pause()
            await s.queue_resume()
            finish.set()
            await asyncio.gather(*s._job_tasks)
        self.assertEqual(item["status"], "queued")

    async def test_scoped_metadata_and_errors_are_shared_with_worker_only(self):
        from media_core.download_state import download_scope
        from media_core import download_ytdlp as yt, download_vk_audio as vk, yandex_music_api as ym

        def set_values(label):
            yt._set_last_error(label)
            vk._set_last_error(label)
            vk._set_last_vk_track_meta({"title": label})
            ym._set_last_yandex_track_meta(ym.YandexTrackInfo(label, "artist", label, 10))

        with download_scope():
            await asyncio.to_thread(set_values, "outer")
            with download_scope():
                self.assertIsNone(yt.get_last_download_error())
                self.assertIsNone(vk.get_last_download_error())
                self.assertIsNone(vk.get_last_vk_track_meta())
                self.assertIsNone(ym.get_last_yandex_track_meta())
                await asyncio.to_thread(set_values, "inner")
                self.assertEqual(vk.get_last_vk_track_meta()["title"], "inner")
            self.assertEqual(yt.get_last_download_error(), "outer")
            self.assertEqual(vk.get_last_download_error(), "outer")
            self.assertEqual(vk.get_last_vk_track_meta()["title"], "outer")
            self.assertEqual(ym.get_last_yandex_track_meta()["title"], "outer")

    async def test_completed_job_is_not_requeued_by_pause_during_finishing(self):
        s = self.server
        item = self.item("finished")

        async def run(body, **kwargs):
            await s.queue_pause()
            kwargs.get("result_state", s._last)["message"] = "Готово"

        with patch.object(s, "_run", side_effect=run), patch.object(s, "_schedule_pump"):
            await s._pump_queue()
            await asyncio.gather(*s._job_tasks)
        self.assertEqual(item["status"], "done")

    async def test_lifespan_waits_for_active_jobs_before_temp_cleanup(self):
        s = self.server
        item = self.item("shutdown")
        entered = asyncio.Event()
        stopped = asyncio.Event()
        observed = []

        async def run(body, **kwargs):
            entered.set()
            try:
                while not kwargs["cancel_event"].is_set():
                    await asyncio.sleep(0)
            finally:
                stopped.set()

        def cleanup():
            observed.append(stopped.is_set())

        with patch.object(s, "_run", side_effect=run), patch.object(s, "stop_uvicorn_server"), \
                patch.object(s, "cleanup_temp_files", side_effect=cleanup):
            async with s.lifespan(s.app):
                await s._pump_queue()
                await entered.wait()
            self.assertEqual(observed, [True], "cleanup ran while download was active")
            self.assertNotEqual(item["status"], "running")

    async def test_lifespan_timeout_skips_cleanup_of_possible_worker_files(self):
        s = self.server
        item = self.item("slow-shutdown")
        entered = asyncio.Event()

        async def run(body, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        with patch.object(s, "_run", side_effect=run), patch.object(s, "stop_uvicorn_server"), \
                patch.object(s, "_SHUTDOWN_GRACE_SECONDS", 0.01), \
                patch.object(s, "cleanup_temp_files") as cleanup:
            async with s.lifespan(s.app):
                await s._pump_queue()
                await entered.wait()
            cleanup.assert_not_called()
            self.assertFalse(s._job_tasks)
            self.assertNotEqual(item["status"], "running")

    async def test_exception_in_lifespan_still_stops_queue(self):
        s = self.server
        with patch.object(s, "stop_uvicorn_server"), patch.object(s, "cleanup_temp_files"):
            with self.assertRaisesRegex(RuntimeError, "lifespan failure"):
                async with s.lifespan(s.app):
                    raise RuntimeError("lifespan failure")
        self.assertTrue(s._shutting_down)

    def test_server_shutdown_preserves_lifespan_teardown(self):
        s = self.server
        uvicorn = Mock(should_exit=False, force_exit=False)
        with patch.object(s, "_uvicorn_server", uvicorn):
            s.stop_uvicorn_server()
        self.assertTrue(uvicorn.should_exit)
        self.assertFalse(uvicorn.force_exit)


if __name__ == "__main__":
    unittest.main()
