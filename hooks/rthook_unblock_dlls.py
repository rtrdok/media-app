"""PyInstaller runtime hook: снять Zone.Identifier (Mark of the Web) с DLL.

После скачивания ZIP с GitHub Windows помечает файлы как из интернета.
.NET CLR отказывается грузить Python.Runtime.dll → падение pywebview/pythonnet.
Хук выполняется до кода приложения и тихо снимает ADS.
"""

from __future__ import annotations

import os
import sys


def _remove_zone_identifier(path: str, delete_file) -> None:
    ads = path + ":Zone.Identifier"
    try:
        delete_file(ads)
    except Exception:
        try:
            os.remove(ads)
        except OSError:
            pass


def _unblock_tree(root: str, delete_file) -> None:
    if not root or not os.path.isdir(root):
        return
    for dirpath, _dirs, filenames in os.walk(root):
        for fn in filenames:
            if not fn.lower().endswith((".dll", ".exe", ".pyd")):
                continue
            _remove_zone_identifier(os.path.join(dirpath, fn), delete_file)


def _unblock_bundle() -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes
        from ctypes.wintypes import LPCWSTR

        delete_file = ctypes.windll.kernel32.DeleteFileW
        delete_file.argtypes = [LPCWSTR]
        delete_file.restype = ctypes.c_bool
    except Exception:

        def delete_file(path: str) -> bool:  # type: ignore[misc]
            try:
                os.remove(path)
                return True
            except OSError:
                return False

    roots: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(str(meipass))
    try:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if exe_dir and exe_dir not in roots:
            roots.append(exe_dir)
            internal = os.path.join(exe_dir, "_internal")
            if os.path.isdir(internal) and internal not in roots:
                roots.append(internal)
    except Exception:
        pass

    for root in roots:
        _unblock_tree(root, delete_file)


_unblock_bundle()
