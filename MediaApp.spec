# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve()
ICON = str(ROOT / "branding" / "app.ico")

datas = [
    ("web/static", "web/static"),
    ("extension", "extension"),
    ("branding", "branding"),
]
binaries = []
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("starlette")
    + collect_submodules("fastapi")
    + collect_submodules("webview")
    + [
        "web",
        "web.server",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "webview.platforms.winforms",
        "python_multipart",
        "multipart",
        "anyio",
        "pydantic",
        "imageio_ffmpeg",
        "pystray",
        "browser_cookie3",
        "mutagen",
        "media_core.library",
        "media_core.backup",
        "media_core.updater",
        "clr_loader",
        "pythonnet",
        "clr",
        "dotenv",
    ]
)

_d, _b, _h = collect_all("dotenv")
datas += _d
binaries += _b
hiddenimports += _h

for pkg in (
    "yt_dlp",
    "imageio_ffmpeg",
    "webview",
    "fastapi",
    "starlette",
    "uvicorn",
    "shazamio",
    "shazamio_core",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "hooks" / "rthook_unblock_dlls.py")],
    excludes=["customtkinter", "tkinter.test"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MediaApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MediaApp",
)
