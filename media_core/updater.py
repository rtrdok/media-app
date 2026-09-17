"""Проверка и установка обновлений с GitHub Releases."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
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
    "install_meta.json",
}

_job_lock = threading.Lock()
_job: dict = {
    "status": "idle",  # idle | downloading | applying | done | error
    "pct": 0.0,
    "bytes_done": 0,
    "bytes_total": 0,
    "speed_bps": 0.0,
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
    """JSON с GitHub API — всегда напрямую.

    Системный VPN/прокси Windows не меняем (только игнорируем для этого запроса).
    """
    req = urllib.request.Request(url, headers=_github_headers())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=20) as r:
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
    zip_url = ""
    installer_url = ""
    for a in assets:
        an = str(a.get("name") or "")
        low = an.lower()
        href = str(a.get("browser_download_url") or "")
        if not href:
            continue
        if low == "mediaapp-installer.exe" or (low.endswith(".exe") and "installer" in low):
            installer_url = href
        elif low == "mediaapp.zip" or (low.endswith(".zip") and "mediaapp" in low):
            if not zip_url:
                zip_url = href

    # Installer надёжнее zip-replace на машинах с системным VPN/PAC
    download = installer_url or zip_url
    html_url = str(data.get("html_url") or "") or f"https://github.com/{repo}/releases/latest"

    newer = bool(remote and is_newer(remote, APP_VERSION))
    return {
        "ok": True,
        "current": APP_VERSION,
        "remote": remote,
        "tag": tag,
        "update": newer,
        "url": download,
        "zip_url": zip_url,
        "installer_url": installer_url,
        "html_url": html_url,
        "changelog": body,
        "message": (
            f"Доступна версия {remote}"
            if newer
            else "Установлена актуальная версия"
        ),
    }


def _fmt_bytes(n: float) -> str:
    n = float(n or 0)
    if n < 1024:
        return f"{n:.0f} Б"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} КБ"
    return f"{n / (1024 * 1024):.1f} МБ"


def _set_job(**kwargs) -> None:
    with _job_lock:
        _job.update(kwargs)


def _download_headers(url: str) -> dict[str, str]:
    """Для CDN GitHub — лёгкие заголовки; API-заголовки часто ломают прокси."""
    ua = f"MediaApp/{APP_VERSION}"
    if "api.github.com" in (url or ""):
        return {**_github_headers(), "Accept": "application/octet-stream"}
    return {
        "User-Agent": ua,
        "Accept": "application/octet-stream,*/*",
    }


def _open_download_requests(url: str, *, connect_timeout: float = 15.0):
    """Прямое скачивание через requests (игнор env/WinINET прокси)."""
    import requests

    headers = _download_headers(url)
    sess = requests.Session()
    sess.trust_env = False
    sess.proxies = {"http": None, "https": None}
    r = sess.get(
        url,
        headers=headers,
        stream=True,
        timeout=(connect_timeout, 120),
        allow_redirects=True,
    )
    r.raise_for_status()
    total = int(r.headers.get("Content-Length") or 0)

    def _iter():
        try:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if chunk:
                    yield chunk
        finally:
            r.close()
            sess.close()

    return total, _iter()


def _download_via_curl(url: str, dest: Path) -> None:
    """curl.exe --noproxy *: скачать напрямую, не трогая системный VPN/прокси."""
    import time

    from media_core.utils import subprocess_no_window_kwargs

    curl = shutil.which("curl") or shutil.which("curl.exe")
    # GUI/.exe часто без PATH — типичный путь Windows
    if not curl:
        for cand in (
            Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "curl.exe",
            Path(r"C:\Windows\System32\curl.exe"),
        ):
            if cand.is_file():
                curl = str(cand)
                break
    if not curl:
        raise RuntimeError("curl.exe не найден")

    if dest.is_file():
        try:
            dest.unlink()
        except OSError:
            pass

    # -sS: без прогресса в stderr (иначе PIPE переполняется и curl зависает)
    cmd = [
        curl,
        "-L",
        "--fail",
        "-sS",
        "--noproxy",
        "*",
        "--connect-timeout",
        "15",
        "--max-time",
        "900",
        "-A",
        f"MediaApp/{APP_VERSION}",
        "-o",
        str(dest),
        url,
    ]
    env = os.environ.copy()
    for k in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        env.pop(k, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    _set_job(message="Скачивание обновления…", pct=0.0, bytes_done=0, bytes_total=0)
    log.info("Update download via curl: %s %s", curl, url)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,  # не PIPE — иначе deadlock на progress meter
        env=env,
        **subprocess_no_window_kwargs(),
    )
    t0 = time.monotonic()
    last_done = 0
    last_t = t0
    stalled_since = t0
    while proc.poll() is None:
        time.sleep(0.35)
        done = dest.stat().st_size if dest.is_file() else 0
        now = time.monotonic()
        dt = max(0.001, now - last_t)
        speed = (done - last_done) / dt
        if done > last_done:
            stalled_since = now
        last_t = now
        last_done = done
        # оценка ~90 МБ, пока нет Content-Length
        est_total = max(done, 90 * 1024 * 1024) if done else 0
        pct = round(100.0 * done / est_total, 1) if est_total else 0.0
        _set_job(
            pct=pct,
            bytes_done=done,
            bytes_total=est_total,
            speed_bps=round(speed, 1),
            message=(
                f"Скачивание… {_fmt_bytes(done)}"
                + (f" · {_fmt_bytes(speed)}/с" if done else " (ожидание ответа)…")
            ),
        )
        if done == 0 and now - stalled_since > 45:
            proc.kill()
            raise TimeoutError("curl: нет данных за 45 с")
        if now - t0 > 900:
            proc.kill()
            raise TimeoutError("curl: превышено время скачивания")

    if proc.returncode != 0:
        raise RuntimeError(f"curl exit {proc.returncode}")
    if not dest.is_file() or dest.stat().st_size < 1024:
        raise RuntimeError("curl: пустой файл")
    size = dest.stat().st_size
    _set_job(pct=100.0, bytes_done=size, bytes_total=size, message=f"Скачано {_fmt_bytes(size)}")


def _write_stream_to_file(dest: Path, total: int, chunks) -> None:
    import time

    done = 0
    t0 = time.monotonic()
    last_t = t0
    last_done = 0
    speed = 0.0
    with open(dest, "wb") as out:
        for chunk in chunks:
            out.write(chunk)
            done += len(chunk)
            now = time.monotonic()
            if now - last_t >= 0.25:
                dt = max(0.001, now - last_t)
                speed = (done - last_done) / dt
                last_t = now
                last_done = done
            elapsed = max(0.001, now - t0)
            if speed <= 0:
                speed = done / elapsed
            pct = round(100.0 * done / total, 1) if total else 0.0
            if total:
                msg = (
                    f"Скачивание… {pct}% · {_fmt_bytes(done)} / {_fmt_bytes(total)} · "
                    f"{_fmt_bytes(speed)}/с"
                )
            else:
                msg = f"Скачивание… {_fmt_bytes(done)} · {_fmt_bytes(speed)}/с"
            _set_job(
                pct=pct,
                bytes_done=done,
                bytes_total=total,
                speed_bps=round(speed, 1),
                message=msg,
            )
    if not done or (total and done != total):
        raise RuntimeError(f"Неполное обновление: получено {done} байт, ожидалось {total}.")
    _set_job(
        pct=100.0,
        bytes_done=done,
        bytes_total=total or done,
        message=f"Скачано {_fmt_bytes(done)}",
    )


def _download_via_urllib(url: str, dest: Path) -> None:
    """Прямое скачивание через urllib (без системного прокси) — без curl."""
    import time

    req = urllib.request.Request(url, headers=_download_headers(url))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    _set_job(message="Скачивание обновления…", pct=0.0, bytes_done=0, bytes_total=0)
    log.info("Update download via urllib direct: %s", url)
    with opener.open(req, timeout=30) as r:
        total = int(r.headers.get("Content-Length") or 0)
        _set_job(bytes_total=total)
        done = 0
        t0 = time.monotonic()
        last_t = t0
        last_done = 0
        with open(dest, "wb") as out:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                if now - last_t >= 0.25:
                    dt = max(0.001, now - last_t)
                    speed = (done - last_done) / dt
                    last_t = now
                    last_done = done
                    pct = round(100.0 * done / total, 1) if total else 0.0
                    _set_job(
                        pct=pct,
                        bytes_done=done,
                        bytes_total=total or done,
                        speed_bps=round(speed, 1),
                        message=(
                            f"Скачивание… {pct}% · {_fmt_bytes(done)}"
                            + (f" / {_fmt_bytes(total)}" if total else "")
                            + f" · {_fmt_bytes(speed)}/с"
                        ),
                    )
    size = dest.stat().st_size if dest.is_file() else 0
    if size < 1024:
        raise RuntimeError("urllib: пустой файл")
    if total and size != total:
        raise RuntimeError(f"Неполное обновление: получено {size} байт, ожидалось {total}.")
    _set_job(pct=100.0, bytes_done=size, bytes_total=size, message=f"Скачано {_fmt_bytes(size)}")


def _download_file(url: str, dest: Path) -> None:
    """Скачивает ZIP с GitHub напрямую. Прокси не нужен (GitHub в РФ доступен).

    Системный VPN/прокси Windows не отключаем и не меняем — только не используем
    их для этого скачивания.

    1) urllib напрямую (без pipe/curl deadlock)
    2) curl.exe --noproxy * -sS
    3) requests без прокси
    """
    last_err: Exception | None = None
    manual = "https://github.com/rtrdok/media-app/releases/latest"

    for label, fn in (
        ("curl", lambda: _download_via_curl(url, dest)),
        ("urllib", lambda: _download_via_urllib(url, dest)),
    ):
        try:
            fn()
            return
        except Exception as e:
            last_err = e
            log.warning("Update download %s failed: %s", label, e)
            try:
                if dest.is_file():
                    dest.unlink()
            except OSError:
                pass

    # 3) requests direct with hard wall-clock budget on connect
    try:
        _set_job(message="Скачивание обновления…", pct=0.0, bytes_done=0, bytes_total=0)
        log.info("Update download requests direct url=%s", url)
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_open_download_requests, url, connect_timeout=10.0)
            try:
                total, chunks = fut.result(timeout=25.0)
            except FuturesTimeout as e:
                raise TimeoutError("requests: нет ответа за 25 с") from e
        _set_job(
            message=(
                f"Скачивание… 0% · 0 Б / {_fmt_bytes(total)}"
                if total
                else "Скачивание… соединение установлено"
            ),
            bytes_total=total,
        )
        _write_stream_to_file(dest, total, chunks)
        return
    except Exception as e:
        last_err = e
        log.warning("Update download requests failed: %s", e)
        try:
            if dest.is_file():
                dest.unlink()
        except OSError:
            pass

    raise RuntimeError(
        f"Не удалось скачать обновление. "
        f"Скачайте MediaApp-Installer.exe вручную: {manual} ({last_err})"
    )


def _validate_update_zip(zip_path: Path) -> None:
    """Reject corrupt/incomplete release packages before closing the application."""
    with zipfile.ZipFile(zip_path) as archive:
        names = set()
        for item in archive.infolist():
            name = item.filename.replace("\\", "/")
            if (name.startswith("/") or ":" in name or ".." in name.split("/")
                    or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise RuntimeError(f"Недопустимый путь в ZIP: {item.filename}")
            if not item.is_dir():
                names.add(name.casefold())
        valid = any(
            prefix + "mediaapp.exe" in names
            and any(prefix + index in names for index in (
                "_internal/web/static/index.html", "web/static/index.html"
            ))
            for prefix in ("", "mediaapp/")
        )
        if not valid:
            raise RuntimeError("Неполный ZIP обновления: отсутствует MediaApp.exe или web/static/index.html.")
        bad_file = archive.testzip()
        if bad_file:
            raise RuntimeError(f"Повреждённый файл в ZIP: {bad_file}")


def _write_apply_script(zip_path: Path, target: Path, exe_name: str = "MediaApp.exe") -> Path:
    target = target.resolve()
    if target == target.parent or not (target / exe_name).is_file():
        raise RuntimeError("Папка установки не содержит MediaApp.exe; замена отменена.")
    if Path(exe_name).name != exe_name or "'" in exe_name:
        raise ValueError("Invalid executable name")
    # Each job owns its script; another instance must not overwrite it.
    ps = zip_path.parent / "apply_update.ps1"
    preserve = ", ".join(f'"{n}"' for n in sorted(_PRESERVE_NAMES))
    zip_s = str(zip_path).replace("'", "''")
    target_s = str(target).replace("'", "''")
    ps_body = f"""
$ErrorActionPreference = "Stop"
$zip = '{zip_s}'
$target = '{target_s}'
$exe = Join-Path $target '{exe_name}'
$preserve = @({preserve})
$parent = [System.IO.Path]::GetDirectoryName($target)
$staging = Join-Path $parent ("MediaApp_update_" + [guid]::NewGuid().ToString("N"))
$backup = Join-Path $parent ("MediaApp_before_update_" + [guid]::NewGuid().ToString("N"))
$swapped = $false
try {{
  if (!(Test-Path -LiteralPath $exe -PathType Leaf)) {{ throw "Installation executable is missing" }}
  New-Item -ItemType Directory -Path $staging | Out-Null
  Expand-Archive -LiteralPath $zip -DestinationPath $staging
  $src = $staging
  $nested = Join-Path $staging "MediaApp"
  if (Test-Path -LiteralPath (Join-Path $nested "{exe_name}") -PathType Leaf) {{ $src = $nested }}
  $hasUi = (Test-Path -LiteralPath (Join-Path $src '_internal/web/static/index.html') -PathType Leaf) -or
           (Test-Path -LiteralPath (Join-Path $src 'web/static/index.html') -PathType Leaf)
  if (!(Test-Path -LiteralPath (Join-Path $src '{exe_name}') -PathType Leaf) -or !$hasUi) {{
    throw "Incomplete update package"
  }}
  # The elevated Discord helper may retain MediaApp.exe between app launches.
  # Ask it to exit before replacing the installation.
  try {{
    Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:17965/shutdown' -Method POST -Body '{{}}' -ContentType 'application/json' -TimeoutSec 2 | Out-Null
    Start-Sleep -Milliseconds 600
  }} catch {{}}
  $deadline = (Get-Date).AddSeconds(60)
  while (Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue) {{
    if ((Get-Date) -gt $deadline) {{ throw "Application did not exit; installation unchanged" }}
    Start-Sleep -Milliseconds 250
  }}
  foreach ($name in $preserve) {{
    $p = Join-Path $target $name
    if (Test-Path -LiteralPath $p) {{
      $dest = Join-Path $src $name
      if (Test-Path -LiteralPath $dest) {{ Remove-Item -LiteralPath $dest -Recurse -Force }}
      Copy-Item -LiteralPath $p -Destination $dest -Recurse -Force
    }}
  }}
  # Staging and backup are siblings on the same volume. Rename failure leaves
  # the old installation intact; never fall back to deleting a locked target.
  Move-Item -LiteralPath $target -Destination $backup
  try {{
    Move-Item -LiteralPath $src -Destination $target
    $swapped = $true
    Start-Process -FilePath $exe -WorkingDirectory $target -WindowStyle Hidden -ErrorAction Stop
  }} catch {{
    if ($swapped) {{ Move-Item -LiteralPath $target -Destination ($backup + '.failed') }}
    if (!(Test-Path -LiteralPath $target)) {{ Move-Item -LiteralPath $backup -Destination $target }}
    throw
  }}
  # Keep the previous install recoverable, including files unknown to this version.
  "Previous installation: $backup" | Set-Content -LiteralPath (Join-Path (Split-Path $zip) 'update-result.txt')
}} catch {{
  $_ | Out-String | Set-Content -LiteralPath (Join-Path (Split-Path $zip) 'update-error.txt')
  exit 1
}}
"""
    # Windows PowerShell 5 needs the BOM to preserve Cyrillic installation paths.
    ps.write_text(ps_body.strip() + "\n", encoding="utf-8-sig")
    return ps


def get_update_job() -> dict:
    with _job_lock:
        return dict(_job)


def _run_update_job(url: str) -> None:
    tmp = None
    try:
        if not getattr(sys, "frozen", False):
            raise RuntimeError("Автообновление доступно только в установленной сборке MediaApp.exe.")
        tmp = Path(tempfile.mkdtemp(prefix="mediaapp_dl_"))
        is_exe = url.lower().split("?", 1)[0].endswith(".exe")
        dest = tmp / ("MediaApp-Installer.exe" if is_exe else "MediaApp.zip")
        with _job_lock:
            _job.update(
                status="downloading",
                pct=0.0,
                bytes_done=0,
                bytes_total=0,
                speed_bps=0.0,
                message="Скачивание обновления…",
                error="",
                restart=False,
            )
        log.info("Downloading update from %s", url)
        _download_file(url, dest)

        if is_exe:
            from media_core.process_cleanup import arm_hard_exit, preserve_child_process

            with _job_lock:
                _job.update(status="applying", pct=100.0, message="Запуск установщика…")
            flags = 0
            if hasattr(subprocess, "DETACHED_PROCESS"):
                flags |= subprocess.DETACHED_PROCESS
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                flags |= subprocess.CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(
                [str(dest)],
                cwd=str(dest.parent),
                creationflags=flags,
                close_fds=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            preserve_child_process(process.pid)
            with _job_lock:
                _job.update(
                    status="done",
                    message="Установщик запущен — заверши установку в его окне.",
                    restart=True,
                )
            arm_hard_exit(1.5)
            return

        _validate_update_zip(dest)
        from media_core.process_cleanup import arm_hard_exit, preserve_child_process

        with _job_lock:
            _job.update(status="applying", pct=100.0, message="Установка… Перезапуск…")
        target = install_dir()
        script = _write_apply_script(dest, target)
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags |= subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=str(Path(tempfile.gettempdir())),
            creationflags=flags,
            close_fds=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        preserve_child_process(process.pid)
        with _job_lock:
            _job.update(
                status="done",
                message="Обновление скачано. Приложение перезапустится…",
                restart=True,
            )
        arm_hard_exit(1.5)
    except Exception as e:
        log.exception("Update failed: %s", e)
        with _job_lock:
            _job.update(
                status="error",
                message=(
                    f"Ошибка обновления: {e}. "
                    "Открой GitHub Releases и поставь MediaApp-Installer.exe вручную."
                ),
                error=str(e),
                restart=False,
            )
        try:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


def start_update_job(url: str | None = None) -> dict:
    """Сразу отвечает клиенту; скачивание идёт в фоне.

    ``url`` retained only for compatibility with older callers.  Update assets
    must always be discovered from the configured GitHub release; accepting a
    caller-supplied executable URL turns an update action into code execution.
    """
    with _job_lock:
        if _job["status"] in ("downloading", "applying") or _job.get("restart"):
            return {"ok": True, **dict(_job)}
        if not getattr(sys, "frozen", False):
            message = "Автообновление доступно только в установленной сборке MediaApp.exe."
            _job.update(status="error", message=message, error="source_checkout", restart=False)
            return {"ok": False, **dict(_job)}
        # Reserve before network I/O or starting the worker. Zero bytes also
        # describes a healthy connection waiting for headers, not a dead job.
        _job.update(status="downloading", pct=0.0, bytes_done=0, bytes_total=0,
                    speed_bps=0.0, message="Проверка обновления…", error="", restart=False)
    try:
        info = check_github_update()
        if not info.get("ok"):
            message = info.get("message") or "Не удалось проверить обновления"
            _set_job(status="error", message=message, error=info.get("error") or message)
            return {**info, **get_update_job(), "ok": False}
        if not info.get("update"):
            _set_job(status="idle", message=info.get("message") or "Обновление не нужно")
            return {**info, **get_update_job(), "ok": True, "applied": False}
        dl = (info.get("url") or info.get("installer_url") or info.get("zip_url") or "").strip()
        if not dl:
            raise RuntimeError("В релизе нет Installer/ZIP. Открой страницу релизов вручную.")
        t = threading.Thread(target=_run_update_job, args=(dl,), daemon=True)
        t.start()
        snapshot = get_update_job()
        return {**info, **snapshot, "ok": snapshot["status"] != "error"}
    except Exception as e:
        _set_job(status="error", message=f"Ошибка обновления: {e}", error=str(e), restart=False)
        return {"ok": False, **get_update_job()}


def download_and_apply_update(url: str | None = None) -> dict:
    """Совместимость: стартует фоновую задачу."""
    return start_update_job(url)
