"""Кэш metadata probe."""

from __future__ import annotations

import asyncio
import json
import time

from media_core.config import PROBE_CACHE_TTL_SECONDS
from media_core.database import probe_cache_get, probe_cache_put

_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = asyncio.Lock()


async def get_cached_probe(url: str) -> dict | None:
    url = url.strip()
    now = time.time()
    async with _LOCK:
        row = _CACHE.get(url)
        if row and now - row[0] <= PROBE_CACHE_TTL_SECONDS and row[1].get("title"):
            return row[1]

    db_row = await probe_cache_get(url)
    if db_row:
        created_at, payload = db_row
        if now - created_at <= PROBE_CACHE_TTL_SECONDS:
            data = json.loads(payload)
            if data.get("title"):
                async with _LOCK:
                    _CACHE[url] = (created_at, data)
                return data
    return None


async def clear_probe_cache() -> None:
    async with _LOCK:
        _CACHE.clear()

    def _sync():
        from media_core.database import _connect

        conn = _connect()
        try:
            conn.execute("DELETE FROM probe_cache")
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


async def set_cached_probe(url: str, info: dict) -> None:
    url = url.strip()
    if not (info or {}).get("title"):
        return
    now = time.time()
    slim = {
        "title": info.get("title"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader") or info.get("channel"),
        "formats": info.get("formats"),
        "entries": info.get("entries"),
        "_playlist_count": info.get("playlist_count"),
    }
    async with _LOCK:
        _CACHE[url] = (now, slim)
    await probe_cache_put(url, json.dumps(slim, ensure_ascii=False))
