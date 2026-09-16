"""Обложки для Discord Rich Presence.

Discord часто не показывает картинки напрямую с VK/Яндекс (hotlink/CORS у media-proxy).
Качаем cover и коротко кладём на публичный хост (litterbox), URL кэшируем.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from media_core.config import BASE_DIR
from media_core.logging_setup import log

_CACHE_DIR = BASE_DIR / "file_cache" / "discord_covers"
_META_PATH = _CACHE_DIR / "cache.json"
_META_TTL = 6 * 3600  # 6 часов — litterbox temporary
_meta_lock_note = False


def discord_cover_image(thumb: str | None) -> str | None:
    """Нормализовать thumb в https URL (без рехоста)."""
    t = (thumb or "").strip()
    if t.startswith("//"):
        t = "https:" + t
    if t.startswith("http://"):
        t = "https://" + t[len("http://") :]
    if not t.startswith("https://"):
        return None
    # Яндекс: просим крупнее (Discord лучше ест ≥512)
    if "avatars.yandex.net" in t or "music.yandex" in t:
        for size in ("%%", "100x100", "200x200", "300x300", "400x400"):
            if size in t:
                t = t.replace(size, "1000x1000")
                break
    if len(t) <= 256:
        return t
    # VK signed URLs нельзя резать по «?» — иначе 403
    return None if len(t) > 256 else t


def _load_meta() -> dict[str, Any]:
    try:
        if _META_PATH.is_file():
            return json.loads(_META_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_meta(data: dict[str, Any]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _META_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    except OSError:
        pass


def _cache_get(src: str) -> str | None:
    meta = _load_meta()
    row = meta.get(src)
    if not isinstance(row, dict):
        return None
    if float(row.get("exp") or 0) < time.time():
        return None
    url = str(row.get("url") or "")
    return url if url.startswith("https://") else None


def _cache_set(src: str, url: str) -> None:
    meta = _load_meta()
    meta[src] = {"url": url, "exp": time.time() + _META_TTL}
    # не раздувать
    if len(meta) > 200:
        oldest = sorted(meta.items(), key=lambda kv: float(kv[1].get("exp") or 0))[:80]
        for k, _ in oldest:
            meta.pop(k, None)
    _save_meta(meta)


def _download_bytes(url: str) -> tuple[bytes, str] | None:
    try:
        with httpx.Client(timeout=20, follow_redirects=True, trust_env=False) as client:
            r = client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/*,*/*",
                },
            )
            r.raise_for_status()
            data = r.content
            if len(data) < 800 or len(data) > 4_500_000:
                return None
            ctype = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip().lower()
            if "png" in ctype:
                ext = "png"
            elif "webp" in ctype:
                ext = "webp"
            elif "gif" in ctype:
                ext = "gif"
            else:
                ext = "jpg"
            return data, ext
    except Exception as e:
        log.warning("discord cover download failed: %s", e)
        return None


def _upload_litterbox(data: bytes, ext: str) -> str | None:
    """Временный хост без API-ключа (файл живёт ~12ч на стороне сервиса)."""
    try:
        with httpx.Client(timeout=40, follow_redirects=True, trust_env=False) as client:
            r = client.post(
                "https://litterbox.catbox.moe/resources/internals/api.php",
                data={"reqtype": "fileupload", "time": "12h"},
                files={"fileToUpload": (f"cover.{ext}", data, f"image/{ext}")},
            )
            r.raise_for_status()
            out = (r.text or "").strip()
            if out.startswith("https://"):
                return out
            log.warning("litterbox unexpected response: %s", out[:120])
    except Exception as e:
        log.warning("litterbox upload failed: %s", e)
    return None


def _upload_0x0(data: bytes, ext: str) -> str | None:
    try:
        with httpx.Client(timeout=40, follow_redirects=True, trust_env=False) as client:
            r = client.post(
                "https://0x0.st",
                files={"file": (f"cover.{ext}", data, f"image/{ext}")},
            )
            r.raise_for_status()
            out = (r.text or "").strip()
            if out.startswith("https://"):
                return out
    except Exception as e:
        log.warning("0x0 upload failed: %s", e)
    return None


def resolve_discord_large_image(thumb: str | None) -> str | None:
    """URL для large_image: прямой https или рехост, если Discord не любит CDN сервиса."""
    src = discord_cover_image(thumb)
    if not src:
        return None

    cached = _cache_get(src)
    if cached:
        return cached if len(cached) <= 256 else None

    # Сначала пробуем отдать оригинал (короткий URL)
    host = (urlparse(src).hostname or "").lower()
    needs_rehost = any(
        x in host
        for x in (
            "yandex",
            "userapi",
            "vk.com",
            "vk.ru",
            "vkuserphoto",
            "akamaized",
        )
    ) or len(src) > 200

    if not needs_rehost and len(src) <= 256:
        return src

    got = _download_bytes(src)
    if not got:
        # fallback: всё же отдать исходник, если влезает
        return src if len(src) <= 256 else None
    data, ext = got
    public = _upload_litterbox(data, ext) or _upload_0x0(data, ext)
    if not public:
        return src if len(src) <= 256 else None
    if len(public) > 256:
        return None
    _cache_set(src, public)
    digest = hashlib.sha1(src.encode()).hexdigest()[:10]
    log.info("discord cover rehosted (%s… → %s)", digest, public[:48])
    return public
