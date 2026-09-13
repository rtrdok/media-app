"""Общее для Vault-треков (SoundCloud, Яндекс Музыка): переименование файла."""

from __future__ import annotations

import os

from media_core.logging_setup import log
from media_core.utils import safe_filename


async def rename_download_to_title(
    url: str,
    path: str,
    *,
    generic_title: str,
) -> str:
    from media_core.probe_cache import get_cached_probe

    title = ""
    cached = await get_cached_probe(url)
    if cached:
        raw = cached.get("title") or ""
        artist = cached.get("uploader") or cached.get("artist") or ""
        if raw:
            title = raw
            if artist and artist.lower() not in raw.lower():
                title = f"{artist} — {raw}"
    if not title:
        from media_core.download_ytdlp import get_last_extract_info

        info = get_last_extract_info()
        if info:
            raw = info.get("title") or info.get("track") or ""
            artist = info.get("uploader") or info.get("artist") or ""
            if raw:
                title = raw
                if artist and artist.lower() not in raw.lower():
                    title = f"{artist} — {raw}"
    title = title.strip()
    if not title or title.lower() == generic_title.lower():
        return path
    ext = os.path.splitext(path)[1] or ".mp3"
    dest = safe_filename(title, ext)
    if os.path.basename(path) == dest:
        return path
    if os.path.isfile(dest):
        try:
            os.remove(dest)
        except OSError:
            pass
    try:
        os.rename(path, dest)
        log.info("vault track: renamed to %s", dest)
        return dest
    except OSError as e:
        log.warning("vault track rename failed: %s", e)
        return path
