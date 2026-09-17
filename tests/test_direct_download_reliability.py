"""Direct download cancellation and preservation of existing files."""

import importlib
import logging
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class DirectDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger = logging.getLogger("media_app")
        handler = logging.NullHandler()
        logger.addHandler(handler)
        try:
            cls.direct = importlib.import_module("media_core.direct_download")
        finally:
            logger.removeHandler(handler)

    def response(self, chunks):
        response = Mock(headers={})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content = Mock(return_value=chunks)
        return response

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "track.mp3"
            existing.write_bytes(b"user original")
            with patch("requests.get", return_value=self.response([b"new download"])), \
                    patch("media_core.net_proxy.requests_proxies", return_value=None):
                downloaded = self.direct.download_direct("https://example.test/track.mp3", directory)
            self.assertEqual(existing.read_bytes(), b"user original")
            self.assertEqual(Path(downloaded).read_bytes(), b"new download")

    def test_failure_removes_partial_download(self):
        def chunks():
            yield b"partial"
            raise OSError("connection lost")

        with tempfile.TemporaryDirectory() as directory:
            with patch("requests.get", return_value=self.response(chunks())), \
                    patch("media_core.net_proxy.requests_proxies", return_value=None):
                downloaded = self.direct.download_direct("https://example.test/track.mp3", directory)
            self.assertIsNone(downloaded)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cancellation_stops_stream_and_removes_partial(self):
        from media_core.constants import CANCELLED

        cancelled = threading.Event()

        def chunks():
            yield b"first chunk"
            cancelled.set()
            yield b"must not be written"
            self.fail("download continued after cancellation")

        with tempfile.TemporaryDirectory() as directory:
            with patch("requests.get", return_value=self.response(chunks())), \
                    patch("media_core.net_proxy.requests_proxies", return_value=None):
                downloaded = self.direct.download_direct(
                    "https://example.test/track.mp3", directory, cancel_event=cancelled,
                )
            self.assertIs(downloaded, CANCELLED)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
