"""Кэш скачанных файлов по URL."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import time

from media_core.config import FILE_CACHE_DIR, FILE_CACHE_TTL_SECONDS
from media_core.database import file_cache_get, file_cache_put, file_cache_touch
from media_core.logging_setup import log
from media_core.utils import detect_platform


def _ensure_cache_dir() -> None:
    os.makedirs(FILE_CACHE_DIR, exist_ok=True)


def cache_key(
    url: str,
    *,
    audio_only: bool = False,
    format_override: str | None = None,
    start: float | None = None,
    end: float | None = None,
    container: str | None = None,
) -> str:
    parts = [
        "fmtv3",  # bump: смена YouTube-клиентов / селектора качества
        url.strip(),
        "1" if audio_only else "0",
        format_override or "",
        str(start if start is not None else ""),
        str(end if end is not None else ""),
        (container or "").lower(),
    ]
    if not audio_only and detect_platform(url.strip()) == "coub":
        parts.append("loop2")
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_cached_path(key: str) -> str | None:
    row = await file_cache_get(key)
    if not row:
        return None
    path, created_at = row
    if time.time() - created_at > FILE_CACHE_TTL_SECONDS:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
        return None
    if not os.path.isfile(path):
        return None
    await file_cache_touch(key)
    log.info("Кэш файла: hit %s", key[:12])
    return path


async def store_cached_path(key: str, url: str, source_path: str) -> str:
    _ensure_cache_dir()
    ext = os.path.splitext(source_path)[1] or ".bin"
    dest = os.path.join(FILE_CACHE_DIR, f"{key[:16]}{ext}")
    await asyncio.to_thread(shutil.copy2, source_path, dest)
    size = os.path.getsize(dest)
    await file_cache_put(key, url, dest, size)
    log.info("Кэш файла: saved %s (%s bytes)", key[:12], size)
    return dest


async def copy_for_send(cached_path: str) -> str:
    base, ext = os.path.splitext(os.path.basename(cached_path))
    tmp = f"tmp_cache_{base}_{int(time.time())}{ext}"
    await asyncio.to_thread(shutil.copy2, cached_path, tmp)
    return tmp
