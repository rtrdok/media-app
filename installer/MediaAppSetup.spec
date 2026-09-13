# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
ICON = str(ROOT / "app.ico")
if not Path(ICON).is_file():
    ICON = str(ROOT.parent / "branding" / "app.ico")

a = Analysis(
    ["setup_main.py"],
    pathex=[],
    binaries=[],
    datas=[("payload.zip", "."), ("app.ico", ".")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MediaApp-Installer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=ICON,
)
