"""Проверка и установка обновлений с GitHub Releases."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import traceback
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from media_core.constants import APP_VERSION, GITHUB_REPO
from media_core.logging_setup import log

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

_job_lock = threading.Lock()
_job: dict = {
    "status": "idle",  # idle | downloading | applying | done | error
    "pct": 0.0,
    "message": "",
    "error": "",
    "restart": False,
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
    for a in assets:
        an = str(a.get("name") or "")
        if an == "MediaApp.zip" or an.lower() == "mediaapp.zip":
            download = str(a.get("browser_download_url") or "")
            break
    if not download:
        for a in assets:
            an = str(a.get("name") or "")
            if an.lower().endswith(".zip") and "mediaapp" in an.lower():
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


def _download_file(url: str, dest: Path) -> None:
    # Accept: */* — иначе GitHub иногда отдаёт HTML вместо бинарника
    headers = {
        **_github_headers(),
        "Accept": "application/octet-stream",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            with _job_lock:
                if total:
                    _job["pct"] = round(100.0 * done / total, 1)
                    _job["message"] = f"Скачивание… {_job['pct']}%"


def _write_apply_script(zip_path: Path, target: Path, exe_name: str = "MediaApp.exe") -> Path:
    script = Path(tempfile.gettempdir()) / "mediaapp_apply_update.bat"
    ps = Path(tempfile.gettempdir()) / "mediaapp_apply_update.ps1"
    preserve = ", ".join(f'"{n}"' for n in sorted(_PRESERVE_NAMES))
    zip_s = str(zip_path).replace("'", "''")
    target_s = str(target).replace("'", "''")
    ps_body = f"""
$ErrorActionPreference = "Continue"
$zip = '{zip_s}'
$target = '{target_s}'
$exe = Join-Path $target '{exe_name}'
$preserve = @({preserve})
Start-Sleep -Seconds 2
Get-Process MediaApp -ErrorAction SilentlyContinue | ForEach-Object {{
  try {{ $_.CloseMainWindow() | Out-Null }} catch {{}}
}}
Start-Sleep -Seconds 1
Get-Process MediaApp -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
$staging = Join-Path $env:TEMP ("MediaApp_update_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $staging -Force | Out-Null
Expand-Archive -LiteralPath $zip -DestinationPath $staging -Force
$src = $staging
$nested = Join-Path $staging "MediaApp"
if (Test-Path (Join-Path $nested "{exe_name}")) {{ $src = $nested }}
$backup = Join-Path $env:TEMP ("MediaApp_userdata_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($name in $preserve) {{
  $p = Join-Path $target $name
  if (Test-Path $p) {{
    Copy-Item -LiteralPath $p -Destination (Join-Path $backup $name) -Recurse -Force -ErrorAction SilentlyContinue
  }}
}}
Get-ChildItem -LiteralPath $target -Force -ErrorAction SilentlyContinue | ForEach-Object {{
  if ($preserve -notcontains $_.Name) {{
    Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
  }}
}}
Copy-Item -Path (Join-Path $src '*') -Destination $target -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $target -Recurse -Include *.dll,*.exe,*.pyd -ErrorAction SilentlyContinue | ForEach-Object {{
  Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue
  $ads = $_.FullName + ':Zone.Identifier'
  if (Test-Path -LiteralPath $ads) {{ Remove-Item -LiteralPath $ads -Force -ErrorAction SilentlyContinue }}
}}
foreach ($name in $preserve) {{
  $b = Join-Path $backup $name
  if (Test-Path $b) {{
    $dest = Join-Path $target $name
    if (Test-Path $dest) {{ Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue }}
    Copy-Item -LiteralPath $b -Destination $dest -Recurse -Force -ErrorAction SilentlyContinue
  }}
}}
Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $exe) {{ Start-Process -FilePath $exe -WorkingDirectory $target }}
"""
    ps.write_text(ps_body.strip() + "\n", encoding="utf-8")
    script.write_text(
        f'@echo off\npowershell -NoProfile -ExecutionPolicy Bypass -File "{ps}"\n',
        encoding="utf-8",
    )
    return script


def get_update_job() -> dict:
    with _job_lock:
        return dict(_job)


def _run_update_job(url: str) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mediaapp_dl_"))
    zip_path = tmp / "MediaApp.zip"
    try:
        with _job_lock:
            _job.update(status="downloading", pct=0.0, message="Скачивание…", error="", restart=False)
        log(f"Downloading update from {url}")
        _download_file(url, zip_path)
        if not zipfile.is_zipfile(zip_path):
            with _job_lock:
                _job.update(
                    status="error",
                    message="Скачанный файл повреждён или это не ZIP.",
                    error="not_zip",
                )
            return
        with _job_lock:
            _job.update(status="applying", pct=100.0, message="Установка… Перезапуск…")
        target = install_dir()
        script = _write_apply_script(zip_path, target)
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags |= subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            ["cmd.exe", "/c", str(script)],
            cwd=str(Path(tempfile.gettempdir())),
            creationflags=flags,
            close_fds=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with _job_lock:
            _job.update(
                status="done",
                message="Обновление скачано. Приложение перезапустится…",
                restart=True,
            )
    except Exception as e:
        log(f"Update failed: {e}\n{traceback.format_exc()}")
        with _job_lock:
            _job.update(status="error", message=f"Ошибка обновления: {e}", error=str(e))
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


def start_update_job(url: str | None = None) -> dict:
    """Сразу отвечает клиенту; скачивание идёт в фоне."""
    with _job_lock:
        if _job["status"] in ("downloading", "applying"):
            return {"ok": True, **dict(_job), "message": _job["message"] or "Уже скачивается…"}

    try:
        info = check_github_update()
    except Exception as e:
        return {"ok": False, "status": "error", "message": f"Ошибка проверки: {e}"}

    dl = (url or info.get("url") or "").strip()
    # Разрешаем скачать даже если версии совпали (переустановка), если есть URL
    if not info.get("update") and not url:
        return {
            **info,
            "ok": True,
            "status": "idle",
            "applied": False,
            "message": info.get("message") or "Обновление не нужно",
        }
    if not dl:
        return {
            **info,
            "ok": False,
            "status": "error",
            "message": "В релизе нет MediaApp.zip.",
        }

    t = threading.Thread(target=_run_update_job, args=(dl,), daemon=True)
    t.start()
    return {
        "ok": True,
        "status": "downloading",
        "message": "Скачивание обновления…",
        "current": info.get("current"),
        "remote": info.get("remote"),
        "restart": False,
    }


def download_and_apply_update(url: str | None = None) -> dict:
    """Совместимость: стартует фоновую задачу."""
    return start_update_job(url)
