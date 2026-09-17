"""Best-effort diagnostics for Windows file locks.

Restart Manager is a Windows component and lists applications that currently
hold a registered file. It is only used for an error message; failure to get
diagnostics must never affect file operations.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def file_lockers(path: str | Path) -> list[dict[str, object]]:
    """Return processes reported by Restart Manager as holding *path*."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes as c
        from ctypes import wintypes as w

        max_app_name = 255
        max_service_name = 63
        error_more_data = 234

        class UniqueProcess(c.Structure):
            _fields_ = [("pid", w.DWORD), ("started", c.c_longlong)]

        class ProcessInfo(c.Structure):
            _fields_ = [
                ("process", UniqueProcess),
                ("app_name", w.WCHAR * (max_app_name + 1)),
                ("service_name", w.WCHAR * (max_service_name + 1)),
                ("app_type", w.DWORD),
                ("status", w.DWORD),
                ("session_id", w.DWORD),
                ("restartable", w.BOOL),
            ]

        manager = c.WinDLL("Rstrtmgr")
        session = w.DWORD()
        key = c.create_unicode_buffer(256)
        if manager.RmStartSession(c.byref(session), 0, key) != 0:
            return []
        try:
            target = os.fspath(Path(path).resolve())
            resources = (w.LPCWSTR * 1)(target)
            if manager.RmRegisterResources(session, 1, resources, 0, None, 0, None) != 0:
                return []
            required = w.DWORD()
            count = w.DWORD()
            reboot_reasons = w.DWORD()
            result = manager.RmGetList(
                session, c.byref(required), c.byref(count), None, c.byref(reboot_reasons)
            )
            if result == 0:
                return []
            if result != error_more_data or not required.value:
                return []
            count.value = required.value
            rows = (ProcessInfo * required.value)()
            if manager.RmGetList(
                session, c.byref(required), c.byref(count), rows, c.byref(reboot_reasons)
            ) != 0:
                return []
            return [
                {"pid": int(row.process.pid), "name": row.app_name or row.service_name or "неизвестный процесс"}
                for row in rows[: count.value]
            ]
        finally:
            manager.RmEndSession(session)
    except Exception:
        return []


def describe_file_lockers(path: str | Path) -> str:
    """Human-readable suffix for a file operation error."""
    lockers = file_lockers(path)
    if not lockers:
        return ""
    names = ", ".join(f"{row['name']} (PID {row['pid']})" for row in lockers)
    return f" Файл удерживает: {names}."
