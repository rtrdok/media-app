import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Import without opening the user's database or log.
with patch("media_core.config.DB_FILE", ":memory:"), patch(
    "logging.handlers.RotatingFileHandler", return_value=logging.NullHandler()
):
    from media_core import database, library


class LibraryReliabilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="media-library-test-")
        self.addCleanup(temp.cleanup)
        self.track = Path(temp.name) / "track.mp3"
        self.track.write_bytes(b"test audio")
        self.enterContext(patch.object(library, "library_index_list", return_value=[{"path": str(self.track)}]))

    def test_locked_file_keeps_index_and_playlist_membership(self):
        with patch.object(Path, "unlink", side_effect=PermissionError("file is playing")), patch(
            "time.sleep"
        ), patch.object(database, "library_index_remove_path", return_value=True) as remove:
            result = library.remove_library_item(str(self.track))
        self.assertFalse(result["ok"])
        self.assertFalse(result["file_deleted"])
        remove.assert_not_called()
        self.assertTrue(self.track.is_file())

    def test_successful_delete_removes_index_only_after_file(self):
        def remove_after_delete(path):
            self.assertFalse(self.track.exists())
            return True

        with patch.object(database, "library_index_remove_path", side_effect=remove_after_delete):
            result = library.remove_library_item(str(self.track))
        self.assertTrue(result["ok"])
        self.assertTrue(result["file_deleted"])

    def test_unindexed_file_is_not_deleted(self):
        other = self.track.with_name("other.mp3")
        other.write_bytes(b"not indexed")
        with patch.object(database, "library_index_remove_path") as remove:
            result = library.remove_library_item(str(other))
        self.assertFalse(result["ok"])
        self.assertTrue(other.exists())
        remove.assert_not_called()

    def test_index_only_removal_preserves_file(self):
        with patch.object(database, "library_index_remove_path", return_value=True):
            result = library.remove_library_item(str(self.track), delete_file=False)
        self.assertTrue(result["ok"])
        self.assertTrue(self.track.exists())


if __name__ == "__main__":
    unittest.main()
