"""Превью треков (VK / Яндекс): скачиваем во временный mp3 и отдаём файлом.

Прокси-стрим в WebView2 часто зависает на 0:00 — FileResponse надёжнее.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from media_core.config import BASE_DIR, load_vk_cookies
from media_core.logging_setup import log
from media_core.utils import is_vk_audio_url, is_yandex_music_url, parse_vk_audio_id

PREVIEW_DIR = BASE_DIR / "file_cache" / "music_preview"
_META_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_FILE_LOCKS: dict[str, asyncio.Lock] = {}


def _preview_path(page_url: str) -> Path:
    digest = hashlib.sha1(page_url.encode("utf-8", errors="replace")).hexdigest()[:20]
    return PREVIEW_DIR / f"{digest}.mp3"


def _lock_for(key: str) -> asyncio.Lock:
    lock = _FILE_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _FILE_LOCKS[key] = lock
    return lock


def _cache_meta(url: str, meta: dict[str, Any]) -> dict[str, Any]:
    store = {k: v for k, v in meta.items() if not str(k).startswith("_")}
    _META_CACHE[url] = (time.time() + 120.0, store)
    if len(_META_CACHE) > 64:
        oldest = min(_META_CACHE.items(), key=lambda kv: kv[1][0])
        _META_CACHE.pop(oldest[0], None)
    return store


async def resolve_music_stream(page_url: str) -> dict[str, Any] | None:
    """Метаданные + прямая ссылка на аудио."""
    url = (page_url or "").strip()
    if not url:
        return None

    cached = _META_CACHE.get(url)
    if cached and cached[0] > time.time():
        return dict(cached[1])

    if is_vk_audio_url(url):
        from media_core.download_vk_audio import fetch_vk_audio_info

        audio_id = parse_vk_audio_id(url)
        if not audio_id:
            return None
        info = await fetch_vk_audio_info(audio_id, source_url=url)
        if not info or not info.get("url"):
            return None
        return _cache_meta(
            url,
            {
                "stream_url": info["url"],
                "title": info.get("title") or "track",
                "artist": info.get("artist") or "",
                "album": info.get("album") or "",
                "cover": info.get("cover") or "",
                "label": info.get("label") or "",
                "platform": "vk",
                "page_url": url,
            },
        )

    if is_yandex_music_url(url):
        from media_core.yandex_music_api import (
            _get_client,
            _track_key,
            fetch_yandex_track_info,
            parse_yandex_track_url,
        )

        info = await fetch_yandex_track_info(url)
        if not info:
            return None
        client = await _get_client()
        if not client:
            return None
        ref = parse_yandex_track_url(url)
        if not ref:
            return None
        try:
            tracks = await client.tracks(_track_key(ref))
            if not tracks:
                return None
            track = tracks[0]
            downloads = await track.get_download_info_async(get_direct_links=True)
            if not downloads:
                return None
            best = max(downloads, key=lambda d: getattr(d, "bitrate_in_kbps", 0) or 0)
            stream = getattr(best, "direct_link", None)
            if not stream:
                stream = await best.get_direct_link_async()
            if not stream or not str(stream).startswith("http"):
                log.warning("yandex preview: no direct link")
                return None
            return _cache_meta(
                url,
                {
                    "stream_url": str(stream),
                    "title": info.title,
                    "artist": info.artist,
                    "album": info.album or "",
                    "cover": info.cover_url or "",
                    "label": info.label,
                    "platform": "yandex_music",
                    "page_url": url,
                },
            )
        except Exception as e:
            log.warning("yandex preview resolve failed: %s", e)
            return None

    return None


async def materialize_preview(page_url: str) -> dict[str, Any] | None:
    """Скачивает трек в file_cache/music_preview → {path, stream, title, ...}."""
    url = (page_url or "").strip()
    if not url:
        return None

    dest = _preview_path(url)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    async with _lock_for(str(dest)):
        info = await resolve_music_stream(url)
        if not info:
            return None

        if dest.is_file() and dest.stat().st_size > 4096:
            out = dict(info)
            out["path"] = str(dest)
            out["stream"] = f"/api/file?p={quote(str(dest))}"
            return out

        tmp = Path(str(dest) + ".part.mp3")
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass

        ok = False
        try:
            if info.get("platform") == "vk":
                from media_core.download_vk_audio import _download_mp3, get_last_download_error

                path = await _download_mp3(
                    str(info["stream_url"]),
                    str(tmp),
                    None,
                    cookies=load_vk_cookies() or "",
                )
                src = path if path and os.path.isfile(path) else (str(tmp) if tmp.is_file() else None)
                if src and os.path.getsize(src) > 4096:
                    os.replace(src, dest)
                    ok = True
                else:
                    err = get_last_download_error()
                    log.warning("vk preview download failed: %s", err)
            else:
                from media_core.net_proxy import httpx_proxy
                import httpx

                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "*/*",
                }
                async with httpx.AsyncClient(
                    timeout=120, follow_redirects=True, proxy=httpx_proxy()
                ) as client:
                    async with client.stream("GET", str(info["stream_url"]), headers=headers) as resp:
                        resp.raise_for_status()
                        with open(tmp, "wb") as f:
                            async for chunk in resp.aiter_bytes(65536):
                                f.write(chunk)
                if tmp.is_file() and tmp.stat().st_size > 4096:
                    os.replace(tmp, dest)
                    ok = True
        except Exception as e:
            log.warning("music preview materialize failed (%s): %s", info.get("platform"), e)
            ok = False
        finally:
            try:
                if tmp.is_file():
                    tmp.unlink()
            except OSError:
                pass

        if not ok or not dest.is_file():
            log.warning("music preview empty for %s", url[:80])
            return None

        out = dict(info)
        out["path"] = str(dest)
        out["stream"] = f"/api/file?p={quote(str(dest))}"
        return out


def player_stream_path(page_url: str) -> str:
    return f"/api/music/stream?url={quote(page_url, safe='')}"
