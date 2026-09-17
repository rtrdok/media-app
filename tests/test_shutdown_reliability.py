"""Exercise shutdown commands without starting or killing any processes."""

import importlib
import logging
import unittest
from unittest.mock import Mock, patch


class ProcessShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger = logging.getLogger("media_app")
        handler = logging.NullHandler()
        logger.addHandler(handler)
        try:
            cls.cleanup = importlib.import_module("media_core.process_cleanup")
        finally:
            logger.removeHandler(handler)

    def test_hard_exit_never_kills_unrelated_ffmpeg_processes(self):
        c = self.cleanup
        callbacks = []
        timer = Mock(side_effect=lambda delay, callback: callbacks.append(callback) or Mock())
        with patch.object(c, "_hard_exit_armed", False), \
                patch.object(c.threading, "Timer", timer), \
                patch.object(c, "terminate_child_processes") as terminate, \
                patch.object(c, "kill_known_helpers") as global_kill, \
                patch.object(c.os, "_exit") as exit_process:
            c.arm_hard_exit()
            callbacks[0]()
        terminate.assert_called_once()
        global_kill.assert_not_called()
        exit_process.assert_called_once_with(0)

    def test_preserved_update_process_and_its_subtree_are_excluded(self):
        c = self.cleanup
        with patch.object(c, "_preserved_child_pids", set()), \
                patch.object(c.os, "name", "nt"), \
                patch.object(c.subprocess, "run") as run:
            c.preserve_child_process(12345)
            c.preserve_child_process(45678)
            c.terminate_child_processes()
        script = run.call_args.args[0][-1]
        self.assertIn("$preserved = @(12345,45678)", script)
        self.assertIn("$cid -notin $preserved -and $targets.Add($cid)", script)
        self.assertIn("$cid -ne $PID", script)

    def test_invalid_preserved_process_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self.cleanup.preserve_child_process(0)


if __name__ == "__main__":
    unittest.main()
