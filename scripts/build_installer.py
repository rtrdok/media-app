"""Собрать dist\\MediaApp и упаковать в MediaApp-Installer.exe."""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_APP = ROOT / "dist" / "MediaApp"
INSTALLER_DIR = ROOT / "installer"
PAYLOAD = INSTALLER_DIR / "payload.zip"
OUT_DIR = ROOT / "dist"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
ICON = ROOT / "branding" / "app.ico"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(cwd or ROOT))


def zip_app() -> None:
    if not (DIST_APP / "MediaApp.exe").is_file():
        raise SystemExit(f"Нет сборки: {DIST_APP}\\MediaApp.exe — сначала build_exe.bat")
    if PAYLOAD.exists():
        PAYLOAD.unlink()
    print(f"Packing {DIST_APP} -> {PAYLOAD}")
    with zipfile.ZipFile(PAYLOAD, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in DIST_APP.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(DIST_APP).as_posix())


def main() -> int:
    py = str(PY if PY.is_file() else sys.executable)
    run([py, "-m", "pip", "install", "-q", "pyinstaller"])
    if not (DIST_APP / "MediaApp.exe").is_file():
        run([py, "-m", "PyInstaller", "--noconfirm", "MediaApp.spec"])
    if ICON.is_file():
        shutil.copy2(ICON, INSTALLER_DIR / "app.ico")
    for name in ("app.png", "app-64.png"):
        src = ROOT / "branding" / name
        if src.is_file():
            shutil.copy2(src, INSTALLER_DIR / name)
    zip_app()
    run(
        [
            py, "-m", "PyInstaller", "--noconfirm",
            "--distpath", str(OUT_DIR),
            "--workpath", str(ROOT / "build" / "installer"),
            "MediaAppSetup.spec",
        ],
        cwd=INSTALLER_DIR,
    )
    final = OUT_DIR / "MediaApp-Installer.exe"
    if not final.is_file():
        candidates = list(OUT_DIR.rglob("MediaApp-Installer.exe"))
        if not candidates:
            raise SystemExit("MediaApp-Installer.exe не найден после сборки")
        shutil.copy2(candidates[0], final)
    # старое имя Setup путает Проводник (стандартная иконка «установки»)
    legacy = OUT_DIR / "MediaApp-Setup.exe"
    if legacy.is_file():
        try:
            legacy.unlink()
        except OSError:
            pass
    print()
    print(f"Готово: {final}")
    print("Установка: %LOCALAPPDATA%\\MediaApp + ярлык в меню Пуск")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
