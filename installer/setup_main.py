"""Графический установщик Media App → выбор папки, ярлыки, обновление на месте."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path
from tkinter import filedialog

APP_NAME = "Media App"
APP_VERSION = "1.5.18"
DEFAULT_TARGET = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MediaApp"
START_MENU = (
    Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
)
DESKTOP = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
META_NAME = "install_meta.json"


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _payload_zip() -> Path:
    return _bundle_dir() / "payload.zip"


def _icon_path() -> Path | None:
    for p in (
        _bundle_dir() / "app.ico",
        Path(__file__).resolve().parent.parent / "branding" / "app.ico",
    ):
        if p.is_file():
            return p
    return None


def _ps_hidden(command: str, timeout: int = 30) -> str:
    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags |= subprocess.CREATE_NO_WINDOW
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=flags,
    )
    return (r.stdout or "").strip()


def _unblock_tree(root: Path) -> None:
    """Снять Zone.Identifier без PowerShell (без вспышек консоли)."""
    try:
        import ctypes

        delete = ctypes.windll.kernel32.DeleteFileW
    except Exception:
        return
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".dll", ".exe", ".pyd", ".zip"}:
            continue
        ads = str(p) + ":Zone.Identifier"
        try:
            delete(ads)
        except Exception:
            pass


def _create_shortcut(lnk: Path, target: Path, workdir: Path, args: str = "") -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    t = str(target).replace("'", "''")
    w = str(workdir).replace("'", "''")
    l = str(lnk).replace("'", "''")
    icon = str(target).replace("'", "''")
    branding_ico = workdir / "branding" / "app.ico"
    if branding_ico.is_file():
        icon = str(branding_ico).replace("'", "''")
    elif target.suffix.lower() == ".exe":
        icon = f"{icon},0"
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{l}'); "
        f"$s.TargetPath = '{t}'; "
        f"$s.WorkingDirectory = '{w}'; "
        f"$s.Description = '{APP_NAME}'; "
        f"$s.IconLocation = '{icon}'; "
    )
    if args:
        ps += f"$s.Arguments = '{args}'; "
    ps += "$s.Save()"
    _ps_hidden(ps, timeout=30)


def _write_uninstall(target: Path) -> Path:
    bat = target / "Uninstall.bat"
    content = f"""@echo off
echo Removing {APP_NAME}...
powershell -NoProfile -Command "Remove-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name 'MediaApp' -ErrorAction SilentlyContinue"
del /f /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{APP_NAME}.lnk" 2>nul
del /f /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Uninstall {APP_NAME}.lnk" 2>nul
del /f /q "%USERPROFILE%\\Desktop\\{APP_NAME}.lnk" 2>nul
cd /d "%TEMP%"
timeout /t 1 /nobreak >nul
rmdir /s /q "{target}"
echo Done.
pause
"""
    bat.write_text(content, encoding="utf-8")
    return bat


def _write_meta(target: Path) -> None:
    meta = {
        "app": "MediaApp",
        "version": APP_VERSION,
        "install_dir": str(target),
    }
    try:
        (target / META_NAME).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _parse_version(v: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", (v or "").strip().lstrip("vV"))
    if not parts:
        return (0,)
    return tuple(int(x) for x in parts[:4])


def _read_installed_version(target: Path) -> str:
    meta = target / META_NAME
    if meta.is_file():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            ver = str(data.get("version") or "").strip()
            if ver:
                return ver
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    exe = target / "MediaApp.exe"
    if exe.is_file():
        # ProductVersion / FileVersion из ресурсов EXE (если прошиты)
        exe_s = str(exe).replace("'", "''")
        out = _ps_hidden(
            f"(Get-Item -LiteralPath '{exe_s}').VersionInfo.ProductVersion; "
            f"(Get-Item -LiteralPath '{exe_s}').VersionInfo.FileVersion",
            timeout=15,
        )
        for line in (out or "").splitlines():
            line = line.strip()
            if re.search(r"\d+\.\d+", line):
                return line.split(" ")[0].strip()
    return ""


def _shortcut_install_dir() -> Path | None:
    lnk = START_MENU / f"{APP_NAME}.lnk"
    if not lnk.is_file():
        return None
    lnk_s = str(lnk).replace("'", "''")
    out = _ps_hidden(
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk_s}'); "
        "$s.TargetPath",
        timeout=15,
    )
    if not out:
        return None
    exe = Path(out.strip().strip('"'))
    if exe.name.lower() == "mediaapp.exe" and exe.is_file():
        return exe.parent
    return None


def _find_existing_install() -> tuple[Path | None, str]:
    """Возвращает (папка, установленная_версия)."""
    candidates: list[Path] = []
    for p in (DEFAULT_TARGET, _shortcut_install_dir()):
        if p and p not in candidates:
            candidates.append(p)
    for p in candidates:
        if (p / "MediaApp.exe").is_file():
            return p, _read_installed_version(p)
    return None, ""


_PRESERVE = (
    ".env",
    "cookies.txt",
    "vk_cookies.txt",
    "yandex_cookies.txt",
    "soundcloud_cookies.txt",
    "history.db",
    "config",
    "file_cache",
    ".migrated_from_install",
    META_NAME,
)


def _backup_userdata(target: Path) -> Path | None:
    if not target.exists():
        return None
    backup = target.parent / f"MediaApp_userdata_bak_{os.getpid()}"
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True, exist_ok=True)
    any_copied = False
    for name in _PRESERVE:
        src = target / name
        if src.exists():
            dest = backup / name
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
            any_copied = True
    if not any_copied:
        shutil.rmtree(backup, ignore_errors=True)
        return None
    return backup


def _restore_userdata(backup: Path | None, target: Path) -> None:
    if not backup or not backup.exists():
        return
    for item in backup.iterdir():
        dest = target / item.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest, ignore_errors=True)
            else:
                dest.unlink(missing_ok=True)
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    shutil.rmtree(backup, ignore_errors=True)


def _stop_running_app() -> None:
    """Закрыть Media App (+ Discord RPC-агент) перед обновлением."""
    import time
    import urllib.request

    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags |= subprocess.CREATE_NO_WINDOW

    # Агент слушает localhost даже будучи elevated — просим выйти мягко
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:17965/shutdown",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2.0):
            pass
        time.sleep(0.6)
    except Exception:
        pass

    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "MediaApp.exe"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            creationflags=flags,
        )
    except Exception:
        pass
    time.sleep(1.0)

    # Если elevated-агент всё ещё держит exe — ещё одна попытка через elevated taskkill
    try:
        still = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq MediaApp.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=flags,
        )
        if "MediaApp.exe" in (still.stdout or ""):
            # UAC: taskkill от админа
            try:
                import ctypes

                ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "runas",
                    "taskkill.exe",
                    "/F /IM MediaApp.exe",
                    None,
                    0,
                )
                time.sleep(1.2)
            except Exception:
                pass
    except Exception:
        pass


def _replace_install_dir(src: Path, target: Path) -> None:
    """Заменить папку установки. Никогда не move() внутрь существующего target.

    Иначе при залоченных файлах получается MediaApp\\MediaApp_install_tmp и битый _internal.
    """
    bad = _verify_install(src)
    if bad:
        raise ValueError(bad)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    old = parent / f"MediaApp_old_{uuid.uuid4().hex}"

    if target.exists():
        # A locked installation must remain intact. Deleting it after a
        # failed rename can destroy the only working copy of the app.
        target.rename(old)

    try:
        shutil.move(str(src), str(target))
        bad = _verify_install(target)
        if bad:
            raise ValueError(bad)
    except Exception:
        if target.exists():
            # Retain the partial replacement for diagnosis, and free the
            # original path for rollback without recursive deletion.
            target.rename(parent / f"MediaApp_failed_{uuid.uuid4().hex}")
        if old.exists():
            old.rename(target)
        raise

    if old.exists():
        shutil.rmtree(old, ignore_errors=True)


def _verify_install(target: Path) -> str | None:
    if not (target / "MediaApp.exe").is_file():
        return f"Не найден MediaApp.exe в\n{target}"
    index = target / "_internal" / "web" / "static" / "index.html"
    if not index.is_file():
        index = target / "web" / "static" / "index.html"
    if not index.is_file():
        return (
            "Неполная установка (нет web/static).\n"
            "Закрой Media App полностью и запусти установщик ещё раз."
        )
    return None


def _do_install(target: Path, desktop: bool, status) -> tuple[bool, str]:
    zpath = _payload_zip()
    if not zpath.is_file():
        return False, f"Не найден payload.zip:\n{zpath}"

    status("Распаковка…")
    staging = None
    userdata_bak = None

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="MediaApp_install_tmp_", dir=target.parent))
        with zipfile.ZipFile(zpath, "r") as zf:
            zf.extractall(staging)

        src = staging
        nested = staging / "MediaApp"
        if (nested / "MediaApp.exe").is_file():
            src = nested

        bad = _verify_install(src)
        if bad:
            return False, bad
        status("Закрываю Media App…")
        _stop_running_app()
        status("Копирование файлов…")
        if target.exists():
            userdata_bak = _backup_userdata(target)
        # Prepare user data before swapping directories so a copy failure
        # leaves the complete previous installation untouched.
        _restore_userdata(userdata_bak, src)
        userdata_bak = None
        _write_meta(src)
        _replace_install_dir(src, target)
    except Exception as e:
        msg = str(e)
        if "WinError 5" in msg or "Отказано в доступе" in msg or "Access is denied" in msg:
            return (
                False,
                "Ошибка установки: отказано в доступе к MediaApp.exe.\n\n"
                "Обычно файл держит Discord RPC-агент.\n"
                "Закрой Media App → Диспетчер задач → сними все MediaApp.exe\n"
                "(при необходимости «Запуск от имени администратора») → снова установщик.",
            )
        return False, f"Ошибка установки:\n{e}"
    finally:
        if staging is not None and staging.exists() and staging.resolve() != target.resolve():
            shutil.rmtree(staging, ignore_errors=True)

    bad = _verify_install(target)
    if bad:
        return False, bad

    exe = target / "MediaApp.exe"
    ico = _bundle_dir() / "app.ico"
    if ico.is_file():
        branding = target / "branding"
        branding.mkdir(exist_ok=True)
        try:
            shutil.copy2(ico, branding / "app.ico")
            for name in ("app.png", "app-64.png"):
                src_png = _bundle_dir() / name
                if src_png.is_file():
                    shutil.copy2(src_png, branding / name)
        except OSError:
            pass

    status("Ярлыки…")
    _unblock_tree(target)

    START_MENU.mkdir(parents=True, exist_ok=True)
    _create_shortcut(START_MENU / f"{APP_NAME}.lnk", exe, target)
    unbat = _write_uninstall(target)
    _create_shortcut(START_MENU / f"Uninstall {APP_NAME}.lnk", unbat, target)
    if desktop:
        _create_shortcut(DESKTOP / f"{APP_NAME}.lnk", exe, target)

    return True, str(target)


def run_gui() -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} — установка")
    root.resizable(False, False)
    root.minsize(500, 420)
    root.geometry("520x440")

    ico = _icon_path()
    if ico and ico.suffix.lower() == ".ico":
        try:
            root.iconbitmap(default=str(ico))
        except Exception:
            pass

    existing_dir, existing_ver = _find_existing_install()
    is_update = bool(existing_dir and (existing_dir / "MediaApp.exe").is_file())
    same_or_newer = False
    if is_update and existing_ver:
        same_or_newer = _parse_version(existing_ver) >= _parse_version(APP_VERSION)

    outer = ttk.Frame(root, padding=16)
    outer.pack(fill="both", expand=True)

    ttk.Label(outer, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(outer, text=f"Установщик версии {APP_VERSION}", font=("Segoe UI", 10)).pack(
        anchor="w", pady=(2, 8)
    )

    info_var = tk.StringVar()
    if is_update:
        ver_txt = existing_ver or "неизвестна"
        if same_or_newer:
            info_var.set(
                f"Уже установлено: v{ver_txt}\n"
                f"Папка: {existing_dir}\n\n"
                f"Эта или более новая версия уже стоит. Можно переустановить поверх "
                f"(настройки и история сохранятся)."
            )
        else:
            info_var.set(
                f"Найдена установка: v{ver_txt}\n"
                f"Папка: {existing_dir}\n\n"
                f"Нажми «Обновить» — поставим {APP_VERSION} в ту же папку.\n"
                f"Настройки, cookies и история сохранятся."
            )
    else:
        info_var.set(
            "Media App ещё не найден на этом ПК.\n"
            "Выбери папку или оставь путь по умолчанию."
        )

    info_lbl = ttk.Label(outer, textvariable=info_var, justify="left", wraplength=470)
    info_lbl.pack(anchor="w", pady=(0, 10))

    ttk.Label(outer, text="Папка установки").pack(anchor="w")
    path_row = ttk.Frame(outer)
    path_row.pack(fill="x", pady=(4, 8))
    path_var = tk.StringVar(value=str(existing_dir or DEFAULT_TARGET))
    path_entry = ttk.Entry(path_row, textvariable=path_var)
    path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

    def browse() -> None:
        chosen = filedialog.askdirectory(
            title="Папка установки",
            initialdir=str(Path(path_var.get()).parent if path_var.get() else DEFAULT_TARGET.parent),
        )
        if chosen:
            path_var.set(str(Path(chosen) / "MediaApp"))

    browse_btn = ttk.Button(path_row, text="Обзор…", command=browse, width=10)
    browse_btn.pack(side="right")

    desk_var = tk.BooleanVar(value=not is_update)
    ttk.Checkbutton(outer, text="Ярлык на рабочем столе", variable=desk_var).pack(anchor="w")

    status_var = tk.StringVar(
        value="Готов к обновлению" if is_update and not same_or_newer else "Готов к установке"
    )
    ttk.Label(outer, textvariable=status_var).pack(anchor="w", pady=(14, 4))
    bar = ttk.Progressbar(outer, mode="indeterminate", length=460)
    bar.pack(fill="x")

    btns = ttk.Frame(outer)
    btns.pack(fill="x", side="bottom", pady=(18, 0))

    def set_status(text: str) -> None:
        status_var.set(text)
        root.update_idletasks()

    def finish(ok: bool, detail: str, target: Path) -> None:
        bar.stop()
        if ok:
            status_var.set("Готово")
            action = "Обновлено" if is_update else "Установлено"
            messagebox.showinfo(
                APP_NAME,
                f"{action} в:\n{detail}\n\nВерсия {APP_VERSION}.\n"
                "Меню Пуск: ярлык и удаление.\nАвтозапуск — в настройках приложения.",
            )
            if messagebox.askyesno(APP_NAME, "Запустить Media App сейчас?"):
                subprocess.Popen(
                    [str(target / "MediaApp.exe")],
                    cwd=str(target),
                    close_fds=True,
                )
            root.destroy()
        else:
            status_var.set("Ошибка")
            messagebox.showerror(APP_NAME, detail)
            install_btn.configure(state="normal")
            cancel_btn.configure(state="normal")
            browse_btn.configure(state="normal")
            path_entry.configure(state="normal")

    def start_install() -> None:
        raw = path_var.get().strip()
        if not raw:
            messagebox.showwarning(APP_NAME, "Укажите папку установки")
            return
        target = Path(raw)
        exe_exists = (target / "MediaApp.exe").is_file()

        if exe_exists:
            cur = _read_installed_version(target) or "?"
            if _parse_version(cur) >= _parse_version(APP_VERSION) and cur != "?":
                if not messagebox.askyesno(
                    APP_NAME,
                    f"Уже установлена версия {cur} (установщик: {APP_VERSION}).\n\n"
                    f"Переустановить поверх в:\n{target}\n\n"
                    "Настройки и история сохранятся.",
                ):
                    return
            elif not messagebox.askyesno(
                APP_NAME,
                f"Обновить Media App до {APP_VERSION}?\n\n"
                f"Папка: {target}\n"
                f"Сейчас: {cur}\n\n"
                "Настройки, cookies и история сохранятся.",
            ):
                return
        elif target.exists() and any(target.iterdir()):
            if not messagebox.askyesno(
                APP_NAME,
                f"Папка уже есть и не похожа на Media App:\n{target}\n\nПродолжить?",
            ):
                return

        install_btn.configure(state="disabled")
        cancel_btn.configure(state="disabled")
        browse_btn.configure(state="disabled")
        path_entry.configure(state="disabled")
        bar.start(12)
        set_status("Обновление…" if exe_exists else "Установка…")

        def worker() -> None:
            ok, detail = _do_install(target, desk_var.get(), lambda t: root.after(0, set_status, t))
            root.after(0, finish, ok, detail, target)

        threading.Thread(target=worker, daemon=True).start()

    btn_text = "Обновить" if is_update and not same_or_newer else (
        "Переустановить" if same_or_newer else "Установить"
    )
    install_btn = ttk.Button(btns, text=btn_text, command=start_install)
    install_btn.pack(side="left", ipadx=12, ipady=4)
    cancel_btn = ttk.Button(btns, text="Отмена", command=root.destroy)
    cancel_btn.pack(side="right", ipadx=8, ipady=4)

    root.update_idletasks()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_gui())
