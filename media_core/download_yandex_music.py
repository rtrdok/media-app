"""Яндекс Музыка (Vault#101, cookies обязательны)."""

from __future__ import annotations

import threading

from media_core.config import yandex_music_configured
from media_core.constants import CANCELLED
from media_core.download_ytdlp import get_last_download_error, _set_last_error
from media_core.logging_setup import log
from media_core.utils import safe_filename
import os


async def download_yandex_music(
    url: str,
    *,
    audio_only: bool = True,
    progress_state: dict | None = None,
    cancel_event: threading.Event | None = None,
    start: float | None = None,
    end: float | None = None,
) -> str | None:
    if cancel_event is not None and cancel_event.is_set():
        return CANCELLED

    if not yandex_music_configured():
        _set_last_error(
            "Яндекс Музыка не настроена. Положи cookies music.yandex.ru в yandex_cookies.txt"
        )
        return None

    from media_core.yandex_music_api import download_yandex_track

    path, info = await download_yandex_track(url, cancel_event=cancel_event)
    if not path:
        if not get_last_download_error():
            _set_last_error(
                "Яндекс Музыка: не удалось получить трек. "
                "Обнови cookies в yandex_cookies.txt или проверь подписку."
            )
        log.warning("yandex music download failed")
        return None

    if info and info.label:
        new_path = os.path.join(os.path.dirname(path) or ".", safe_filename(info.label))
        if new_path != path:
            try:
                if os.path.isfile(new_path):
                    os.remove(new_path)
                os.replace(path, new_path)
                path = new_path
            except OSError as e:
                log.warning("yandex rename failed: %s", e)

    return path


def get_last_yandex_music_error():
    return get_last_download_error()
