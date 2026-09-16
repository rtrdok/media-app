"""Один экземпляр Media App: mutex + пробуждение окна из трея."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from media_core.config import BASE_DIR

HOST = "127.0.0.1"
WAKE_PORTS = (17865, 8765, 18765)
MUTEX_NAME = "Local\\MediaAppSingleInstance"
_PORT_FILE = BASE_DIR / "config" / "listen_port.txt"
# Mutex API недоступен (не Windows / сбой) — не блокируем запуск, но и не притворяемся владельцем
MUTEX_UNAVAILABLE = object()


def write_listen_port(port: int) -> None:
    try:
        _PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PORT_FILE.write_text(str(int(port)), encoding="utf-8")
    except OSError:
        pass


def read_listen_port() -> int | None:
    try:
        if not _PORT_FILE.is_file():
            return None
        return int(_PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def try_acquire_mutex() -> object | None:
    """Windows named mutex.

    Returns:
      handle — мы владельцы
      None — уже запущено (ERROR_ALREADY_EXISTS)
      MUTEX_UNAVAILABLE — API недоступен (не блокировать старт)
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return MUTEX_UNAVAILABLE
        err = kernel32.GetLastError()
        # ERROR_ALREADY_EXISTS = 183
        if err == 183:
            kernel32.CloseHandle(handle)
            return None
        return handle
    except Exception:
        return MUTEX_UNAVAILABLE


def release_mutex(handle: object | None) -> None:
    if handle is None or handle is MUTEX_UNAVAILABLE:
        return
    try:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass


def _post_show(port: int) -> bool:
    req = urllib.request.Request(
        f"http://{HOST}:{port}/api/window/show",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=1.5) as r:
        raw = r.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
        return bool(data.get("ok"))


def _ping(port: int) -> bool:
    with urllib.request.urlopen(f"http://{HOST}:{port}/api/extension/ping", timeout=0.8) as r:
        data = json.loads(r.read().decode("utf-8", errors="replace"))
        return data.get("app") == "MediaApp"


def wake_existing_instance(ports: tuple[int, ...] | None = None) -> bool:
    """Показать уже запущенное окно. True если ответил наш сервер."""
    ordered: list[int] = []
    saved = read_listen_port()
    if saved:
        ordered.append(saved)
    for p in ports or WAKE_PORTS:
        if p not in ordered:
            ordered.append(p)

    for port in ordered:
        try:
            if _post_show(port):
                return True
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            continue
        except Exception:
            continue

    for port in ordered:
        try:
            if _ping(port):
                try:
                    _post_show(port)
                except Exception:
                    pass
                return True
        except Exception:
            continue
    return False


_show_cb: Callable[[], None] | None = None


def set_show_callback(cb: Callable[[], None] | None) -> None:
    global _show_cb
    _show_cb = cb


def invoke_show() -> bool:
    if _show_cb is None:
        return False
    try:
        _show_cb()
        return True
    except Exception:
        return False
