"""Discord Presence regressions that do not require Discord or the network."""

import tempfile
import sys
import types
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from media_core import discord_presence as presence
from media_core import discord_rpc as rpc
from media_core import discord_rpc_agent as agent


class DiscordPresenceReliabilityTests(unittest.TestCase):
    def test_generated_library_cover_is_rehosted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cover = root / "file_cache" / "covers" / "cover.jpg"
            cover.parent.mkdir(parents=True)
            cover.write_bytes(b"\xff\xd8" + b"x" * 1200)
            thumb = "/api/file?p=" + quote(str(cover))
            with patch.object(presence, "BASE_DIR", root), \
                    patch.object(presence, "_CACHE_DIR", root / "cache"), \
                    patch.object(presence, "_META_PATH", root / "cache" / "meta.json"), \
                    patch.object(presence, "_rehost", return_value="https://cdn.example/cover.jpg") as upload:
                self.assertEqual(presence.resolve_discord_large_image(thumb), "https://cdn.example/cover.jpg")
            upload.assert_called_once()

    def test_api_file_outside_generated_image_cache_is_never_uploaded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / "secret.txt"
            secret.write_bytes(b"x" * 1200)
            thumb = "/api/file?p=" + quote(str(secret))
            with patch.object(presence, "BASE_DIR", root), \
                    patch.object(presence, "_upload_litterbox") as upload:
                self.assertIsNone(presence.resolve_discord_large_image(thumb))
            upload.assert_not_called()

    def test_clear_presence_tells_persistent_agent_immediately(self):
        with patch.object(rpc, "_use_agent", True), \
                patch.object(rpc, "_post_agent") as post, \
                patch.object(rpc, "_enqueue") as enqueue:
            rpc.clear_presence()
        post.assert_called_once_with("/clear", {})
        enqueue.assert_called_once()

    def test_rehost_uses_next_host_after_primary_failure(self):
        with patch.object(presence, "_upload_uguu", return_value=None), \
                patch.object(presence, "_upload_0x0", return_value="https://0x0.st/cover.jpg") as fallback, \
                patch.object(presence, "_upload_litterbox"):
            self.assertEqual(presence._rehost(b"image", "jpg"), "https://0x0.st/cover.jpg")
        fallback.assert_called_once()

    def test_paused_seek_replaces_old_discord_timestamp(self):
        class FakeRpc:
            def __init__(self):
                self.clears = 0
                self.updates = []

            def clear(self):
                self.clears += 1

            def update(self, **kwargs):
                self.updates.append(kwargs)

        fake = FakeRpc()
        fake_pypresence = types.ModuleType("pypresence")
        fake_types = types.ModuleType("pypresence.types")
        fake_types.ActivityType = types.SimpleNamespace(WATCHING="watching", LISTENING="listening")
        fake_types.StatusDisplayType = types.SimpleNamespace(DETAILS="details")
        state = {
            "client_id": "123456789012345678", "has_track": True,
            "title": "Track", "artist": "Artist", "playing": False,
            "current": 11, "duration": 206, "kind": "audio",
        }
        with patch.object(agent, "_rpc", fake), patch.object(agent, "_connected_id", state["client_id"]), \
                patch.object(agent, "_last_sig", ""), patch.object(agent, "_last_push", 0), \
                patch.object(agent, "_ensure", return_value=True), \
                patch("media_core.discord_presence.resolve_discord_large_image", return_value=None), \
                patch.dict(sys.modules, {"pypresence": fake_pypresence, "pypresence.types": fake_types}):
            self.assertTrue(agent.apply_state(state)["ok"])
            state["current"] = 181
            self.assertTrue(agent.apply_state(state)["ok"])
        self.assertEqual(fake.clears, 2)
        self.assertEqual(len(fake.updates), 2)
        payload = fake.updates[-1]["payload_override"]
        self.assertEqual(payload["args"]["activity"]["timestamps"], {})


if __name__ == "__main__":
    unittest.main()
