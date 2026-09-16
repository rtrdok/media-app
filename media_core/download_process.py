"""Единая точка скачивания по платформе (без Premium/Vault)."""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

from media_core.constants import CANCELLED
from media_core.download_soundcloud import download_soundcloud
from media_core.download_tiktok import download_tiktok
from media_core.download_vk_audio import download_vk_audio
from media_core.download_yandex_music import download_yandex_music
from media_core.download_ytdlp import download_ytdlp
from media_core.file_cache import cache_key, copy_for_send, get_cached_path, store_cached_path
from media_core.settings_store import get_download_dir_for_url, get_rate_limit, get_subtitles_mode
from media_core.utils import (
    cache_display_filename,
    detect_platform,
    is_soundcloud_url,
    is_vk_audio_url,
    is_yandex_music_url,
)


def get_last_download_error():
    from media_core.download_vk_audio import get_last_download_error as vk_err
    from media_core.download_ytdlp import get_last_download_error as ytdlp_err

    return vk_err() or ytdlp_err()


def save_to_downloads(src_path: str, url: str, audio_only: bool, title: str | None = None) -> str:
    dest_dir = Path(get_download_dir_for_url(url))
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = cache_display_filename(url, audio_only, src_path, track=title)
    dest = dest_dir / name
    if dest.exists():
        stem, ext = dest.stem, dest.suffix
        i = 2
        while True:
            candidate = dest_dir / f"{stem}_{i}{ext}"
            if not candidate.exists():
                dest = candidate
                break
            i += 1
    shutil.copy2(src_path, dest)
    return str(dest)


async def process_url(
    url: str,
    audio_only: bool = False,
    format_override: str | None = None,
    progress_state: dict | None = None,
    cancel_event: threading.Event | None = None,
    start: float | None = None,
    end: float | None = None,
    *,
    record_stats: bool = False,
    user_id: int | None = None,
    use_cache: bool = True,
    container: str | None = None,
    rate_limit: str | None = None,
    subtitles_mode: str | None = None,
):
    import asyncio

    from media_core.utils import convert_media

    platform = detect_platform(url)
    if not platform:
        return None

    container = (container or "").lower().lstrip(".") or None
    if audio_only:
        container = "mp3"
    rate_limit = rate_limit if rate_limit is not None else get_rate_limit()
    subtitles_mode = subtitles_mode if subtitles_mode is not None else get_subtitles_mode()

    key = cache_key(
        url, audio_only=audio_only, format_override=format_override, start=start, end=end,
        container=container,
    )
    if use_cache:
        cached = await get_cached_path(key)
        if cached:
            return await copy_for_send(cached)

    if platform == "direct":
        from media_core.direct_download import download_direct

        path = await asyncio.to_thread(
            download_direct, url, get_download_dir_for_url(url, platform), progress_state,
        )
    elif platform == "instagram":
        from media_core.utils import is_instagram_stories_url, youtube_cookies_active
        if is_instagram_stories_url(url) and not youtube_cookies_active():
            from media_core.download_ytdlp import _set_last_error
            _set_last_error("Instagram Stories: нужны cookies (Настройки → Cookies из Chrome/Edge)")
            return None
        path = await download_ytdlp(
            url, audio_only, format_override=format_override,
            progress_state=progress_state, cancel_event=cancel_event,
            start=start, end=end,
            merge_output_format=(container if container in ("mp4", "webm", "mkv", "mov") else "mp4"),
            rate_limit=rate_limit or None,
            subtitles_mode=subtitles_mode,
        )
    elif is_vk_audio_url(url):
        path = await download_vk_audio(url, cancel_event=cancel_event)
    elif is_yandex_music_url(url):
        path = await download_yandex_music(
            url, progress_state=progress_state, cancel_event=cancel_event,
            start=start, end=end, audio_only=audio_only,
        )
    elif is_soundcloud_url(url):
        path = await download_soundcloud(
            url, progress_state=progress_state, cancel_event=cancel_event,
            start=start, end=end, audio_only=audio_only,
        )
    elif platform == "tiktok":
        path = await download_tiktok(url, audio_only, cancel_event=cancel_event)
    else:
        path = await download_ytdlp(
            url, audio_only, format_override=format_override,
            progress_state=progress_state, cancel_event=cancel_event,
            start=start, end=end,
            merge_output_format=(container if container in ("mp4", "webm", "mkv", "mov") else "mp4"),
            rate_limit=rate_limit or None,
            subtitles_mode=subtitles_mode,
        )

    if path and path is not CANCELLED and os.path.isfile(path) and container and platform != "direct":
        if progress_state is not None:
            progress_state["stage"] = f"Конвертирую в {container.upper()}…"
            progress_state["indeterminate"] = True
        path = await convert_media(path, container)

    if path and path is not CANCELLED:
        if use_cache and os.path.isfile(path):
            try:
                await store_cached_path(key, url, path)
            except Exception:
                pass
    return path
