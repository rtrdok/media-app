"""Один экземпляр Media App: mutex + пробуждение окна из трея."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

HOST = "127.0.0.1"
WAKE_PORTS = (17865, 8765, 18765)
MUTEX_NAME = "Local\\MediaAppSingleInstance"


def try_acquire_mutex() -> object | None:
    """Windows named mutex. None = уже запущено (или не Windows)."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return None
        err = kernel32.GetLastError()
        # ERROR_ALREADY_EXISTS = 183
        if err == 183:
            kernel32.CloseHandle(handle)
            return None
        return handle
    except Exception:
        return object()  # не Windows / ошибка — не блокируем запуск


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


def wake_existing_instance(ports: tuple[int, ...] = WAKE_PORTS) -> bool:
    """Показать уже запущенное окно. True если ответил наш сервер."""
    for port in ports:
        try:
            if _post_show(port):
                return True
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            continue
        except Exception:
            continue

    # сервер жив, но show не ок — всё равно «занято», иначе два UI
    for port in ports:
        try:
            if _ping(port):
                # ещё раз попросим show (восстановление после мини/трея)
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
