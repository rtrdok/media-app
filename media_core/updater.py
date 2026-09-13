"""Проверка и установка обновлений с GitHub Releases."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from media_core.constants import APP_VERSION, GITHUB_REPO
from media_core.logging_setup import log

# Файлы/папки пользовательских данных — не трогаем при обновлении бинарников
_PRESERVE_NAMES = {
    ".env",
    "cookies.txt",
    "vk_cookies.txt",
    "yandex_cookies.txt",
    "soundcloud_cookies.txt",
    "history.db",
    "media_app.log",
    "config",
    "file_cache",
}


def _parse_version(v: str) -> tuple[int, ...]:
    s = (v or "").strip().lstrip("vV")
    parts = re.findall(r"\d+", s)
    if not parts:
        return (0,)
    return tuple(int(x) for x in parts[:4])


def is_newer(remote: str, current: str = APP_VERSION) -> bool:
    return _parse_version(remote) > _parse_version(current)


def install_dir() -> Path:
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _github_headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"MediaApp/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=_github_headers())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def check_github_update() -> dict:
    """Сверяет APP_VERSION с latest GitHub Release."""
    repo = (GITHUB_REPO or "").strip()
    if not repo or "/" not in repo:
        return {
            "ok": True,
            "current": APP_VERSION,
            "remote": "",
            "update": False,
            "url": "",
            "changelog": "",
            "message": "Репозиторий обновлений не настроен.",
        }

    api = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        data = _fetch_json(api)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {
                "ok": True,
                "current": APP_VERSION,
                "remote": "",
                "update": False,
                "url": "",
                "changelog": "",
                "message": "Релизов на GitHub пока нет — у тебя актуальная сборка.",
            }
        return {
            "ok": False,
            "current": APP_VERSION,
            "remote": "",
            "update": False,
            "url": "",
            "error": f"GitHub HTTP {e.code}",
            "message": f"Не удалось проверить обновления (HTTP {e.code}).",
        }
    except Exception as e:
        return {
            "ok": False,
            "current": APP_VERSION,
            "remote": "",
            "update": False,
            "url": "",
            "error": str(e),
            "message": f"Ошибка проверки: {e}",
        }

    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    remote = tag.lstrip("vV")
    body = str(data.get("body") or "").strip()
    assets = data.get("assets") or []
    download = ""
    # предпочитаем zip портативной сборки
    for name_hint in ("MediaApp.zip", "mediaapp.zip", ".zip"):
        for a in assets:
            an = str(a.get("name") or "")
            if name_hint == ".zip":
                if an.lower().endswith(".zip") and "MediaApp" in an:
                    download = str(a.get("browser_download_url") or "")
                    break
            elif an == name_hint or an.lower() == name_hint:
                download = str(a.get("browser_download_url") or "")
                break
        if download:
            break
    if not download:
        for a in assets:
            an = str(a.get("name") or "").lower()
            if an.endswith(".exe") and "installer" in an:
                download = str(a.get("browser_download_url") or "")
                break

    newer = bool(remote and is_newer(remote, APP_VERSION))
    return {
        "ok": True,
        "current": APP_VERSION,
        "remote": remote,
        "tag": tag,
        "update": newer,
        "url": download,
        "html_url": str(data.get("html_url") or ""),
        "changelog": body,
        "message": (
            f"Доступна версия {remote}"
            if newer
            else "Установлена актуальная версия"
        ),
    }


def _download_file(url: str, dest: Path, progress: dict | None = None) -> None:
    req = urllib.request.Request(url, headers=_github_headers())
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress is not None and total:
                progress["pct"] = round(100.0 * done / total, 1)
                progress["bytes"] = done
                progress["total"] = total


def _write_apply_script(zip_path: Path, target: Path, exe_name: str = "MediaApp.exe") -> Path:
    """BAT: ждёт закрытия процесса, распаковывает, сохраняет userdata, запускает снова."""
    script = Path(tempfile.gettempdir()) / "mediaapp_apply_update.bat"
    # PowerShell внутри bat надёжнее для копирования с exclude
    ps = Path(tempfile.gettempdir()) / "mediaapp_apply_update.ps1"
    preserve = ", ".join(f'"{n}"' for n in sorted(_PRESERVE_NAMES))
    ps_body = f"""
$ErrorActionPreference = "Stop"
$zip = "{str(zip_path).replace('"', '`"')}"
$target = "{str(target).replace('"', '`"')}"
$exe = Join-Path $target "{exe_name}"
$preserve = @({preserve})
Start-Sleep -Seconds 2
Get-Process MediaApp -ErrorAction SilentlyContinue | ForEach-Object {{
  try {{ $_.CloseMainWindow() | Out-Null }} catch {{}}
}}
Start-Sleep -Seconds 1
Get-Process MediaApp -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
$staging = Join-Path $env:TEMP ("MediaApp_update_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $staging -Force | Out-Null
Expand-Archive -LiteralPath $zip -DestinationPath $staging -Force
$src = $staging
$nested = Join-Path $staging "MediaApp"
if (Test-Path (Join-Path $nested "{exe_name}")) {{ $src = $nested }}
# backup user data
$backup = Join-Path $env:TEMP ("MediaApp_userdata_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($name in $preserve) {{
  $p = Join-Path $target $name
  if (Test-Path $p) {{
    Copy-Item -LiteralPath $p -Destination (Join-Path $backup $name) -Recurse -Force
  }}
}}
# replace app files (remove non-userdata)
Get-ChildItem -LiteralPath $target -Force | ForEach-Object {{
  if ($preserve -notcontains $_.Name) {{
    Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
  }}
}}
Copy-Item -Path (Join-Path $src "*") -Destination $target -Recurse -Force
foreach ($name in $preserve) {{
  $b = Join-Path $backup $name
  if (Test-Path $b) {{
    $dest = Join-Path $target $name
    if (Test-Path $dest) {{ Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue }}
    Copy-Item -LiteralPath $b -Destination $dest -Recurse -Force
  }}
}}
Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
Start-Process -FilePath $exe -WorkingDirectory $target
"""
    ps.write_text(ps_body.strip() + "\n", encoding="utf-8")
    bat_body = f'@echo off\npowershell -NoProfile -ExecutionPolicy Bypass -File "{ps}"\n'
    script.write_text(bat_body, encoding="utf-8")
    return script


def download_and_apply_update(url: str | None = None) -> dict:
    """Скачивает zip и запускает внешний скрипт обновления. Клиент должен закрыться."""
    info = check_github_update()
    if not info.get("ok"):
        return info
    if not info.get("update"):
        return {**info, "ok": True, "applied": False, "message": info.get("message") or "Обновление не нужно"}
    dl = (url or info.get("url") or "").strip()
    if not dl:
        return {
            **info,
            "ok": False,
            "applied": False,
            "message": "В релизе нет MediaApp.zip — приложи архив к GitHub Release.",
        }

    target = install_dir()
    tmp = Path(tempfile.mkdtemp(prefix="mediaapp_dl_"))
    zip_path = tmp / "MediaApp.zip"
    progress = {"pct": 0.0}
    try:
        log(f"Downloading update from {dl}")
        _download_file(dl, zip_path, progress)
        if not zipfile.is_zipfile(zip_path):
            # возможно installer exe — не применяем автоматически
            return {
                **info,
                "ok": False,
                "applied": False,
                "message": "Скачанный файл не ZIP. Залей MediaApp.zip в Release.",
            }
        script = _write_apply_script(zip_path, target)
        # detach
        subprocess.Popen(
            ["cmd", "/c", str(script)],
            cwd=str(Path(tempfile.gettempdir())),
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
        return {
            **info,
            "ok": True,
            "applied": True,
            "progress": progress,
            "message": "Обновление скачано. Приложение перезапустится…",
            "restart": True,
        }
    except Exception as e:
        log(f"Update failed: {e}")
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
        return {**info, "ok": False, "applied": False, "error": str(e), "message": f"Ошибка обновления: {e}"}
