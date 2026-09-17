"""HTTP smoke checks with temporary database/settings; no GUI or external APIs."""

import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from test_queue_reliability import load_server


class ApiReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.server = load_server()
        from media_core import database, settings_store

        temp = tempfile.TemporaryDirectory(prefix="media-api-test-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.enterContext(patch.object(database, "DB_FILE", str(root / "history.db")))
        self.enterContext(patch.object(settings_store, "_PATH", root / "settings.json"))
        self.enterContext(patch.object(settings_store, "_DEFAULTS", {
            **settings_store._DEFAULTS, "download_dir": str(root / "downloads"),
        }))
        database.init_db()
        self.client = TestClient(self.server.app)
        self.addCleanup(self.client.close)
        self.server._active_file_streams.clear()
        self.server._active_file_tasks.clear()

    def test_home_and_state_have_working_contract(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/static/assets/", response.text)
        state = self.client.get("/api/state")
        self.assertEqual(state.status_code, 200)
        self.assertIn("settings", state.json())
        self.assertEqual(state.json()["history"], [])
        light = self.client.get("/api/state?light=1")
        self.assertEqual(light.status_code, 200)
        self.assertNotIn("settings", light.json())

    def test_playlist_crud_through_http(self):
        created = self.client.post("/api/library/playlists", json={"name": "Smoke test"})
        self.assertEqual(created.status_code, 200)
        playlist_id = created.json()["playlist"]["id"]
        added = self.client.post(f"/api/library/playlists/{playlist_id}/tracks", json={"paths": ["a.mp3", "b.mp3"]})
        self.assertEqual(added.json()["added"], 2)
        detail = self.client.get(f"/api/library/playlists/{playlist_id}")
        self.assertEqual(len(detail.json()["tracks"]), 2)
        deleted = self.client.delete(f"/api/library/playlists/{playlist_id}")
        self.assertTrue(deleted.json()["ok"])
        self.assertEqual(self.client.get("/api/library/playlists").json()["items"], [])

    def test_file_stream_marker_is_released_after_response(self):
        from media_core import settings_store

        media = Path(settings_store.get_download_dir()) / "sample.mp3"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"small media")
        response = self.client.get("/api/file", params={"p": str(media)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.server._active_file_streams, {})

    def test_remove_cancels_its_own_file_response_before_delete(self):
        from media_core import library

        class ActiveTask:
            def __init__(self):
                self.cancelled = 0

            def done(self):
                return False

            def cancel(self):
                self.cancelled += 1

        path = "C:/downloads/sample.mp4"
        key = self.server._stream_key(path)
        task = ActiveTask()
        self.server._active_file_streams[key] = 1
        self.server._active_file_tasks[key] = {task}
        result = {"ok": False, "error": "locked"}
        with patch.object(self.server, "_wait_for_file_streams", new=AsyncMock(return_value=0)), patch.object(
            library, "remove_library_item", return_value=result
        ):
            response = self.client.post("/api/library/remove", json={"path": path, "delete_file": True})
        self.assertEqual(task.cancelled, 1)
        self.assertEqual(response.json(), result)

    def test_cancelling_file_response_releases_stream_marker(self):
        from media_core import settings_store

        media = Path(settings_store.get_download_dir()) / "stream.mp4"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"test media")

        async def exercise():
            key = self.server._stream_key(media)
            self.server._active_file_streams[key] = 1
            response = self.server._TrackedFileResponse(media)
            sending = asyncio.Event()
            release_send = asyncio.Event()

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                if message["type"] == "http.response.body":
                    sending.set()
                    await release_send.wait()

            task = asyncio.create_task(
                response({"type": "http", "method": "GET", "headers": []}, receive, send)
            )
            await sending.wait()
            self.assertEqual(self.server._abort_file_streams(media), 1)
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertNotIn(key, self.server._active_file_streams)
            self.assertNotIn(key, self.server._active_file_tasks)

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
