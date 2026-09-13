"""Ярлыки Windows и автозапуск."""



from __future__ import annotations



import os

import subprocess

import sys

from pathlib import Path





APP_NAME = "Media App"





def _exe_path() -> Path:

    if getattr(sys, "frozen", False):

        return Path(sys.executable).resolve()

    return Path(__file__).resolve().parent.parent / "main.py"





def _workdir() -> Path:

    if getattr(sys, "frozen", False):

        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent.parent





def _desktop() -> Path:

    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"





def _start_menu() -> Path:

    return (

        Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))

        / "Microsoft"

        / "Windows"

        / "Start Menu"

        / "Programs"

    )





def _create_shortcut(lnk: Path, target: Path, workdir: Path, args: str = "") -> None:

    lnk.parent.mkdir(parents=True, exist_ok=True)

    ps = (

        "$ws = New-Object -ComObject WScript.Shell; "

        f"$s = $ws.CreateShortcut('{str(lnk).replace(chr(39), chr(39)+chr(39))}'); "

        f"$s.TargetPath = '{str(target).replace(chr(39), chr(39)+chr(39))}'; "

        f"$s.WorkingDirectory = '{str(workdir).replace(chr(39), chr(39)+chr(39))}'; "

        f"$s.Description = '{APP_NAME}'; "

    )

    if args:

        ps += f"$s.Arguments = '{args}'; "

    ps += "$s.Save()"

    from media_core.utils import subprocess_no_window_kwargs

    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        **subprocess_no_window_kwargs(),
    )





def set_desktop_shortcut(enabled: bool) -> dict:

    lnk = _desktop() / f"{APP_NAME}.lnk"

    exe = _exe_path()

    if enabled:

        if getattr(sys, "frozen", False):

            _create_shortcut(lnk, exe, _workdir())

        else:

            py = Path(sys.executable)

            _create_shortcut(lnk, py, _workdir(), f'"{exe}"')

        return {"ok": True, "path": str(lnk), "enabled": True}

    if lnk.is_file():

        try:

            lnk.unlink()

        except OSError:

            pass

    return {"ok": True, "enabled": False}





def set_autostart(enabled: bool) -> dict:

    """HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"""

    key = r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

    name = "MediaApp"

    if enabled:

        target = _exe_path()

        if getattr(sys, "frozen", False):

            value = f'"{target}"'

        else:

            value = f'"{sys.executable}" "{target}"'

        ps = f"New-ItemProperty -Path '{key}' -Name '{name}' -Value '{value}' -PropertyType String -Force | Out-Null"

    else:

        ps = (

            f"Remove-ItemProperty -Path '{key}' -Name '{name}' -ErrorAction SilentlyContinue"

        )

    from media_core.utils import subprocess_no_window_kwargs

    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        **subprocess_no_window_kwargs(),
    )

    return {"ok": r.returncode == 0, "enabled": enabled, "log": (r.stderr or "")[-500:]}





def apply_integration(*, desktop_shortcut: bool | None = None, autostart: bool | None = None) -> dict:

    out: dict = {}

    if desktop_shortcut is not None:

        out["desktop_shortcut"] = set_desktop_shortcut(bool(desktop_shortcut))

    if autostart is not None:

        out["autostart"] = set_autostart(bool(autostart))

    return out


