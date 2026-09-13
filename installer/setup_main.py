"""Графический установщик Media App → %LOCALAPPDATA%\\MediaApp."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

APP_NAME = "Media App"
APP_VERSION = "1.4.3"
TARGET = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MediaApp"
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
        TARGET / "MediaApp.exe",
    ):
        if p.is_file():
            return p
    return None


def _create_shortcut(lnk: Path, target: Path, workdir: Path, args: str = "") -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    t = str(target).replace("'", "''")
    w = str(workdir).replace("'", "''")
    l = str(lnk).replace("'", "''")
    icon = str(target).replace("'", "''")
    if target.suffix.lower() == ".exe":
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
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _write_uninstall(exe: Path) -> Path:
    bat = TARGET / "Uninstall.bat"
    content = f"""@echo off
echo Removing {APP_NAME}...
powershell -NoProfile -Command "Remove-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name 'MediaApp' -ErrorAction SilentlyContinue"
del /f /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{APP_NAME}.lnk" 2>nul
del /f /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Uninstall {APP_NAME}.lnk" 2>nul
del /f /q "%USERPROFILE%\\Desktop\\{APP_NAME}.lnk" 2>nul
cd /d "%TEMP%"
timeout /t 1 /nobreak >nul
rmdir /s /q "{TARGET}"
echo Done.
pause
"""
    bat.write_text(content, encoding="utf-8")
    return bat


# в installer: при обновлении сохраняем пользовательские данные рядом с exe (legacy)
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


def _do_install(desktop: bool, status) -> tuple[bool, str]:
    zpath = _payload_zip()
    if not zpath.is_file():
        return False, f"Не найден payload.zip:\n{zpath}"

    status("Распаковка…")
    staging = TARGET.parent / "MediaApp_install_tmp"
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
        if TARGET.exists():
            userdata_bak = _backup_userdata(TARGET)
            shutil.rmtree(TARGET, ignore_errors=True)
        shutil.move(str(src), str(TARGET))
        _restore_userdata(userdata_bak, TARGET)
        userdata_bak = None
    except Exception as e:
        if userdata_bak:
            try:
                _restore_userdata(userdata_bak, TARGET)
            except Exception:
                pass
        return False, f"Ошибка установки:\n{e}"
    finally:
        if staging.exists() and staging != TARGET:
            shutil.rmtree(staging, ignore_errors=True)

    exe = TARGET / "MediaApp.exe"
    if not exe.is_file():
        return False, f"Не найден MediaApp.exe в\n{TARGET}"

    # рядом с exe кладём иконку для ярлыков/трея (на случай)
    ico = _bundle_dir() / "app.ico"
    if ico.is_file():
        branding = TARGET / "branding"
        branding.mkdir(exist_ok=True)
        try:
            shutil.copy2(ico, branding / "app.ico")
        except OSError:
            pass

# после распаковки installer тоже снимаем MOTW
    status("Ярлыки…")
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-ChildItem -LiteralPath '{TARGET}' -Recurse -Include *.dll,*.exe,*.pyd "
                f"| Unblock-File -ErrorAction SilentlyContinue",
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except Exception:
        pass

    START_MENU.mkdir(parents=True, exist_ok=True)
    _create_shortcut(START_MENU / f"{APP_NAME}.lnk", exe, TARGET)
    unbat = _write_uninstall(exe)
    _create_shortcut(START_MENU / f"Uninstall {APP_NAME}.lnk", unbat, TARGET)
    if desktop:
        _create_shortcut(DESKTOP / f"{APP_NAME}.lnk", exe, TARGET)

    return True, str(TARGET)


def run_gui() -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title(f"{APP_NAME} — установка")
    root.resizable(False, False)
    root.geometry("440x280")

    ico = _icon_path()
    if ico and ico.suffix.lower() == ".ico":
        try:
            root.iconbitmap(default=str(ico))
        except Exception:
            pass

    frm = ttk.Frame(root, padding=20)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text=APP_NAME, font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(
        frm,
        text=f"Версия {APP_VERSION}\nУстановка в:\n{TARGET}\n\n"
        "Всё нужное уже внутри (ffmpeg и библиотеки).\n"
        "PATH и доп. зависимости не требуются.",
        justify="left",
    ).pack(anchor="w", pady=(8, 12))

    desk_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(frm, text="Ярлык на рабочем столе", variable=desk_var).pack(anchor="w")

    status_var = tk.StringVar(value="Готов к установке")
    ttk.Label(frm, textvariable=status_var).pack(anchor="w", pady=(12, 4))
    bar = ttk.Progressbar(frm, mode="indeterminate", length=380)
    bar.pack(fill="x")

    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(16, 0))

    def set_status(text: str) -> None:
        status_var.set(text)
        root.update_idletasks()

    def finish(ok: bool, detail: str) -> None:
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
                    [str(TARGET / "MediaApp.exe")],
                    cwd=str(TARGET),
                    close_fds=True,
                )
            root.destroy()
        else:
            status_var.set("Ошибка")
            messagebox.showerror(APP_NAME, detail)
            install_btn.configure(state="normal")
            cancel_btn.configure(state="normal")

    def start_install() -> None:
        if TARGET.exists() and not messagebox.askyesno(
            APP_NAME, f"Папка уже есть:\n{TARGET}\n\nПерезаписать?"
        ):
            return
        install_btn.configure(state="disabled")
        cancel_btn.configure(state="disabled")
        bar.start(12)
        set_status("Установка…")

        def worker() -> None:
            ok, detail = _do_install(desk_var.get(), lambda t: root.after(0, set_status, t))
            root.after(0, finish, ok, detail)

        threading.Thread(target=worker, daemon=True).start()

    install_btn = ttk.Button(btns, text="Установить", command=start_install)
    install_btn.pack(side="left")
    cancel_btn = ttk.Button(btns, text="Отмена", command=root.destroy)
    cancel_btn.pack(side="right")

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_gui())
