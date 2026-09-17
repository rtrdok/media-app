"""Optional, cancellable post-processing for downloaded audio."""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

from media_core.utils import _ffmpeg_bin, subprocess_no_window_kwargs


def normalize_mp3(path: str, cancel_event=None) -> bool:
    """Normalize an MP3 atomically to a comfortable listening level.

    The original is only replaced after ffmpeg has produced a valid temporary
    file. Returning False means cancellation; failures raise and leave the
    original untouched.
    """
    src = Path(path)
    if src.suffix.lower() != ".mp3" or not src.is_file():
        return True
    tmp = src.with_name(f".{src.stem}.{uuid.uuid4().hex}.normalized.mp3")
    command = [
        _ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-map_metadata", "0", "-vn",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a", "libmp3lame", "-q:a", "2", str(tmp),
    ]
    proc = None
    try:
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **subprocess_no_window_kwargs())
        while proc.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return False
            time.sleep(0.1)
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 1024:
            error = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"Не удалось нормализовать аудио{': ' + error if error else ''}")
        os.replace(tmp, src)
        return True
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
