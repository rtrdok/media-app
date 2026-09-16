"""Скачивание через yt-dlp (YouTube / Instagram / Coub)."""

from __future__ import annotations

import asyncio
import os
import threading
import time

import yt_dlp
from yt_dlp.utils import download_range_func

from media_core.alerts import notify_admins
from media_core.config import COOKIES_FILE, YOUTUBE_CLIENT_FALLBACKS
from media_core.utils import detect_platform, remux_coub_looped, youtube_cookies_active
from media_core.constants import DownloadCancelled
from media_core.database import get_proxies_to_try, mask_proxy, record_proxy_result
from media_core.proxy_runner import is_fatal_proxy_error, run_with_proxies
from media_core.logging_setup import log
from media_core.runtime import application

_last_download_error: Exception | str | None = None
_last_extract_info: dict | None = None


def get_last_download_error() -> Exception | str | None:
    return _last_download_error


def get_last_extract_info() -> dict | None:
    return _last_extract_info


def _set_last_error(err: Exception | str | None) -> None:
    global _last_download_error
    _last_download_error = err


def _set_last_extract_info(info: dict | None) -> None:
    global _last_extract_info
    _last_extract_info = info


def _parse_rate_limit(value: str | int | float | None) -> int | None:
    """yt-dlp ratelimit — байт/сек. Принимает 2M, 500K, 1048576."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    s = str(value).strip().upper().replace(" ", "")
    if not s:
        return None
    mult = 1
    if s.endswith("K"):
        mult = 1024
        s = s[:-1]
    elif s.endswith("M"):
        mult = 1024 * 1024
        s = s[:-1]
    elif s.endswith("G"):
        mult = 1024 * 1024 * 1024
        s = s[:-1]
    try:
        n = float(s) * mult
    except ValueError:
        return None
    return int(n) if n > 0 else None


def ytdlp_safe_opts(**extra) -> dict:
    """Базовые опции: один элемент плейлиста, без max_downloads (ломает fallback клиентов)."""
    import shutil

    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "playlistend": 1,
        # YouTube EJS: без JS-рантайма часть форматов/высот пропадает или криво размечается
        "remote_components": {"ejs:github", "ejs:npm"},
    }
    try:
        import imageio_ffmpeg

        opts["ffmpeg_location"] = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    js_runtimes: dict = {}
    if shutil.which("deno"):
        js_runtimes["deno"] = {}
    node = shutil.which("node")
    if node:
        js_runtimes["node"] = {"path": node}
    if js_runtimes:
        opts["js_runtimes"] = js_runtimes
    opts.update(extra)
    # если вызывающий передал ffmpeg_location=None — убрать
    if opts.get("ffmpeg_location") is None:
        opts.pop("ffmpeg_location", None)
    return opts


def _is_bot_check_error(err: Exception) -> bool:
    msg = str(err).lower()
    return (
        "sign in to confirm" in msg
        or "not a bot" in msg
        or "page needs to be reloaded" in msg
        or "confirm you're not a bot" in msg
    )


def _is_cookie_reload_error(err: Exception | str) -> bool:
    return "page needs to be reloaded" in str(err).lower()


def _make_progress_hook(progress_state: dict | None, cancel_event: threading.Event | None):
    def hook(d):
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled()
        if progress_state is None:
            return
        progress_state["updated_at"] = time.time()
        status = d.get("status")
        if status == "downloading":
            pct = (d.get("_percent_str") or "").strip()
            if not pct:
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                if total:
                    pct = f"{100.0 * done / total:.1f}%"
            progress_state["percent"] = pct
            progress_state["speed"] = (d.get("_speed_str") or "").strip()
            progress_state["eta"] = (d.get("_eta_str") or "").strip()
            info = d.get("info_dict") or {}
            from media_core.video_quality import effective_video_height, snap_quality_height

            h = effective_video_height(info)
            if h:
                note = f"{snap_quality_height(h)}p"
            else:
                note = (info.get("format_note") or info.get("format_id") or "").strip()
            ext = info.get("ext") or d.get("filename", "").rsplit(".", 1)[-1]
            label = "Скачиваю"
            if note or ext:
                parts = [p for p in (note, ext) if p]
                label = f"Скачиваю ({', '.join(parts)})" if parts else label
            progress_state["stage"] = label
            progress_state["indeterminate"] = False
        elif status == "finished":
            # после потока часто идёт ffmpeg (склейка / аудио)
            progress_state["percent"] = ""
            progress_state["speed"] = ""
            progress_state["eta"] = ""
            progress_state["stage"] = "Обработка ffmpeg (склейка / конвертация)…"
            progress_state["indeterminate"] = True
        elif status == "error":
            progress_state["stage"] = "Ошибка загрузки"
            progress_state["indeterminate"] = False
    return hook


def _ytdlp_extract_sync(url: str, ydl_opts: dict, download: bool, progress_state: dict | None = None):
    """extract_info с fallback-клиентами только при bot-check.

    Важно: не начинать с android/ios — у них часто только ~360p без PO token.
    Сначала дефолтные клиенты yt-dlp (полные форматы), затем fallback.
    Для probe выбираем самый полный набор качеств.
    """
    from media_core.video_quality import format_richness

    last_error: Exception | None = None
    # Всегда сначала default (None), иначе cookies+android → 360p
    attempts = [None] + list(YOUTUBE_CLIENT_FALLBACKS)

    best_info = None
    best_filename = None
    best_score = -1

    for client in attempts:
        opts = dict(ydl_opts)
        if client:
            opts["extractor_args"] = {"youtube": {"player_client": [client]}}
            if progress_state is not None:
                progress_state["stage"] = f"YouTube блокирует — пробую клиент {client}…"
                progress_state["updated_at"] = time.time()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=download)
                target_info = info
                if info and info.get("entries"):
                    entries = list(info["entries"])
                    if entries:
                        target_info = entries[0]
                if download and target_info:
                    _set_last_extract_info(target_info)
                    filename = ydl.prepare_filename(target_info)
                    return target_info, filename
                if not download:
                    score = format_richness(target_info)
                    if score > best_score and target_info and target_info.get("title"):
                        best_score = score
                        best_info = target_info
                        best_filename = None
                    if score >= 7000:
                        return target_info, None
        except DownloadCancelled:
            raise
        except Exception as e:
            last_error = e
            if _is_bot_check_error(e):
                log.info("yt-dlp: YouTube отказ (client=%s): %s", client or "default", e)
                continue
            if download:
                # для download пробуем следующий клиент только при bot-check;
                # иные ошибки — сразу наружу, кроме «format not available»
                msg = str(e).lower()
                if "requested format is not available" in msg or "no video formats" in msg:
                    log.info("yt-dlp: client=%s нет нужного формата: %s", client or "default", e)
                    continue
                raise
            log.info("yt-dlp: client=%s ошибка probe: %s", client or "default", e)
            continue

    if not download and best_info is not None:
        return best_info, best_filename

    if last_error is not None and best_info is None:
        raise last_error
    return best_info or {}, best_filename


def _apply_ytdlp_cookies(
    ydl_opts: dict,
    url: str,
    *,
    extra_http_cookie: str | None = None,
    extra_cookiefile: str | None = None,
    ignore_cookies: bool = False,
) -> None:
    if ignore_cookies:
        return
    if extra_cookiefile and os.path.isfile(extra_cookiefile):
        ydl_opts["cookiefile"] = extra_cookiefile
    elif extra_http_cookie:
        ydl_opts.setdefault("http_headers", {})["Cookie"] = extra_http_cookie
    elif youtube_cookies_active():
        ydl_opts["cookiefile"] = COOKIES_FILE


def _probe_video_info_sync(
    url: str,
    proxy: str | None,
    *,
    extra_http_cookie: str | None = None,
    extra_cookiefile: str | None = None,
    ignore_cookies: bool = False,
) -> dict:
    from media_core.net_proxy import ytdlp_proxy_opt

    ydl_opts = ytdlp_safe_opts(skip_download=True, socket_timeout=20)
    # всегда явно: иначе yt-dlp берёт системный VPN/PAC и «висит»
    ydl_opts["proxy"] = ytdlp_proxy_opt(proxy)
    if not ignore_cookies:
        _apply_ytdlp_cookies(
            ydl_opts, url, extra_http_cookie=extra_http_cookie, extra_cookiefile=extra_cookiefile,
        )
    info, _ = _ytdlp_extract_sync(url, ydl_opts, download=False)
    return info or {}


def _probe_result_usable(info: dict | None) -> bool:
    return bool(info and info.get("title"))


async def probe_video_info(
    url: str,
    *,
    extra_http_cookie: str | None = None,
    extra_cookiefile: str | None = None,
    proxies_override: list[str | None] | None = None,
) -> dict:
    from media_core.probe_cache import get_cached_probe, set_cached_probe

    cached = await get_cached_probe(url)
    if cached is not None:
        return cached

    proxies: list[str | None]
    if proxies_override is not None:
        proxies = proxies_override
    else:
        proxies = await get_proxies_to_try()
        if not proxies:
            proxies = [None]

    last_error: Exception | None = None

    async def _run_probe(ignore_cookies: bool) -> dict | None:
        nonlocal last_error

        async def _probe(proxy: str | None) -> dict:
            return await asyncio.to_thread(
                _probe_video_info_sync,
                url,
                proxy,
                extra_http_cookie=extra_http_cookie,
                extra_cookiefile=extra_cookiefile,
                ignore_cookies=ignore_cookies,
            )

        for proxy in proxies:
            label = "direct" if proxy is None else mask_proxy(proxy)
            try:
                raw = await asyncio.wait_for(_probe(proxy), timeout=25)
            except Exception as e:
                last_error = e
                log.warning("probe: %s не сработал: %s", label, e)
                if proxy is not None:
                    await record_proxy_result(proxy, success=False, error=str(e))
                if is_fatal_proxy_error(e):
                    break
                continue
            if _probe_result_usable(raw):
                if proxy is not None:
                    await record_proxy_result(proxy, success=True, latency_ms=None)
                return raw
            last_error = RuntimeError("empty metadata")
            log.warning("probe: %s — пустые метаданные", label)
        return None

    result = await _run_probe(ignore_cookies=False)
    if result is None and youtube_cookies_active() and not extra_http_cookie and not extra_cookiefile:
        log.info("probe: повтор без cookies (cookies могли сломать yt-dlp)")
        result = await _run_probe(ignore_cookies=True)

    if result is not None:
        await set_cached_probe(url, result)
        return result

    log.error("probe: не удалось получить метаданные: %s", last_error)
    _set_last_error(last_error)
    if application and len(proxies) > 1:
        await notify_admins(
            application,
            f"Не удалось получить превью.\nПоследняя ошибка: {last_error}",
            alert_key="all_proxies_probe",
        )
    return {}


def _ytdlp_format(url: str, audio_only: bool, format_override: str | None) -> str:
    if format_override:
        return format_override
    if audio_only:
        return "bestaudio/best"
    if detect_platform(url) == "coub":
        return "bestvideo+bestaudio/best"
    return "mp4/best"


def _coub_merge_postprocessor_args() -> dict[str, list[str]]:
    """Цикл видео до конца аудио.

    Важно: -stream_loop не работает с -c copy (Merger по умолчанию),
    поэтому явно перекодируем.
    """
    return {
        # i1 = первый вход (видео) в нумерации yt-dlp
        "Merger+ffmpeg_i1": ["-stream_loop", "-1"],
        "Merger+ffmpeg_o1": [
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
        ],
    }


def _find_downloaded_path(filename: str | None, audio_only: bool) -> str | None:
    if not filename:
        return None
    if audio_only:
        base = filename.rsplit(".", 1)[0]
        for ext in (".mp3", ".m4a", ".webm"):
            path = base + ext
            if os.path.exists(path):
                return path
        return None
    if os.path.exists(filename):
        return filename
    base = filename.rsplit(".", 1)[0]
    mp4 = base + ".mp4"
    return mp4 if os.path.exists(mp4) else None


def estimate_quality_sizes(formats: list[dict]) -> dict[str, int | None]:
    from media_core.config import QUALITY_HEIGHTS

    def fsize(f: dict) -> int | None:
        return f.get("filesize") or f.get("filesize_approx")

    audio_candidates = [f for f in formats if f.get("vcodec") == "none" and fsize(f)]
    audio_size = max((fsize(f) for f in audio_candidates), default=None)

    results: dict[str, int | None] = {}
    for key, max_h in QUALITY_HEIGHTS:
        candidates = [
            f for f in formats
            if f.get("vcodec") not in (None, "none")
            and (f.get("height") or 0) <= max_h
            and fsize(f)
        ]
        if not candidates:
            results[key] = None
            continue
        best = max(candidates, key=lambda f: f.get("height") or 0)
        size = fsize(best)
        if best.get("acodec") == "none":
            size = (size or 0) + (audio_size or 0)
        results[key] = size

    video_all = [f for f in formats if f.get("vcodec") not in (None, "none") and fsize(f)]
    if video_all:
        best = max(video_all, key=lambda f: f.get("height") or 0)
        size = fsize(best)
        if best.get("acodec") == "none":
            size = (size or 0) + (audio_size or 0)
        results["best"] = size
    else:
        results["best"] = None
    return results


def format_size(num_bytes: int | None) -> str:
    if not num_bytes:
        return ""
    return f"~{num_bytes / (1024 * 1024):.0f} МБ"


async def download_ytdlp(
    url: str,
    audio_only: bool = False,
    format_override: str | None = None,
    progress_state: dict | None = None,
    cancel_event: threading.Event | None = None,
    start: float | None = None,
    end: float | None = None,
    *,
    extra_http_cookie: str | None = None,
    extra_cookiefile: str | None = None,
    proxies_override: list[str | None] | None = None,
    merge_output_format: str = "mp4",
    rate_limit: str | None = None,
    subtitles_mode: str = "off",
):
    from media_core.constants import CANCELLED

    try:
        if cancel_event is not None and cancel_event.is_set():
            return CANCELLED

        proxies: list[str | None]
        if proxies_override is not None:
            proxies = proxies_override
        else:
            loaded = await get_proxies_to_try()
            if not loaded:
                log.warning("yt-dlp: нет активных прокси — скачивание отменено")
                _set_last_error("нет активных прокси")
                if application:
                    await notify_admins(application, "Нет активных прокси (download).", alert_key="no_proxies")
                return None
            proxies = loaded

        last_error: Exception | None = None
        total = len(proxies)
        used_cookies = youtube_cookies_active() or bool(extra_http_cookie or extra_cookiefile)
        cookie_modes = [False, True] if used_cookies else [False]
        # False = обычный режим (cookies если включены); True = принудительно без cookies
        for ignore_cookies in cookie_modes:
            if ignore_cookies and used_cookies:
                log.info("yt-dlp: повтор без cookies (YouTube часто ломается на cookies из браузера)")
                if progress_state is not None:
                    progress_state["stage"] = "Повтор без cookies…"
                    progress_state["updated_at"] = time.time()
            for idx, proxy in enumerate(proxies, start=1):
                if cancel_event is not None and cancel_event.is_set():
                    return CANCELLED

                t0 = time.time()
                if progress_state is not None:
                    if proxy is None:
                        progress_state["stage"] = "Связываюсь с YouTube…"
                    else:
                        progress_state["stage"] = f"Пробую прокси {idx}/{total}…"
                    progress_state["percent"] = ""
                    progress_state["speed"] = ""
                    progress_state["eta"] = ""
                    progress_state["indeterminate"] = True
                    progress_state["updated_at"] = time.time()
                fmt = _ytdlp_format(url, audio_only, format_override)
                ydl_opts = ytdlp_safe_opts(
                    outtmpl="media_%(id)s.%(ext)s",
                    format=fmt,
                    progress_hooks=[_make_progress_hook(progress_state, cancel_event)],
                    socket_timeout=30,
                    retries=2,
                    fragment_retries=2,
                    concurrent_fragment_downloads=4,
                    merge_output_format=merge_output_format or "mp4",
                    continuedl=True,
                )
                if rate_limit:
                    ydl_opts["ratelimit"] = _parse_rate_limit(rate_limit)
                if subtitles_mode in ("srt", "embed") and detect_platform(url) == "youtube" and not audio_only:
                    ydl_opts["writesubtitles"] = True
                    ydl_opts["writeautomaticsub"] = True
                    ydl_opts["subtitleslangs"] = ["ru", "en", "ru-orig"]
                    ydl_opts["subtitlesformat"] = "srt/best"
                    if subtitles_mode == "embed":
                        ydl_opts.setdefault("postprocessors", [])
                        ydl_opts["postprocessors"] = list(ydl_opts.get("postprocessors") or []) + [{
                            "key": "FFmpegEmbedSubtitle",
                            "already_have_subtitle": False,
                        }]
                        ydl_opts["postprocessors"].append({"key": "FFmpegMetadata"})
                from media_core.net_proxy import ytdlp_proxy_opt

                ydl_opts["proxy"] = ytdlp_proxy_opt(proxy)
                _apply_ytdlp_cookies(
                    ydl_opts, url,
                    extra_http_cookie=extra_http_cookie,
                    extra_cookiefile=extra_cookiefile,
                    ignore_cookies=ignore_cookies,
                )
                if detect_platform(url) == "coub" and not audio_only:
                    ydl_opts["postprocessor_args"] = _coub_merge_postprocessor_args()
                if audio_only:
                    pps = list(ydl_opts.get("postprocessors") or [])
                    pps.append({
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    })
                    ydl_opts["postprocessors"] = pps
                if start is not None:
                    ydl_opts["download_ranges"] = download_range_func(None, [(start, end)])
                    ydl_opts["force_keyframes_at_cuts"] = True

                if progress_state is not None:
                    progress_state["stage"] = "Разбираю ссылку и форматы…"
                    progress_state["updated_at"] = time.time()

                try:
                    _, filename = await asyncio.to_thread(
                        _ytdlp_extract_sync, url, ydl_opts, True, progress_state,
                    )
                except DownloadCancelled:
                    log.info("yt-dlp: скачивание отменено пользователем")
                    return CANCELLED
                except Exception as e:
                    last_error = e
                    _set_last_error(e)
                    log.warning(
                        "yt-dlp: %s не сработал%s: %s",
                        "direct" if proxy is None else mask_proxy(proxy),
                        " (без cookies)" if ignore_cookies else "",
                        e,
                    )
                    await record_proxy_result(proxy, success=False, error=str(e))
                    if is_fatal_proxy_error(e) and not _is_cookie_reload_error(e):
                        break
                    continue

                path = _find_downloaded_path(filename, audio_only)
                if path:
                    if detect_platform(url) == "coub" and not audio_only:
                        path = await remux_coub_looped(path)
                    await record_proxy_result(proxy, success=True, latency_ms=(time.time() - t0) * 1000)
                    return path

                err = "audio file not found on disk" if audio_only else "video file not found on disk"
                log.warning("yt-dlp: %s (%s)", err, "direct" if proxy is None else mask_proxy(proxy))
                await record_proxy_result(proxy, success=False, error=err)
                last_error = RuntimeError(err)

            # Если cookies не виноваты — нет смысла второй круг без cookies.
            if not ignore_cookies and used_cookies and last_error and _is_cookie_reload_error(last_error):
                continue
            if not ignore_cookies and used_cookies and last_error and _is_bot_check_error(last_error):
                continue
            break

        friendly = str(last_error or "не удалось скачать")
        if _is_cookie_reload_error(friendly):
            friendly = (
                "YouTube отклонил запрос (cookies). "
                "Попробуй выключить «Использовать cookies» в настройках или обновить cookies из браузера."
            )
        log.error("yt-dlp: скачивание не удалось: %s", last_error)
        _set_last_error(friendly)
        if application and len(proxies) > 1:
            await notify_admins(
                application,
                f"Скачивание не удалось.\nПоследняя ошибка: {last_error}",
                alert_key="all_proxies_download",
            )
        return None
    except DownloadCancelled:
        return CANCELLED
    except Exception as e:
        log.exception("yt-dlp error: %s", e)
        _set_last_error(e)
        return None


def _find_subtitle_path(stem: str) -> str | None:
    if not stem:
        return None
    base = stem.rsplit(".", 1)[0] if "." in os.path.basename(stem) else stem
    for name in os.listdir("."):
        if not name.startswith(os.path.basename(base).split(".")[0]):
            continue
        if name.endswith((".srt", ".vtt")) and os.path.isfile(name):
            return name
    for ext in (".ru.srt", ".en.srt", ".srt", ".vtt"):
        path = base + ext
        if os.path.exists(path):
            return path
    return None


async def download_ytdlp_subtitles(
    url: str,
    progress_state: dict | None = None,
    cancel_event: threading.Event | None = None,
):
    from media_core.constants import CANCELLED

    if cancel_event is not None and cancel_event.is_set():
        return CANCELLED
    if detect_platform(url) != "youtube":
        _set_last_error("Субтитры доступны только для YouTube")
        return None

    proxies = await get_proxies_to_try()
    if not proxies:
        _set_last_error("нет активных прокси")
        return None

    last_error: Exception | None = None
    for proxy in proxies:
        if cancel_event is not None and cancel_event.is_set():
            return CANCELLED
        t0 = time.time()
        ydl_opts = ytdlp_safe_opts(
            skip_download=True,
            writesubtitles=True,
            writeautomaticsub=True,
            subtitleslangs=["ru", "en", "ru-orig"],
            subtitlesformat="srt/best",
            outtmpl="media_%(id)s.%(ext)s",
            proxy=proxy,
        )
        if youtube_cookies_active():
            ydl_opts["cookiefile"] = COOKIES_FILE
        try:
            info, filename = await asyncio.to_thread(_ytdlp_extract_sync, url, ydl_opts, True)
        except DownloadCancelled:
            return CANCELLED
        except Exception as e:
            last_error = e
            _set_last_error(e)
            await record_proxy_result(proxy, success=False, error=str(e))
            continue
        path = _find_subtitle_path(filename or "")
        if not path and info:
            vid = info.get("id") or "video"
            path = _find_subtitle_path(f"media_{vid}")
        if path:
            await record_proxy_result(proxy, success=True, latency_ms=(time.time() - t0) * 1000)
            if progress_state is not None:
                progress_state["stage"] = "Субтитры готовы"
            return path
        last_error = RuntimeError("subtitle file not found")
        await record_proxy_result(proxy, success=False, error="subtitle file not found")

    _set_last_error(last_error or "все прокси исчерпаны")
    return None
