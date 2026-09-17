"""Локальный HTTP API: те же функции media_core, веб-интерфейс как на макете."""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from media_core.config import BASE_DIR, COOKIES_FILE, LOG_FILE, RESOURCE_DIR
from media_core.constants import APP_VERSION, CANCELLED
from media_core.database import (
    history_add,
    history_clear,
    history_delete,
    history_list,
    history_prune_missing,
    history_search,
    history_update,
)
from media_core.download_process import get_last_download_error, process_url, save_to_downloads
from media_core.download_state import download_scope
from media_core.settings_store import (
    get_all,
    get_bool,
    get_download_dir,
    get_extension_token,
    set_download_dir,
    set_last_update_check,
    update_settings,
)
from media_core.utils import (
    PLATFORM_NAMES,
    build_source_links,
    clean_media_url,
    cleanup_temp_files,
    detect_platform,
    fmt_time,
    is_instagram_stories_url,
    is_unsupported_media_url,
    is_vk_audio_url,
    parse_time_to_seconds,
    youtube_cookies_active,
)

STATIC = RESOURCE_DIR / "web" / "static"
THUMBS = BASE_DIR / "file_cache" / "thumbs"

if not STATIC.is_dir():
    # Частая причина: битое обновление поверх запущенного exe (1.5.5 и раньше).
    raise RuntimeError(
        f"Нет папки интерфейса:\n{STATIC}\n\n"
        "Закрой Media App и поставь заново через MediaApp-Installer.exe "
        "(Обновить / Переустановить)."
    )

_LISTEN_PORT = 17865
_show_window_cb = None
_fullscreen_cb = None
_on_top_cb = None
_mini_player_cb = None
_quit_cb = None
_uvicorn_server = None
_active_file_streams: dict[str, int] = {}
_active_file_tasks: dict[str, set[asyncio.Task]] = {}


def _stream_key(path: str | Path) -> str:
    try:
        return str(Path(path).resolve()).lower()
    except OSError:
        return str(path).lower()


class _TrackedFileResponse(FileResponse):
    """Release an active-stream marker even when the client disconnects."""

    def __init__(self, path: str | Path, **kwargs):
        super().__init__(path, **kwargs)
        self._stream_key = _stream_key(path)

    async def __call__(self, scope, receive, send):
        task = asyncio.current_task()
        if task is not None:
            _active_file_tasks.setdefault(self._stream_key, set()).add(task)
        try:
            await super().__call__(scope, receive, send)
        finally:
            if task is not None:
                tasks = _active_file_tasks.get(self._stream_key)
                if tasks is not None:
                    tasks.discard(task)
                    if not tasks:
                        _active_file_tasks.pop(self._stream_key, None)
            left = _active_file_streams.get(self._stream_key, 0) - 1
            if left > 0:
                _active_file_streams[self._stream_key] = left
            else:
                _active_file_streams.pop(self._stream_key, None)


def _abort_file_streams(path: str | Path) -> int:
    """Cancel this server's responses for a file so Windows can release it."""
    key = _stream_key(path)
    current = asyncio.current_task()
    tasks = tuple(_active_file_tasks.get(key, ()))
    for task in tasks:
        if task is not current and not task.done():
            task.cancel()
    return _active_file_streams.get(key, 0)


async def _wait_for_file_streams(path: str | Path, timeout: float = 5.0) -> int:
    """Let an aborted WebView2 media request close its FileResponse handle."""
    key = _stream_key(path)
    deadline = time.monotonic() + timeout
    while _active_file_streams.get(key, 0) and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    return _active_file_streams.get(key, 0)


def set_listen_port(port: int) -> None:
    global _LISTEN_PORT
    _LISTEN_PORT = int(port)


def get_listen_port() -> int:
    return _LISTEN_PORT


def set_show_window_callback(cb) -> None:
    global _show_window_cb
    _show_window_cb = cb


def set_fullscreen_callback(cb) -> None:
    global _fullscreen_cb
    _fullscreen_cb = cb


def set_on_top_callback(cb) -> None:
    global _on_top_cb
    _on_top_cb = cb


def set_mini_player_callback(cb) -> None:
    global _mini_player_cb
    _mini_player_cb = cb


def set_quit_callback(cb) -> None:
    global _quit_cb
    _quit_cb = cb


def set_uvicorn_server(server) -> None:
    global _uvicorn_server
    _uvicorn_server = server


def stop_uvicorn_server() -> None:
    srv = _uvicorn_server
    if srv is None:
        return
    try:
        srv.should_exit = True
    except Exception:
        pass


def _fmt_height(h: int) -> str:
    """Селектор формата под целевое качество.

    Не форсируем ext=mp4 на видео (иначе часто остаётся progressive ~360p).
    Склейка/ремукс в нужный контейнер — через ffmpeg + merge_output_format.
    Для ультрашироких дублируем фильтр по width (16:9-эквивалент ярлыка YouTube).
    """
    w = int(round(h * 16 / 9))
    # не скатываться к 360p, если доступны форматы ближе к выбранному качеству
    h_min = max(144, int(h * 0.70))
    w_min = max(256, int(w * 0.70))
    return (
        f"bestvideo[height<={h}][height>={h_min}]+bestaudio/"
        f"bestvideo[width<={w}][width>={w_min}]+bestaudio/"
        f"bestvideo[height<={h}]+bestaudio/"
        f"bestvideo[width<={w}]+bestaudio/"
        f"best[height<={h}]/best[width<={w}]/best"
    )


FORMAT_MAP = {
    "144": _fmt_height(144),
    "240": _fmt_height(240),
    "360": _fmt_height(360),
    "480": _fmt_height(480),
    "720": _fmt_height(720),
    "1080": _fmt_height(1080),
    "1440": _fmt_height(1440),
    "2160": _fmt_height(2160),
    "best": "bestvideo+bestaudio/best",
}


def format_for_quality(quality: str, audio_lang: str = "") -> str:
    q = (quality or "best").strip().lower()
    lang = (audio_lang or "").strip()
    if q in FORMAT_MAP:
        base = FORMAT_MAP[q]
    elif q.isdigit():
        base = _fmt_height(int(q))
    else:
        base = FORMAT_MAP["best"]
    if lang:
        # приоритет аудио с языком
        if (q.isdigit() or q in FORMAT_MAP) and q != "best":
            h = int(q) if q.isdigit() else {"144": 144, "240": 240, "360": 360, "480": 480, "720": 720, "1080": 1080, "1440": 1440, "2160": 2160}.get(q, 720)
            return (
                f"bestvideo[height<={h}][height>={max(144, int(h * 0.70))}]+bestaudio[language={lang}]/"
                f"bestvideo[width<={int(round(h * 16 / 9))}][width>={max(256, int(h * 16 / 9 * 0.70))}]+bestaudio[language={lang}]/"
                f"bestvideo[height<={h}]+bestaudio[language={lang}]/"
                f"bestvideo[height<={h}]+bestaudio/best[height<={h}]"
            )
        return (
            f"bestvideo+bestaudio[language={lang}]/"
            f"bestvideo+bestaudio/best"
        )
    return base


_cancel = threading.Event()
_busy = False
_paused = False
_soft_pause = False
_shutting_down = False
_last: dict = {"error": "", "shazam": None, "message": "", "preview": None, "notify_pending": False}
_queue: list[dict] = []
_queue_id = 0
_queue_lock = asyncio.Lock()
_current_job: dict | None = None
_pump_task: asyncio.Task | None = None
_job_tasks: set[asyncio.Task] = set()
_SHUTDOWN_GRACE_SECONDS = 1.5
_progress: dict = {
    "stage": "",
    "percent": "",
    "speed": "",
    "eta": "",
    "indeterminate": False,
    "updated_at": 0.0,
    "started_at": 0.0,
}


def _blank_progress() -> dict:
    return {
        "stage": "",
        "percent": "",
        "speed": "",
        "eta": "",
        "indeterminate": False,
        "updated_at": time.time(),
        "started_at": 0.0,
    }


def _max_concurrent() -> int:
    try:
        n = int(get_all().get("max_concurrent_downloads") or 3)
    except (TypeError, ValueError):
        n = 3
    return max(1, min(4, n))


def _running_items() -> list[dict]:
    return [q for q in _queue if q.get("status") == "running"]


def _sync_busy_and_progress() -> None:
    """Обновить глобальные busy/progress по активным задачам (для UI)."""
    global _busy, _current_job, _progress
    running = _running_items()
    _busy = bool(running)
    _current_job = running[0] if running else None
    if not running:
        _progress = _blank_progress()
        return
    # Показать прогресс самой «свежей» активной задачи
    best = max(running, key=lambda q: float((q.get("progress") or {}).get("updated_at") or 0))
    src = best.get("progress") or _blank_progress()
    _progress = dict(src)


def _cancel_all_running() -> None:
    _cancel.set()
    for q in _running_items():
        ev = q.get("cancel_event")
        if isinstance(ev, threading.Event):
            ev.set()


def request_app_shutdown() -> None:
    """Остановить очередь загрузок и HTTP-сервер (при закрытии окна)."""
    global _shutting_down, _paused
    _shutting_down = True
    _paused = True
    _cancel_all_running()
    stop_uvicorn_server()


def _schedule_pump() -> None:
    global _pump_task
    if _shutting_down or _paused:
        return
    task = asyncio.create_task(_pump_queue())
    _pump_task = task


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _shutting_down
    _shutting_down = False
    try:
        yield
    finally:
        request_app_shutdown()
        task = _pump_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # Downloads run in separate tasks (and sometimes worker threads).
        # Give cooperative cancellation time to finish before removing files.
        pending = set()
        jobs = set(_job_tasks)
        if jobs:
            _, pending = await asyncio.wait(jobs, timeout=_SHUTDOWN_GRACE_SECONDS)
            for job in pending:
                job.cancel()
            await asyncio.gather(*jobs, return_exceptions=True)
        # Cancelling to_thread does not stop its worker: leave its files alone.
        if not pending:
            try:
                await asyncio.to_thread(cleanup_temp_files)
            except Exception:
                pass


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def _extension_cors(request: Request, call_next):
    """Allow CORS only for the two authenticated browser-extension actions.

    The desktop UI is served from this very HTTP server and therefore does not
    need CORS.  Reflecting arbitrary origins here would let any visited web
    page send privileged requests to the loopback API.
    """
    origin = request.headers.get("origin", "")
    path = request.url.path
    extension_origin = origin.startswith(("chrome-extension://", "moz-extension://"))
    extension_api = path in {
        "/api/extension/ping",
        "/api/cookies/from-extension",
        "/api/extension/job",
    }
    if request.method == "OPTIONS" and extension_origin and extension_api:
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, X-Media-Token",
                "Access-Control-Max-Age": "86400",
            },
        )
    response = await call_next(request)
    if extension_origin and extension_api:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Media-Token"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


class JobIn(BaseModel):
    url: str = ""
    urls: list[str] = []
    kind: str = "video"
    quality: str = "720"
    fmt: str = "MP4"
    start: str = ""
    end: str = ""
    track: str = ""
    audio_lang: str = ""


class PreviewIn(BaseModel):
    url: str


class SettingsIn(BaseModel):
    download_dir: str | None = None
    theme: str | None = None
    accent: str | None = None
    rate_limit: str | None = None
    subtitles: str | None = None
    minimize_to_tray: bool | None = None
    notify_on_done: bool | None = None
    desktop_shortcut: bool | None = None
    autostart: bool | None = None
    update_check_url: str | None = None
    cache_max_days: int | None = None
    use_cookies: bool | None = None
    ui_lang: str | None = None
    check_disk_space: bool | None = None
    max_concurrent_downloads: int | None = None
    use_proxy: bool | None = None
    proxy_list: str | None = None
    onboarding_done: bool | None = None
    folders_by_service: bool | None = None
    discord_rpc: bool | None = None
    discord_client_id: str | None = None
    normalize_audio: bool | None = None


class LyricsIn(BaseModel):
    title: str = ""
    artist: str = ""
    duration: float | None = None


class OnTopIn(BaseModel):
    enable: bool = True


class HistoryPatchIn(BaseModel):
    favorite: bool | None = None
    tags: list[str] | str | None = None


class LibraryOrganizeIn(BaseModel):
    paths: list[str] = []


class OpenIn(BaseModel):
    path: str = ""


class PlaylistIn(BaseModel):
    url: str


class QueueIds(BaseModel):
    ids: list[int] = []


class NotifyIn(BaseModel):
    title: str = "Media App"
    body: str = ""


class CookiesIn(BaseModel):
    browser: str = "chrome"


class ExtensionCookiesIn(BaseModel):
    netscape: str
    source: str = "extension"
    count: int = 0


class ExtensionJobIn(BaseModel):
    url: str = ""
    kind: str = ""
    quality: str = "best"
    fmt: str = ""


def _check_extension_token(request: Request) -> None:
    expected = get_extension_token()
    if not expected:
        return
    got = (request.headers.get("X-Media-Token") or "").strip()
    if got != expected:
        raise HTTPException(
            403,
            "Неверный токен расширения. В Настройках снова нажми «Скачать расширение» и перезагрузи его в браузере.",
        )


class IntegrationIn(BaseModel):
    desktop_shortcut: bool | None = None
    autostart: bool | None = None


class UrlIn(BaseModel):
    url: str


class MusicPreviewIn(BaseModel):
    url: str = ""
    prefer: str = "quick"  # quick | file


class YandexDownloadIn(BaseModel):
    urls: list[str] = []


class VkDownloadIn(BaseModel):
    urls: list[str] = []


def _clip(start: str, end: str):
    s = parse_time_to_seconds(start) if start.strip() else None
    e = parse_time_to_seconds(end) if end.strip() else None
    return s, e


async def _thumb(url: str | None) -> str | None:
    if not url:
        return None
    THUMBS.mkdir(parents=True, exist_ok=True)
    dest = THUMBS / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg")
    if dest.is_file():
        return str(dest)

    def _dl():
        import requests

        from media_core.net_proxy import apply_requests_kwargs

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        }
        low = url.lower()
        vkish = any(x in low for x in ("userapi.com", "vkuseraudio", "vk.com", "vk.ru", "sun", "yandex."))
        if any(x in low for x in ("userapi.com", "vkuseraudio", "vk.com", "vk.ru", "sun")):
            headers["Referer"] = "https://vk.com/"
            try:
                from media_core.config import load_vk_cookies

                cookies = load_vk_cookies()
                if cookies:
                    headers["Cookie"] = cookies
            except Exception:
                pass
        kw = apply_requests_kwargs({"timeout": 15, "headers": headers}, force_direct=vkish)
        r = requests.get(url, **kw)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return str(dest)

    try:
        return await asyncio.to_thread(_dl)
    except Exception:
        return None


_last_prune = 0.0

def _history_item_payload(item: dict) -> dict:
    thumb = item.get("thumb") or ""
    return {
        "id": item.get("id"),
        "url": item.get("url"),
        "title": item.get("title") or item.get("url"),
        "platform": item.get("platform"),
        "platform_name": PLATFORM_NAMES.get(item.get("platform") or "", item.get("platform") or ""),
        "duration": item.get("duration") or "",
        "format": item.get("format") or "",
        "quality": (item.get("quality") or "").replace(" (HD)", ""),
        "dest": item.get("dest") or "",
        "thumb": f"/api/file?p={quote(thumb)}" if thumb and os.path.isfile(thumb) else "",
        "status": item.get("status") or "Готово",
        "favorite": bool(item.get("favorite")),
        "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
    }


def _history_payload() -> list[dict]:
    global _last_prune
    now = time.time()
    if now - _last_prune > 8:
        history_prune_missing()
        _last_prune = now
    return [_history_item_payload(item) for item in history_list()]


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
async def state(files: int = 0, light: int = 0):
    """Состояние приложения.

    light=1 — лёгкий heartbeat (очередь/прогресс), без history/settings.
    Полный ответ — при старте UI и когда нужна история/настройки.
    """
    _sync_busy_and_progress()
    payload: dict = {
        "busy": _busy,
        "paused": _paused,
        "progress": dict(_progress),
        "running_count": len(_running_items()),
        "max_concurrent": _max_concurrent(),
        "last": dict(_last),
        "version": APP_VERSION,
        "port": get_listen_port(),
        "queue": [
            {
                "id": q["id"],
                "url": q["url"],
                "kind": q["kind"],
                "title": q.get("title") or q["url"],
                "status": q["status"],
                "error": q.get("error") or "",
                "progress": dict(q["progress"]) if q.get("status") == "running" and q.get("progress") else None,
            }
            for q in _queue
        ],
        "last_error": (_last.get("error") or ""),
    }
    if light:
        if files:
            payload["files"] = _list_files()
        return payload

    payload.update(
        {
            "download_dir": get_download_dir(),
            "settings": get_all(),
            "history": _history_payload(),
            "files": _list_files() if files else [],
            "pc": {
                "user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
                "host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "",
            },
        }
    )
    return payload


def _list_files() -> list[dict]:
    folder = Path(get_download_dir())
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(folder.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file():
            out.append({"name": p.name, "path": str(p)})
        if len(out) >= 80:
            break
    return out


@app.post("/api/preview")
async def preview(body: PreviewIn):
    from media_core.preview import fetch_preview
    from media_core.utils import clean_media_url, fmt_time as ft

    url = clean_media_url(body.url.strip())
    if not detect_platform(url) or is_unsupported_media_url(url):
        return {"ok": False, "error": "Эта ссылка не поддерживается", "url": url}
    try:
        info = await asyncio.wait_for(fetch_preview(url), timeout=25)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Превью не ответило вовремя — можно скачивать без него", "url": url}
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}
    try:
        thumb = await asyncio.wait_for(_thumb(info.get("thumbnail")), timeout=12)
    except Exception:
        thumb = None
    return {
        "ok": True,
        "url": url,
        "platform": info.get("platform"),
        "platform_name": PLATFORM_NAMES.get(info.get("platform") or "", info.get("platform") or ""),
        "title": info.get("title") or "",
        "uploader": info.get("uploader") or "",
        "duration": ft(info.get("duration")) if info.get("duration") else "",
        "duration_sec": info.get("duration"),
        "thumb": f"/api/file?p={quote(thumb)}" if thumb else "",
        "qualities": info.get("qualities") or [{"value": "best", "label": "Оригинал"}],
        "audio_tracks": info.get("audio_tracks") or [],
    }


@app.get("/api/clipboard")
async def clipboard():
    def _get():
        import subprocess

        from media_core.utils import subprocess_no_window_kwargs

        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
            capture_output=True,
            text=True,
            timeout=8,
            **subprocess_no_window_kwargs(),
        )
        return (r.stdout or "").strip()

    try:
        text = await asyncio.to_thread(_get)
        return {"text": text or ""}
    except Exception:
        return {"text": ""}


def _enqueue_one(body: JobIn) -> dict:
    global _queue_id
    url = clean_media_url(body.url.strip())
    if body.kind == "track":
        if not (body.track or "").strip():
            raise HTTPException(400, "Нет названия трека")
    elif body.kind != "shazam_file" and not detect_platform(url):
        raise HTTPException(400, "Неизвестная платформа")
    if is_instagram_stories_url(url) and not youtube_cookies_active():
        raise HTTPException(400, "Instagram Stories нужны cookies — импортируй в Настройках")
    body = body.model_copy(update={"url": url})
    _queue_id += 1
    item = {
        "id": _queue_id,
        "url": url,
        "kind": body.kind,
        "quality": body.quality,
        "fmt": body.fmt,
        "start": body.start,
        "end": body.end,
        "track": body.track,
        "audio_lang": body.audio_lang,
        "title": body.track or url,
        "status": "queued",
        "body": body,
    }
    _queue.append(item)
    return item


@app.post("/api/job")
async def start_job(body: JobIn):
    ids = []
    urls = [u.strip() for u in (body.urls or []) if u and u.strip()]
    if not urls and body.url.strip():
        # batch: несколько ссылок в одном поле через перевод строки
        parts = [p.strip() for p in body.url.replace("\r", "\n").split("\n") if p.strip()]
        http_parts = [p for p in parts if p.lower().startswith("http")]
        urls = http_parts if len(http_parts) > 1 else [body.url.strip()]
    if body.kind == "track":
        item = _enqueue_one(body)
        ids.append(item["id"])
    else:
        if not urls:
            raise HTTPException(400, "Нет ссылки")
        for u in urls:
            one = body.model_copy(update={"url": u, "urls": []})
            item = _enqueue_one(one)
            ids.append(item["id"])
    _schedule_pump()
    return {"ok": True, "ids": ids, "id": ids[0] if ids else None, "queue_len": len(_queue)}


@app.post("/api/queue/pause")
async def queue_pause():
    global _paused, _soft_pause
    _paused = True
    _soft_pause = True
    _cancel_all_running()
    for q in _running_items():
        q["requeue_on_cancel"] = True
        prog = q.get("progress")
        if isinstance(prog, dict):
            prog["stage"] = "Пауза…"
    _sync_busy_and_progress()
    return {"ok": True, "paused": True}


@app.post("/api/queue/resume")
async def queue_resume():
    global _paused, _soft_pause
    if _shutting_down:
        return {"ok": False, "paused": True, "error": "Приложение завершается"}
    _paused = False
    _soft_pause = False
    _cancel.clear()
    _schedule_pump()
    return {"ok": True, "paused": False}


@app.post("/api/queue/clear")
async def queue_clear():
    global _queue
    _queue = [q for q in _queue if q["status"] == "running"]
    return {"ok": True}


@app.post("/api/queue/{job_id}/retry")
async def queue_retry(job_id: int):
    """Return a failed job to the queue without losing its original options."""
    if _shutting_down:
        raise HTTPException(409, "Приложение завершается")
    item = next((q for q in _queue if q["id"] == job_id), None)
    if not item:
        raise HTTPException(404, "Задача не найдена")
    if item.get("status") != "error":
        raise HTTPException(409, "Повторить можно только задачу с ошибкой")
    item.pop("error", None)
    item.pop("progress", None)
    item.pop("requeue_on_cancel", None)
    item["status"] = "queued"
    _schedule_pump()
    return {"ok": True, "id": job_id}


@app.post("/api/cancel")
async def cancel():
    global _soft_pause
    _soft_pause = False
    _cancel_all_running()
    for q in _running_items():
        q["requeue_on_cancel"] = False
        prog = q.get("progress")
        if isinstance(prog, dict):
            prog["stage"] = "Отмена…"
    _sync_busy_and_progress()
    return {"ok": True}


@app.post("/api/history/clear")
async def clear_history():
    history_clear()
    return {"ok": True}


@app.get("/api/history")
async def api_history(q: str = "", favorite: int = -1, tag: str = ""):
    fav = None
    if favorite == 1:
        fav = True
    elif favorite == 0:
        fav = False
    rows = history_search(q=q, favorite=fav, tag=tag)
    return {"ok": True, "history": [_history_item_payload(i) for i in rows]}


@app.post("/api/history/{item_id}")
async def api_history_patch(item_id: int, body: HistoryPatchIn):
    item = history_update(item_id, favorite=body.favorite, tags=body.tags)
    if not item:
        raise HTTPException(404, "Не найдено")
    return {"ok": True, "item": _history_item_payload(item)}


@app.delete("/api/history/{item_id}")
async def api_history_delete(item_id: int):
    if not history_delete(item_id):
        raise HTTPException(404, "Не найдено")
    return {"ok": True}


@app.post("/api/settings")
async def save_settings(body: SettingsIn):
    from media_core.settings_store import get_bool

    prev_shortcut = get_bool("desktop_shortcut", False)
    prev_autostart = get_bool("autostart", False)
    data = update_settings(
        download_dir=body.download_dir,
        theme=body.theme,
        accent=body.accent,
        rate_limit=body.rate_limit,
        subtitles=body.subtitles,
        minimize_to_tray=body.minimize_to_tray,
        notify_on_done=body.notify_on_done,
        desktop_shortcut=body.desktop_shortcut,
        autostart=body.autostart,
        update_check_url=body.update_check_url,
        cache_max_days=body.cache_max_days,
        use_cookies=body.use_cookies,
        ui_lang=body.ui_lang,
        check_disk_space=body.check_disk_space,
        max_concurrent_downloads=body.max_concurrent_downloads,
        use_proxy=body.use_proxy,
        proxy_list=body.proxy_list,
        onboarding_done=body.onboarding_done,
        folders_by_service=body.folders_by_service,
        discord_rpc=body.discord_rpc,
        discord_client_id=body.discord_client_id,
        normalize_audio=body.normalize_audio,
    )
    try:
        from media_core.discord_rpc import on_settings_changed

        on_settings_changed()
    except Exception:
        pass
    if body.desktop_shortcut != prev_shortcut or body.autostart != prev_autostart:
        try:
            from media_core.windows_integration import apply_integration

            apply_integration(
                desktop_shortcut=body.desktop_shortcut,
                autostart=body.autostart,
            )
        except Exception:
            pass
    return data


@app.get("/api/log")
async def get_log(lines: int = 200):
    path = Path(LOG_FILE)
    if not path.is_file():
        return {"ok": True, "text": "", "path": str(path)}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise HTTPException(500, str(e))
    parts = raw.splitlines()
    tail = "\n".join(parts[-max(20, min(2000, lines)):])
    return {"ok": True, "text": tail, "path": str(path)}


@app.post("/api/cleanup")
async def api_cleanup():
    result = await asyncio.to_thread(cleanup_temp_files)
    return {"ok": True, **result}


@app.get("/api/app/version")
async def app_version():
    return {"version": APP_VERSION}


@app.post("/api/app/check_update")
async def check_update(quiet: int = 0):
    from media_core.settings_store import get_update_check_url
    from media_core.updater import check_github_update, is_newer
    import json
    import urllib.request

    try:
        set_last_update_check()
        gh = await asyncio.to_thread(check_github_update)
        if gh.get("update") or not get_update_check_url():
            if gh.get("update"):
                return {
                    "ok": True,
                    "current": gh.get("current") or APP_VERSION,
                    "remote": gh.get("remote") or "",
                    "url": gh.get("url") or "",
                    "installer_url": gh.get("installer_url") or "",
                    "html_url": gh.get("html_url") or "",
                    "changelog": gh.get("changelog") or "",
                    "quiet": bool(quiet),
                    "message": gh.get("message") or "",
                    "update": {
                        "version": gh.get("remote") or "",
                        "url": gh.get("url") or gh.get("installer_url") or "",
                        "changelog": gh.get("changelog") or "",
                        "html_url": gh.get("html_url") or "",
                    },
                }
            return {
                "ok": bool(gh.get("ok", True)),
                "current": gh.get("current") or APP_VERSION,
                "remote": gh.get("remote") or "",
                "url": gh.get("url") or "",
                "changelog": gh.get("changelog") or "",
                "quiet": bool(quiet),
                "message": gh.get("message") or "Установлена актуальная версия",
                "update": None,
            }

        url = get_update_check_url()

        def _fetch():
            with urllib.request.urlopen(url, timeout=12) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))

        try:
            data = await asyncio.to_thread(_fetch)
        except Exception as e:
            return {
                "ok": False,
                "current": APP_VERSION,
                "remote": "",
                "update": None,
                "url": "",
                "error": str(e),
                "message": str(e),
            }
        remote = str(data.get("version") or "").strip()
        download = str(data.get("url") or data.get("download_url") or "").strip()
        changelog = str(data.get("changelog") or data.get("notes") or "").strip()
        newer = bool(remote and is_newer(remote, APP_VERSION))
        return {
            "ok": True,
            "current": APP_VERSION,
            "remote": remote,
            "update": {"version": remote, "url": download, "changelog": changelog} if newer else None,
            "url": download,
            "changelog": changelog,
            "quiet": bool(quiet),
            "message": (f"Доступна {remote}" if newer else "У тебя актуальная версия"),
        }
    except Exception as e:
        return {
            "ok": False,
            "current": APP_VERSION,
            "update": None,
            "message": f"Ошибка проверки: {e}",
            "error": str(e),
        }


class ApplyUpdateIn(BaseModel):
    url: str | None = None


@app.post("/api/app/apply_update")
async def apply_update(body: ApplyUpdateIn | None = None):
    from media_core.updater import start_update_job

    try:
        # Never accept a download URL from the browser.  It can be forged by a
        # local process or, if CORS is misconfigured in the future, by a web
        # page.  Resolve the expected release asset through GitHub instead.
        return await asyncio.to_thread(start_update_job)
    except Exception as e:
        return {"ok": False, "status": "error", "message": f"Ошибка: {e}", "error": str(e)}


@app.get("/api/app/update_status")
async def update_status():
    from media_core.updater import get_update_job

    try:
        return {"ok": True, **get_update_job()}
    except Exception as e:
        return {"ok": False, "status": "error", "message": str(e)}


@app.get("/api/backup/export")
async def backup_export():
    from starlette.background import BackgroundTask

    from media_core.backup import export_backup_zip

    path = await asyncio.to_thread(export_backup_zip)
    tmp_dir = path.parent

    def _cleanup():
        import shutil

        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    return FileResponse(
        path,
        filename=path.name,
        media_type="application/zip",
        background=BackgroundTask(_cleanup),
    )


@app.post("/api/backup/import")
async def backup_import(file: UploadFile = File(...)):
    from media_core.backup import import_backup_zip

    raw = await file.read()
    result = await asyncio.to_thread(import_backup_zip, raw)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Ошибка импорта")
    return result


@app.get("/api/library")
async def api_library(by: str = "flat", artist: str = "", kind: str = "all", sync: int = 1):
    from media_core.library import get_library, scan_library

    # мягкий автоскан при каждом запросе (только новые/изменённые файлы)
    if sync:
        await asyncio.to_thread(scan_library, False)
    data = await asyncio.to_thread(get_library, by, artist, kind)

    def map_cover(it: dict) -> dict:
        cover = it.get("cover") or it.get("cover_path") or ""
        out = dict(it)
        out["cover"] = f"/api/file?p={quote(cover)}" if cover and os.path.isfile(cover) else ""
        return out

    if data.get("items"):
        data["items"] = [map_cover(i) for i in data["items"]]
    if data.get("groups"):
        for g in data["groups"]:
            g["items"] = [map_cover(i) for i in g.get("items") or []]
    return data


@app.post("/api/library/rescan")
async def api_library_rescan():
    from media_core.library import scan_library

    return await asyncio.to_thread(scan_library, True)


class LibraryRemoveIn(BaseModel):
    path: str
    delete_file: bool = True


@app.post("/api/library/remove")
async def api_library_remove(body: LibraryRemoveIn):
    from media_core.library import remove_library_item

    active = 0
    if body.delete_file:
        _abort_file_streams(body.path)
        active = await _wait_for_file_streams(body.path)
        if active:
            return {
                "ok": False,
                "removed_from_index": False,
                "file_deleted": False,
                "error": f"Не удалось остановить выдачу файла приложением. Активных запросов: {active}.",
            }
    result = await asyncio.to_thread(remove_library_item, body.path, delete_file=body.delete_file)
    return result


@app.get("/api/library/playlists")
async def api_library_playlists():
    from media_core.database import library_playlists_list

    items = await asyncio.to_thread(library_playlists_list)
    return {"ok": True, "items": items}


class LibraryPlaylistCreateIn(BaseModel):
    name: str = "Новый плейлист"


class LibraryPlaylistRenameIn(BaseModel):
    name: str


class LibraryPlaylistTracksIn(BaseModel):
    paths: list[str] = []


@app.post("/api/library/playlists")
async def api_library_playlist_create(body: LibraryPlaylistCreateIn):
    from media_core.database import library_playlist_create

    pl = await asyncio.to_thread(library_playlist_create, body.name)
    return {"ok": True, "playlist": pl}


@app.patch("/api/library/playlists/{playlist_id}")
async def api_library_playlist_rename(playlist_id: int, body: LibraryPlaylistRenameIn):
    from media_core.database import library_playlist_rename

    pl = await asyncio.to_thread(library_playlist_rename, playlist_id, body.name)
    if not pl:
        return {"ok": False, "error": "Не удалось переименовать"}
    return {"ok": True, "playlist": pl}


@app.delete("/api/library/playlists/{playlist_id}")
async def api_library_playlist_delete(playlist_id: int):
    from media_core.database import library_playlist_delete

    ok = await asyncio.to_thread(library_playlist_delete, playlist_id)
    return {"ok": ok}


@app.get("/api/library/playlists/{playlist_id}")
async def api_library_playlist_detail(playlist_id: int):
    from media_core.database import library_playlist_tracks, library_playlists_list
    from media_core.utils import fmt_time

    playlists = await asyncio.to_thread(library_playlists_list)
    pl = next((p for p in playlists if int(p["id"]) == int(playlist_id)), None)
    if not pl:
        return {"ok": False, "error": "Плейлист не найден", "tracks": []}
    tracks = await asyncio.to_thread(library_playlist_tracks, playlist_id)
    out = []
    for t in tracks:
        cover = t.get("cover_path") or ""
        dur = t.get("duration")
        try:
            dur_sec = float(dur) if dur not in (None, "") else 0.0
            duration_label = fmt_time(dur_sec) if dur_sec else ""
        except (TypeError, ValueError):
            duration_label = str(dur) if isinstance(dur, str) else ""
        out.append(
            {
                **t,
                "cover": f"/api/file?p={quote(cover)}" if cover and os.path.isfile(cover) else "",
                "duration": duration_label,
            }
        )
    return {"ok": True, "playlist": pl, "tracks": out}


@app.post("/api/library/playlists/{playlist_id}/tracks")
async def api_library_playlist_add(playlist_id: int, body: LibraryPlaylistTracksIn):
    from media_core.database import library_playlist_add_tracks

    return await asyncio.to_thread(library_playlist_add_tracks, playlist_id, body.paths or [])


@app.delete("/api/library/playlists/{playlist_id}/tracks")
async def api_library_playlist_remove(playlist_id: int, path: str):
    from media_core.database import library_playlist_remove_track

    ok = await asyncio.to_thread(library_playlist_remove_track, playlist_id, path)
    return {"ok": ok}


@app.get("/api/library/duplicates")
async def api_library_duplicates():
    from media_core.library import find_duplicates

    data = await asyncio.to_thread(find_duplicates)

    def map_cover(it: dict) -> dict:
        cover = it.get("cover_path") or ""
        out = dict(it)
        out["cover"] = f"/api/file?p={quote(cover)}" if cover and os.path.isfile(cover) else ""
        return out

    for g in data.get("groups") or []:
        g["items"] = [map_cover(i) for i in g.get("items") or []]
    return data


@app.post("/api/library/organize")
async def api_library_organize(body: LibraryOrganizeIn):
    from media_core.library import organize_by_artist

    return await asyncio.to_thread(organize_by_artist, body.paths or None)


@app.post("/api/notify")
async def api_notify(body: NotifyIn):
    if not get_bool("notify_on_done", True):
        return {"ok": False, "skipped": True}
    from media_core.notify_win import show_toast
    ok = await asyncio.to_thread(show_toast, body.title or "Media App", body.body or "")
    return {"ok": ok}


@app.post("/api/notify/ack")
async def api_notify_ack():
    _last["notify_pending"] = False
    return {"ok": True}


@app.post("/api/cookies/import")
async def cookies_import(body: CookiesIn):
    from media_core.cookies_import import import_browser_cookies
    return await asyncio.to_thread(import_browser_cookies, body.browser)


@app.post("/api/cookies/upload")
async def cookies_upload(file: UploadFile = File(...)):
    from media_core.cookies_import import save_uploaded_cookies
    raw = await file.read()
    return await asyncio.to_thread(save_uploaded_cookies, raw, file.filename or "cookies.txt")


@app.get("/api/cookies/status")
async def cookies_status():
    from media_core.cookies_import import cookies_status as st
    return st()


@app.post("/api/cookies/open")
async def cookies_open():
    from media_core.utils import open_path_in_shell

    folder = Path(COOKIES_FILE).resolve().parent
    open_path_in_shell(folder)
    return {"ok": True, "path": str(folder)}


@app.get("/api/extension/ping")
async def extension_ping(request: Request):
    return {"ok": True, "app": "MediaApp", "version": APP_VERSION, "port": get_listen_port()}


@app.post("/api/window/show")
async def window_show():
    ok = False
    if _show_window_cb is not None:
        try:
            _show_window_cb()
            ok = True
        except Exception:
            ok = False
    return {"ok": ok, "app": "MediaApp"}


@app.post("/api/window/quit")
async def window_quit():
    """Запрос полного выхода (трей → GUI)."""
    ok = False
    if _quit_cb is not None:
        try:
            _quit_cb()
            ok = True
        except Exception:
            ok = False
    else:
        request_app_shutdown()
        ok = True
    return {"ok": ok}


class FullscreenIn(BaseModel):
    enable: bool | None = None  # None = toggle


@app.post("/api/window/fullscreen")
async def window_fullscreen(body: FullscreenIn | None = None):
    enable = None if body is None else body.enable
    ok = False
    if _fullscreen_cb is not None:
        try:
            _fullscreen_cb(enable)
            ok = True
        except Exception:
            ok = False
    return {"ok": ok}


@app.post("/api/window/on_top")
async def window_on_top(body: OnTopIn):
    ok = False
    if _on_top_cb is not None:
        try:
            _on_top_cb(bool(body.enable))
            ok = True
        except Exception:
            ok = False
    return {"ok": ok, "enable": bool(body.enable)}


@app.get("/api/player/state")
async def api_player_state():
    from media_core.player_bridge import get_state, is_mini_open

    s = get_state()
    s["mini_open"] = is_mini_open()
    return {"ok": True, **s}


class PlayerPublishIn(BaseModel):
    title: str | None = None
    artist: str | None = None
    playing: bool | None = None
    current: float | None = None
    duration: float | None = None
    volume: float | None = None
    has_track: bool | None = None
    thumb: str | None = None
    kind: str | None = None


@app.post("/api/player/publish")
async def api_player_publish(body: PlayerPublishIn):
    from media_core.player_bridge import publish_state

    state = publish_state(**body.model_dump())
    try:
        from media_core.discord_rpc import sync_from_player

        sync_from_player(state)
    except Exception:
        pass
    return {"ok": True, **state}


class PlayerControlIn(BaseModel):
    action: str  # play | pause | toggle | next | prev | volume | seek | close_mini
    value: float | None = None


@app.post("/api/player/control")
async def api_player_control(body: PlayerControlIn):
    from media_core.player_bridge import push_command

    return push_command(body.action, value=body.value)


@app.get("/api/player/commands")
async def api_player_commands():
    from media_core.player_bridge import pop_commands

    return {"ok": True, "commands": pop_commands()}


class MiniPlayerIn(BaseModel):
    enable: bool = True


@app.post("/api/window/mini_player")
async def api_mini_player(body: MiniPlayerIn):
    """Только флаг желаемого состояния. Show/hide — через pywebview.api (GUI-поток)."""
    from media_core.player_bridge import set_mini_want

    set_mini_want(bool(body.enable))
    # Не вызываем _mini_player_cb здесь: show/hide HWND из uvicorn зависает приложение на Windows.
    return {"ok": True, "enable": bool(body.enable), "gui": True}


@app.get("/mini")
async def mini_page():
    """Отдельная страница мини-плеера (второе окно)."""
    from fastapi.responses import HTMLResponse

    html = """<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Media App</title>
<style>
  html,body{margin:0;height:100%;overflow:hidden;font-family:Segoe UI,system-ui,sans-serif;
    background:#0f172a;color:#f8fafc;user-select:none}
  .bar{display:flex;align-items:center;gap:10px;height:100%;padding:8px 12px;box-sizing:border-box;
    -webkit-app-region:drag;app-region:drag}
  .nodrag{-webkit-app-region:no-drag;app-region:no-drag;display:flex;align-items:center;gap:6px}
  .cover{width:48px;height:48px;border-radius:8px;object-fit:cover;flex-shrink:0;background:#1e293b;
    border:1px solid rgba(255,255,255,.12);-webkit-app-region:drag;app-region:drag}
  .cover.ph{display:flex;align-items:center;justify-content:center;color:#64748b;font-size:18px}
  .btn{-webkit-app-region:no-drag;app-region:no-drag;border:0;background:transparent;color:#e2e8f0;cursor:pointer;
    width:34px;height:34px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:14px}
  .btn:hover{background:rgba(255,255,255,.08)}
  .play{background:#14b8a6;color:#fff;border-radius:999px;width:40px;height:40px;font-size:15px}
  .play:hover{filter:brightness(1.08)}
  .meta{min-width:0;flex:1;-webkit-app-region:drag;app-region:drag}
  .title{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.25}
  .artist{font-size:11px;opacity:.65;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.25;margin-top:2px}
  .vol{-webkit-app-region:no-drag;app-region:no-drag;width:100px;height:20px;accent-color:#14b8a6;cursor:pointer}
  .x{opacity:.7}
</style></head><body>
<div class="bar">
  <img class="cover" id="cover" alt="" hidden/>
  <div class="cover ph" id="coverph" aria-hidden="true">♪</div>
  <div class="nodrag">
    <button class="btn" id="prev" title="Предыдущий">&#9198;</button>
    <button class="btn play" id="toggle" title="Play/Pause">&#9654;</button>
    <button class="btn" id="next" title="Следующий">&#9197;</button>
  </div>
  <div class="meta"><div class="title" id="title">&mdash;</div><div class="artist" id="artist"></div></div>
  <div class="nodrag" id="volwrap">
    <input class="vol" id="vol" type="range" min="0" max="1" step="0.05" value="0.85" title="Громкость"/>
    <button class="btn x" id="close" title="Закрыть мини-плеер">&#10005;</button>
  </div>
</div>
<script>
async function j(url, opt){const r=await fetch(url,opt);return r.json()}
function ctrl(action,value){
  return j('/api/player/control',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action,value})})
}
const title=document.getElementById('title'), artist=document.getElementById('artist');
const toggle=document.getElementById('toggle'), vol=document.getElementById('vol');
const volwrap=document.getElementById('volwrap');
const cover=document.getElementById('cover'), coverph=document.getElementById('coverph');
function blockDrag(e){e.stopPropagation()}
;['pointerdown','mousedown','touchstart'].forEach(ev=>{
  volwrap.addEventListener(ev, blockDrag, true);
  vol.addEventListener(ev, blockDrag, true);
});
document.getElementById('prev').onclick=()=>ctrl('prev');
document.getElementById('next').onclick=()=>ctrl('next');
toggle.onclick=()=>ctrl('toggle');
vol.oninput=()=>ctrl('volume', Number(vol.value));
document.getElementById('close').onclick=async()=>{
  await ctrl('close_mini');
  try{
    if(window.pywebview&&window.pywebview.api&&window.pywebview.api.hide_mini){
      await window.pywebview.api.hide_mini();
      return;
    }
  }catch(e){}
  await j('/api/window/mini_player',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({enable:false})});
};
function setCover(url){
  if(url){
    cover.src=url;
    cover.hidden=false;
    coverph.style.display='none';
  }else{
    cover.removeAttribute('src');
    cover.hidden=true;
    coverph.style.display='flex';
  }
}
async function tick(){
  try{
    const s=await j('/api/player/state');
    title.textContent=s.title||'—';
    artist.textContent=s.artist||'';
    toggle.textContent=s.playing?'❚❚':'▶';
    if(typeof s.volume==='number' && Math.abs(s.volume-Number(vol.value))>0.04) vol.value=s.volume;
    setCover(s.thumb||'');
  }catch(e){}
}
setInterval(tick,500); tick();
</script></body></html>"""
    return HTMLResponse(html)


@app.post("/api/lyrics")
async def api_lyrics(body: LyricsIn):
    from media_core.lyrics import fetch_lyrics

    return await asyncio.to_thread(fetch_lyrics, body.title, body.artist, body.duration)


@app.post("/api/cookies/from-extension")
async def cookies_from_extension(body: ExtensionCookiesIn, request: Request):
    _check_extension_token(request)
    from media_core.cookies_import import save_uploaded_cookies
    raw = (body.netscape or "").encode("utf-8")
    result = await asyncio.to_thread(save_uploaded_cookies, raw, "extension_cookies.txt")
    if result.get("ok"):
        _last["message"] = f"Cookies из расширения: {result.get('count')} шт."
    return result


@app.post("/api/extension/job")
async def extension_job(body: ExtensionJobIn, request: Request):
    """Очередь загрузки из браузерного расширения («Отправить в Media App»)."""
    _check_extension_token(request)
    from media_core.utils import is_track_download_url

    url = clean_media_url((body.url or "").strip())
    if not url:
        raise HTTPException(400, "Нет ссылки")
    if not detect_platform(url) or is_unsupported_media_url(url):
        raise HTTPException(400, "Эта ссылка не поддерживается")
    kind = (body.kind or "").strip().lower()
    if kind not in ("video", "audio", "track", "shazam"):
        kind = "audio" if is_track_download_url(url) else "video"
    fmt = (body.fmt or "").strip().upper()
    if not fmt:
        fmt = "MP3" if kind == "audio" else "MP4"
    if fmt == "MP3":
        kind = "audio"
    # VK/Яндекс/SoundCloud — всегда аудио, даже если в расширении стоит «Видео»
    if is_track_download_url(url):
        kind = "audio"
        if fmt not in ("MP3", "M4A", "OPUS", "FLAC"):
            fmt = "MP3"
    quality = (body.quality or "best").strip() or "best"
    item = _enqueue_one(
        JobIn(url=url, kind=kind, quality=quality, fmt=fmt, start="", end="", track="")
    )
    _schedule_pump()
    _last["message"] = f"Из браузера в очередь: {item.get('title') or url} ({fmt} · {quality})"
    return {
        "ok": True,
        "id": item["id"],
        "queue_len": len(_queue),
        "kind": kind,
        "quality": quality,
        "fmt": fmt,
        "title": item.get("title") or url,
    }


@app.get("/api/extension/download")
async def extension_download():
    from media_core.extension_pack import build_extension_zip, ensure_extension_token

    ensure_extension_token()
    data = await asyncio.to_thread(build_extension_zip, get_listen_port())
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="MediaApp-Extension.zip"'},
    )


@app.post("/api/extension/save")
async def extension_save():
    """Сохранить zip рядом с программой и открыть папку (надёжнее в pywebview)."""
    from media_core.extension_pack import build_extension_zip, ensure_extension_token

    ensure_extension_token()
    data = await asyncio.to_thread(build_extension_zip, get_listen_port())
    dest = BASE_DIR / "MediaApp-Cookies-Extension.zip"
    dest.write_bytes(data)
    # распаковать рядом для удобства
    unpack = BASE_DIR / "MediaApp-Cookies-Extension"
    if unpack.exists():
        import shutil
        shutil.rmtree(unpack, ignore_errors=True)
    unpack.mkdir(parents=True, exist_ok=True)
    import zipfile
    with zipfile.ZipFile(dest, "r") as zf:
        zf.extractall(unpack)
    from media_core.utils import open_path_in_shell

    open_path_in_shell(unpack)
    return {"ok": True, "path": str(dest), "folder": str(unpack)}


@app.post("/api/integration")
async def integration(body: IntegrationIn):
    from media_core.windows_integration import apply_integration
    result = await asyncio.to_thread(
        apply_integration,
        desktop_shortcut=body.desktop_shortcut,
        autostart=body.autostart,
    )
    update_settings(
        desktop_shortcut=body.desktop_shortcut,
        autostart=body.autostart,
    )
    return {"ok": True, **result}


@app.post("/api/playlist")
async def playlist_info(body: PlaylistIn):
    url = body.url.strip()
    from media_core.download_ytdlp import extract_playlist_entries

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(extract_playlist_entries, url, limit=500),
            timeout=90,
        )
    except Exception as e:
        raise HTTPException(400, f"Не удалось прочитать плейлист: {e}")
    return {
        "ok": bool(data.get("ok")),
        "title": data.get("title") or "Плейлист",
        "entries": data.get("entries") or [],
        "count": data.get("count") or 0,
        "error": data.get("error") or "",
    }


@app.post("/api/ytdlp/update")
async def ytdlp_update():
    """Обновляет только пакет yt-dlp. Настройки Media App (config/app_settings.json) не трогает."""
    import subprocess
    import sys

    def _upd():
        if getattr(sys, "frozen", False):
            return (
                1,
                "В установленной .exe yt-dlp обновляется вместе с Media App "
                "(Настройки → Обновления). Настройки приложения при этом сохраняются.",
            )
        from media_core.utils import subprocess_no_window_kwargs

        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            capture_output=True,
            text=True,
            timeout=180,
            **subprocess_no_window_kwargs(),
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out[-2000:]

    code, out = await asyncio.to_thread(_upd)
    try:
        import yt_dlp
        ver = getattr(yt_dlp, "version", None)
        version = getattr(ver, "__version__", None) or str(ver)
    except Exception:
        version = "?"
    return {"ok": code == 0, "version": version, "log": out}


@app.post("/api/shazam/file")
async def shazam_file(file: UploadFile = File(...)):
    raw = await file.read()
    suffix = Path(file.filename or "audio.mp3").suffix or ".mp3"
    tmp = BASE_DIR / f"tmp_shazam_{os.getpid()}{suffix}"
    tmp.write_bytes(raw)
    from media_core.recognize import recognize_music_from_file, _save_preview_clip

    preview_url = ""
    try:
        _progress.update(stage="Распознаю файл…", indeterminate=True, updated_at=time.time())
        result = await recognize_music_from_file(str(tmp))
        preview_path = _save_preview_clip(str(tmp))
        if preview_path:
            preview_url = f"/api/file?p={quote(preview_path)}"
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    if not result:
        return {"ok": False, "error": "Трек не найден"}
    track_name = result.get("track") if isinstance(result, dict) else str(result)
    cover_url = result.get("cover_url") if isinstance(result, dict) else None
    cover_local = await _thumb(cover_url) if cover_url else None
    links = build_source_links(track_name)
    payload = {
        "track": track_name,
        "title": (result.get("title") if isinstance(result, dict) else None) or track_name,
        "artist": (result.get("artist") if isinstance(result, dict) else "") or "",
        "links": [{"name": n, "url": h} for n, h in links],
        "preview": preview_url,
        "cover": f"/api/file?p={quote(cover_local)}" if cover_local else (cover_url or ""),
        "cover_url": cover_url,
    }
    _last["shazam"] = payload
    return {"ok": True, **payload}


@app.get("/api/yandex/status")
async def yandex_status():
    from media_core.yandex_music_api import yandex_account_status

    return await yandex_account_status()


@app.get("/api/yandex/playlists")
async def yandex_playlists():
    from media_core.yandex_music_api import list_yandex_playlists

    return await list_yandex_playlists()


@app.get("/api/yandex/likes")
async def yandex_likes(limit: int = 500):
    from media_core.yandex_music_api import list_yandex_likes_tracks

    return await list_yandex_likes_tracks(limit=max(1, min(2000, limit)))


@app.get("/api/yandex/playlist")
async def yandex_playlist(kind: str = "likes", uid: str = "", limit: int = 1000):
    from media_core.yandex_music_api import list_yandex_playlist_tracks

    return await list_yandex_playlist_tracks(
        kind.strip() or "likes",
        uid=uid.strip() or None,
        limit=max(1, min(2000, limit)),
    )


@app.post("/api/yandex/download")
async def yandex_download(body: YandexDownloadIn):
    urls = [u.strip() for u in (body.urls or []) if u and u.strip()]
    if not urls:
        return {"ok": False, "error": "Не выбраны треки", "ids": []}
    ids = []
    for u in urls[:200]:
        item = _enqueue_one(JobIn(url=u, kind="audio", quality="best", fmt="MP3", start="", end="", track=""))
        ids.append(item["id"])
    _schedule_pump()
    return {"ok": True, "ids": ids, "count": len(ids), "queue_len": len(_queue)}


@app.get("/api/vk/status")
async def vk_status():
    from media_core.vk_music_api import vk_account_status

    return await vk_account_status()


@app.get("/api/vk/playlists")
async def vk_playlists():
    from media_core.vk_music_api import list_vk_playlists

    return await list_vk_playlists()


@app.get("/api/vk/playlist")
async def vk_playlist(kind: str = "my", uid: str = "", limit: int = 1000, access_hash: str = ""):
    from media_core.vk_music_api import list_vk_playlist_tracks

    return await list_vk_playlist_tracks(
        kind.strip() or "my",
        uid=uid.strip() or None,
        limit=max(1, min(2000, limit)),
        access_hash=access_hash.strip(),
    )


@app.post("/api/vk/download")
async def vk_download(body: VkDownloadIn):
    urls = [u.strip() for u in (body.urls or []) if u and u.strip()]
    if not urls:
        return {"ok": False, "error": "Не выбраны треки", "ids": []}
    ids = []
    for u in urls[:200]:
        item = _enqueue_one(JobIn(url=u, kind="audio", quality="best", fmt="MP3", start="", end="", track=""))
        ids.append(item["id"])
    _schedule_pump()
    return {"ok": True, "ids": ids, "count": len(ids), "queue_len": len(_queue)}


@app.get("/api/music/live")
async def music_live(url: str):
    """Прокси-стрим с CDN без ожидания полного файла (быстрый старт в плеере)."""
    from fastapi.responses import StreamingResponse

    from media_core.music_preview import iter_upstream_audio, resolve_music_stream

    page = (url or "").strip()
    if not page:
        raise HTTPException(400, "url required")
    info = await resolve_music_stream(page)
    if not info or not info.get("stream_url"):
        raise HTTPException(404, "stream unavailable")
    stream_url = str(info["stream_url"])
    if "m3u8" in stream_url.lower() or "mpegurl" in stream_url.lower():
        raise HTTPException(415, "hls — используй file preview")

    async def gen():
        async for chunk in iter_upstream_audio(page):
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "Accept-Ranges": "none",
            "X-Media-Stream-Mode": "live",
        },
    )


@app.get("/api/music/stream")
async def music_stream(url: str):
    """Превью файлом (WebView2 стабильнее на FileResponse)."""
    from media_core.music_preview import materialize_preview

    page = (url or "").strip()
    if not page:
        raise HTTPException(400, "url required")
    try:
        meta = await asyncio.wait_for(materialize_preview(page), timeout=90)
    except asyncio.TimeoutError:
        raise HTTPException(504, "timeout") from None
    if not meta or not meta.get("path"):
        raise HTTPException(404, "preview unavailable")
    path = Path(str(meta["path"]))
    if not path.is_file():
        raise HTTPException(404, "preview file missing")
    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename=path.name,
        headers={"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"},
    )


@app.post("/api/music/preview")
async def music_preview(body: MusicPreviewIn):
    """Быстрый стрим в плеер; prefer=file — дождаться полного локального mp3."""
    from media_core.music_preview import materialize_preview, prepare_quick_preview

    page = (body.url or "").strip()
    if not page:
        return {"ok": False, "error": "url required"}
    prefer = (body.prefer or "quick").strip().lower()
    try:
        if prefer == "file":
            meta = await asyncio.wait_for(materialize_preview(page), timeout=90)
        else:
            meta = await asyncio.wait_for(prepare_quick_preview(page), timeout=45)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "timeout"}
    if not meta or not meta.get("stream"):
        return {"ok": False, "error": "Не удалось получить трек для прослушивания"}
    return {
        "ok": True,
        "stream": meta["stream"],
        "title": meta.get("title") or "",
        "artist": meta.get("artist") or "",
        "cover": meta.get("cover") or "",
        "label": meta.get("label") or "",
        "mode": meta.get("mode") or "live",
    }


@app.post("/api/open")
async def open_path(body: OpenIn):
    from media_core.utils import open_path_in_shell

    path = body.path.strip() or get_download_dir()
    open_path_in_shell(Path(path))
    return {"ok": True}


@app.post("/api/open_url")
async def open_url(body: UrlIn):
    import sys

    url = body.url.strip()
    if not url:
        return {"ok": False}
    if sys.platform == "win32":
        os.startfile(url)
    else:
        import webbrowser

        webbrowser.open(url)
    return {"ok": True}


@app.get("/api/file")
async def file_get(p: str):
    path = Path(p)
    allowed = (
        THUMBS.resolve(),
        Path(get_download_dir()).resolve(),
        (BASE_DIR / "file_cache").resolve(),
    )
    try:
        resolved = path.resolve()
    except OSError:
        raise HTTPException(404)
    if not resolved.is_file():
        raise HTTPException(404)
    ok = False
    for a in allowed:
        try:
            resolved.relative_to(a)
            ok = True
            break
        except ValueError:
            continue
    if not ok:
        raise HTTPException(404)
    key = _stream_key(resolved)
    _active_file_streams[key] = _active_file_streams.get(key, 0) + 1
    return _TrackedFileResponse(resolved)


@app.post("/api/anime")
async def anime(file: UploadFile = File(...)):
    raw = await file.read()
    name = file.filename or "photo.jpg"
    suffix = Path(name).suffix.lower() or ".jpg"
    tmp = BASE_DIR / f"tmp_anime_{os.getpid()}{suffix}"
    tmp.write_bytes(raw)
    image_path = str(tmp)
    frame_tmp = None
    from media_core.anime_recognize import candidates_from_api, search_anime_image

    try:
        if suffix in (".mp4", ".webm", ".mkv", ".mov", ".avi"):
            import subprocess
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            frame_tmp = BASE_DIR / f"tmp_anime_frame_{os.getpid()}.jpg"
            from media_core.utils import subprocess_no_window_kwargs

            subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-ss", "00:00:01", "-i", str(tmp), "-frames:v", "1", str(frame_tmp)],
                check=True,
                capture_output=True,
                timeout=60,
                **subprocess_no_window_kwargs(),
            )
            image_path = str(frame_tmp)
        ok, text, meta, raw_api = await search_anime_image(image_path)
    except Exception as e:
        return {"ok": False, "text": str(e), "meta": {}, "candidates": []}
    finally:
        for p in (tmp, frame_tmp):
            if p is None:
                continue
            try:
                p.unlink()
            except OSError:
                pass

    candidates = []
    for c in candidates_from_api(raw_api if isinstance(raw_api, dict) else {}):
        thumb = await _thumb(c.get("preview_url"))
        title = c.get("title") or ""
        q = quote(title)
        candidates.append({
            **c,
            "thumb": f"/api/file?p={quote(thumb)}" if thumb else "",
            "moment": fmt_time(c.get("from_sec")),
            "shikimori_url": f"https://shikimori.one/animes?search={q}",
            "mal_url": f"https://myanimelist.net/search/all?q={q}",
        })
    return {"ok": ok, "text": text, "meta": meta, "candidates": candidates}


async def _pump_queue():
    """Запустить до max_concurrent задач из очереди."""
    if _shutting_down or _paused:
        return
    async with _queue_lock:
        running_n = len(_running_items())
        slots = _max_concurrent() - running_n
        if slots <= 0:
            return
        started = 0
        while started < slots:
            nxt = next((q for q in _queue if q["status"] == "queued"), None)
            if not nxt:
                break
            if get_bool("check_disk_space", True):
                import shutil

                try:
                    usage = shutil.disk_usage(get_download_dir())
                    if usage.free < 500 * 1024 * 1024:
                        _last["error"] = "Мало места на диске (нужно ~500 МБ)"
                        nxt["status"] = "error"
                        nxt["error"] = _last["error"]
                        continue
                except OSError:
                    pass
            cancel_ev = threading.Event()
            progress = _blank_progress()
            progress.update(
                stage="Старт…",
                indeterminate=True,
                started_at=time.time(),
            )
            nxt["cancel_event"] = cancel_ev
            nxt["requeue_on_cancel"] = False
            nxt["progress"] = progress
            nxt["status"] = "running"
            nxt["error"] = ""
            task = asyncio.create_task(_execute_job(nxt))
            _job_tasks.add(task)
            task.add_done_callback(_job_tasks.discard)
            started += 1
        _sync_busy_and_progress()


async def _execute_job(nxt: dict) -> None:
    """Одна загрузка из очереди (параллельно с другими)."""
    progress = nxt.get("progress") or _blank_progress()
    cancel_ev = nxt.get("cancel_event") or threading.Event()
    result = {"error": "", "message": ""}
    _last.update(error="", message="")
    try:
        with download_scope():
            await _run(nxt["body"], progress_state=progress, cancel_event=cancel_ev, result_state=result)
        _last.update(result)
        if nxt.get("requeue_on_cancel") and result.get("message") == "Отменено":
            nxt["status"] = "queued"
            nxt.pop("cancel_event", None)
            nxt.pop("progress", None)
            _last["message"] = "Пауза"
            _last["error"] = ""
        elif result.get("error"):
            nxt["status"] = "error"
            nxt["error"] = result["error"]
        else:
            nxt["status"] = "done"
            if result.get("message") in ("Готово", "Трек скачан") and get_bool("notify_on_done", True):
                _last["notify_pending"] = True
                try:
                    from media_core.notify_win import show_toast
                    await asyncio.to_thread(
                        show_toast, "Media App", result.get("message") or "Готово",
                    )
                except Exception:
                    pass
    except asyncio.CancelledError:
        cancel_ev.set()
        nxt["status"] = "done"
        _last["message"] = "Отменено"
        raise
    except Exception as e:
        if nxt.get("requeue_on_cancel") and cancel_ev.is_set():
            nxt["status"] = "queued"
            nxt.pop("cancel_event", None)
            nxt.pop("progress", None)
            _last["message"] = "Пауза"
        else:
            nxt["status"] = "error"
            nxt["error"] = str(e)
            _last["error"] = str(e)
    finally:
        nxt.pop("requeue_on_cancel", None)
        if nxt.get("status") != "queued":
            nxt.pop("cancel_event", None)
            nxt.pop("progress", None)
        _sync_busy_and_progress()
        while len(_queue) > 40:
            for i, q in enumerate(_queue):
                if q["status"] in ("done", "error"):
                    _queue.pop(i)
                    break
            else:
                break
        if not _paused and not _shutting_down:
            _schedule_pump()


async def _run(
    body: JobIn,
    *,
    progress_state: dict | None = None,
    cancel_event: threading.Event | None = None,
    result_state: dict | None = None,
):
    progress = progress_state if progress_state is not None else _progress
    cancel = cancel_event if cancel_event is not None else _cancel
    result = result_state if result_state is not None else _last
    try:
        url = clean_media_url(body.url.strip())
        start, end = _clip(body.start, body.end)
        audio = body.kind in ("audio", "track") or body.fmt.upper() == "MP3"

        if body.kind == "track":
            from media_core.download_ytdlp import download_ytdlp
            from media_core.media_tags import split_artist_title, tag_mp3

            track = body.track.strip()
            progress["stage"] = "Ищу полный трек…"
            progress["updated_at"] = time.time()
            query = f"ytsearch1:{track}"
            path = await download_ytdlp(
                query, audio_only=True, progress_state=progress, cancel_event=cancel,
            )
            if path is CANCELLED:
                result["message"] = "Отменено"
                return
            if not path or not os.path.isfile(path):
                err = get_last_download_error()
                result["error"] = str(err) if err else "Не удалось скачать трек"
                return
            dest = save_to_downloads(path, query, True, track)
            try:
                if os.path.abspath(path) != os.path.abspath(dest):
                    os.remove(path)
            except OSError:
                pass
            artist, title = split_artist_title(track)
            if get_bool("normalize_audio", False):
                progress.update(stage="Нормализую громкость…", indeterminate=True, updated_at=time.time())
                from media_core.audio_postprocess import normalize_mp3
                if not await asyncio.to_thread(normalize_mp3, dest, cancel):
                    result["message"] = "Отменено"
                    return
            thumb = None
            try:
                from media_core.download_ytdlp import probe_video_info
                info = await probe_video_info(query)
                thumb = await _thumb((info or {}).get("thumbnail"))
                tag_mp3(dest, title=title, artist=artist, cover_url=(info or {}).get("thumbnail"))
            except Exception:
                tag_mp3(dest, title=title, artist=artist)
            history_add(query, track, "youtube", format="MP3", quality="audio", dest=dest, thumb=thumb)
            result["message"] = "Трек скачан"
            return

        if body.kind == "shazam":
            from media_core.recognize import recognize_music_from_url

            progress.update(
                stage="Готовлю отрезок для распознавания…",
                indeterminate=True,
                updated_at=time.time(),
            )
            recognized = await recognize_music_from_url(
                url, cancel_event=cancel, progress_state=progress, start=start, end=end,
            )
            if recognized is CANCELLED:
                result["message"] = "Отменено"
            elif not recognized:
                result["error"] = "Трек не найден"
            else:
                if isinstance(recognized, str):
                    payload = {"track": recognized, "cover_url": None, "preview": ""}
                else:
                    payload = dict(recognized)
                    track_name = payload.get("track") or ""
                    preview_path = payload.pop("preview_path", None)
                    preview = ""
                    if preview_path and os.path.isfile(preview_path):
                        preview = f"/api/file?p={quote(preview_path)}"
                    cover = payload.get("cover_url")
                    cover_local = await _thumb(cover) if cover else None
                    payload.update({
                        "track": track_name,
                        "preview": preview,
                        "cover": f"/api/file?p={quote(cover_local)}" if cover_local else (cover or ""),
                    })
                    recognized = track_name
                links = build_source_links(payload.get("track") or recognized)
                payload["links"] = [{"name": n, "url": h} for n, h in links]
                result["shazam"] = payload
            return

        progress.update(
            stage=f"Начинаю скачивание… ({body.quality}{'p' if body.quality.isdigit() else ''} · {body.fmt})",
            indeterminate=True,
            updated_at=time.time(),
        )
        fmt = None if audio else format_for_quality(body.quality, getattr(body, "audio_lang", "") or "")
        container = "mp3" if audio else body.fmt.strip().lower()
        path = await process_url(
            url, audio_only=audio, format_override=fmt,
            progress_state=progress, cancel_event=cancel, start=start, end=end,
            container=container,
        )
        if path is CANCELLED:
            result["message"] = "Отменено"
            return
        if not path or not os.path.isfile(path):
            err = get_last_download_error()
            result["error"] = str(err) if err else "Не удалось скачать"
            return
        progress.update(stage="Сохраняю файл…", indeterminate=True, updated_at=time.time())
        from media_core.download_ytdlp import get_last_extract_info
        from media_core.media_tags import split_artist_title, tag_mp3
        from media_core.yandex_music_api import get_last_yandex_track_meta
        from media_core.download_vk_audio import get_last_vk_track_meta

        info = get_last_extract_info() or {}
        ym = get_last_yandex_track_meta() if detect_platform(url) == "yandex_music" else None
        vk = get_last_vk_track_meta() if is_vk_audio_url(url) else None
        meta = ym or vk or {}
        title = meta.get("label") or meta.get("title") or info.get("title")
        dur = meta.get("duration") if meta.get("duration") is not None else info.get("duration")
        thumb_url = meta.get("thumbnail") or info.get("thumbnail")
        dest = save_to_downloads(path, url, audio, title)
        try:
            if os.path.abspath(path) != os.path.abspath(dest):
                os.remove(path)
        except OSError:
            pass
        if audio or dest.lower().endswith(".mp3"):
            artist = meta.get("artist") or info.get("artist") or info.get("uploader")
            album = meta.get("album")
            t = meta.get("title") or title
            if t and " — " in t and not artist:
                artist, t = split_artist_title(t)
            if get_bool("normalize_audio", False):
                progress.update(stage="Нормализую громкость…", indeterminate=True, updated_at=time.time())
                from media_core.audio_postprocess import normalize_mp3
                if not await asyncio.to_thread(normalize_mp3, dest, cancel):
                    result["message"] = "Отменено"
                    return
            tag_mp3(dest, title=t, artist=artist, album=album, cover_url=thumb_url)
        try:
            stem = Path(path).stem
            for name in Path(".").glob(f"{stem}*.srt"):
                srt_dest = Path(dest).parent / name.name
                if not srt_dest.exists():
                    import shutil
                    shutil.copy2(name, srt_dest)
        except Exception:
            pass
        thumb = await _thumb(thumb_url)
        history_add(
            url, title, detect_platform(url),
            duration=fmt_time(dur) if dur else None,
            format="MP3" if audio else body.fmt,
            quality=f"{body.quality}p" if body.quality.isdigit() else body.quality,
            dest=dest,
            thumb=thumb,
        )
        result["message"] = "Готово"
    except Exception as e:
        result["error"] = str(e)
