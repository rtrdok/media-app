"""Завершение дочерних процессов и жёсткий выход приложения."""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Callable

from media_core.logging_setup import log
from media_core.utils import subprocess_no_window_kwargs

_hard_exit_armed = False
_preserved_child_pids: set[int] = set()
_preserved_child_lock = threading.Lock()


def preserve_child_process(pid: int) -> None:
    """Keep an update installer/helper and its descendants alive on app exit."""
    pid = int(pid)
    if pid <= 0:
        raise ValueError("Expected a positive child process ID")
    with _preserved_child_lock:
        _preserved_child_pids.add(pid)


def terminate_child_processes() -> None:
    """Убить прямых и вложенных потомков текущего процесса (не себя)."""
    if os.name != "nt":
        return
    pid = os.getpid()
    with _preserved_child_lock:
        preserved = ",".join(str(pid) for pid in sorted(_preserved_child_pids))
    # Рекурсивно: потомки текущего PID, без Stop-Process на себя
    ps = f"""
$root = {pid}
$preserved = @({preserved})
$targets = New-Object 'System.Collections.Generic.HashSet[int]'
$queue = New-Object System.Collections.Generic.Queue[int]
$queue.Enqueue($root)
while ($queue.Count -gt 0) {{
  $p = $queue.Dequeue()
  Get-CimInstance Win32_Process -Filter "ParentProcessId=$p" -ErrorAction SilentlyContinue | ForEach-Object {{
    $cid = [int]$_.ProcessId
    if ($cid -ne $root -and $cid -ne $PID -and $cid -notin $preserved -and $targets.Add($cid)) {{ $queue.Enqueue($cid) }}
  }}
}}
foreach ($cid in $targets) {{
  Stop-Process -Id $cid -Force -ErrorAction SilentlyContinue
}}
"""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
            **subprocess_no_window_kwargs(),
        )
        log.info("process_cleanup: terminated children of pid=%s", pid)
    except Exception as e:
        log.warning("process_cleanup: children kill failed: %s", e)


def kill_known_helpers() -> None:
    """Добить типичные helper'ы по имени (ffmpeg и т.п.)."""
    if os.name != "nt":
        return
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", name],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                **subprocess_no_window_kwargs(),
            )
        except Exception:
            pass


def arm_hard_exit(delay_sec: float = 2.5, before: Callable[[], None] | None = None) -> None:
    """Через delay_sec принудительно завершить процесс (если ещё жив)."""
    global _hard_exit_armed
    if _hard_exit_armed:
        return
    _hard_exit_armed = True

    def _go() -> None:
        try:
            if before:
                before()
        except Exception:
            pass
        try:
            terminate_child_processes()
        except Exception:
            pass
        log.info("process_cleanup: os._exit(0)")
        os._exit(0)

    threading.Timer(max(0.5, float(delay_sec)), _go).start()
