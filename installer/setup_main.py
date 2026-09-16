"""Графический установщик Media App → выбор папки, ярлыки."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from tkinter import filedialog

APP_NAME = "Media App"
APP_VERSION = "1.5.1"
DEFAULT_TARGET = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MediaApp"
START_MENU = (
    Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
)
DESKTOP = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


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


def _ps_hidden(command: str, timeout: int = 30) -> None:
    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags |= subprocess.CREATE_NO_WINDOW
    subprocess.run(
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


def _do_install(target: Path, desktop: bool, status) -> tuple[bool, str]:
    zpath = _payload_zip()
    if not zpath.is_file():
        return False, f"Не найден payload.zip:\n{zpath}"

    status("Распаковка…")
    staging = target.parent / "MediaApp_install_tmp"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    userdata_bak = None

    try:
        with zipfile.ZipFile(zpath, "r") as zf:
            zf.extractall(staging)

        src = staging
        nested = staging / "MediaApp"
        if (nested / "MediaApp.exe").is_file():
            src = nested

        status("Копирование файлов…")
        if target.exists():
            userdata_bak = _backup_userdata(target)
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(src), str(target))
        _restore_userdata(userdata_bak, target)
        userdata_bak = None
    except Exception as e:
        if userdata_bak:
            try:
                _restore_userdata(userdata_bak, target)
            except Exception:
                pass
        return False, f"Ошибка установки:\n{e}"
    finally:
        if staging.exists() and staging != target:
            shutil.rmtree(staging, ignore_errors=True)

    exe = target / "MediaApp.exe"
    if not exe.is_file():
        return False, f"Не найден MediaApp.exe в\n{target}"

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
    root.minsize(480, 380)
    root.geometry("500x400")

    ico = _icon_path()
    if ico and ico.suffix.lower() == ".ico":
        try:
            root.iconbitmap(default=str(ico))
        except Exception:
            pass

    # шапка + контент + кнопки всегда внизу (не обрезаются)
    outer = ttk.Frame(root, padding=16)
    outer.pack(fill="both", expand=True)

    ttk.Label(outer, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(outer, text=f"Версия {APP_VERSION}", font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 10))

    ttk.Label(outer, text="Папка установки").pack(anchor="w")
    path_row = ttk.Frame(outer)
    path_row.pack(fill="x", pady=(4, 8))
    path_var = tk.StringVar(value=str(DEFAULT_TARGET))
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

    ttk.Label(
        outer,
        text="Всё нужное уже внутри (ffmpeg и библиотеки).\nPATH и доп. зависимости не требуются.",
        justify="left",
    ).pack(anchor="w", pady=(4, 10))

    desk_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(outer, text="Ярлык на рабочем столе", variable=desk_var).pack(anchor="w")

    status_var = tk.StringVar(value="Готов к установке")
    ttk.Label(outer, textvariable=status_var).pack(anchor="w", pady=(14, 4))
    bar = ttk.Progressbar(outer, mode="indeterminate", length=440)
    bar.pack(fill="x")

    # кнопки — отдельная нижняя полоса
    btns = ttk.Frame(outer)
    btns.pack(fill="x", side="bottom", pady=(18, 0))

    def set_status(text: str) -> None:
        status_var.set(text)
        root.update_idletasks()

    def finish(ok: bool, detail: str, target: Path) -> None:
        bar.stop()
        if ok:
            status_var.set("Готово")
            messagebox.showinfo(
                APP_NAME,
                f"Установлено в:\n{detail}\n\nМеню Пуск: ярлык и удаление.\n"
                "Автозапуск — в настройках приложения.",
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
        if target.exists() and not messagebox.askyesno(
            APP_NAME, f"Папка уже есть:\n{target}\n\nПерезаписать?"
        ):
            return
        install_btn.configure(state="disabled")
        cancel_btn.configure(state="disabled")
        browse_btn.configure(state="disabled")
        path_entry.configure(state="disabled")
        bar.start(12)
        set_status("Установка…")

        def worker() -> None:
            ok, detail = _do_install(target, desk_var.get(), lambda t: root.after(0, set_status, t))
            root.after(0, finish, ok, detail, target)

        threading.Thread(target=worker, daemon=True).start()

    install_btn = ttk.Button(btns, text="Установить", command=start_install)
    install_btn.pack(side="left", ipadx=12, ipady=4)
    cancel_btn = ttk.Button(btns, text="Отмена", command=root.destroy)
    cancel_btn.pack(side="right", ipadx=8, ipady=4)

    root.update_idletasks()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_gui())
