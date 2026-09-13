"""SoundCloud через yt-dlp (Vault#101)."""

from __future__ import annotations

import threading

from media_core.config import resolve_soundcloud_cookies
from media_core.constants import CANCELLED
from media_core.download_ytdlp import download_ytdlp, get_last_download_error
from media_core.logging_setup import log
from media_core.vault_track import rename_download_to_title


async def download_soundcloud(
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

    http_cookie, cookiefile = resolve_soundcloud_cookies()

    path = await download_ytdlp(
        url,
        audio_only=audio_only,
        progress_state=progress_state,
        cancel_event=cancel_event,
        start=start,
        end=end,
    )
    if not path:
        if not http_cookie and not cookiefile:
            log.info("soundcloud: public download failed, cookies not configured")
            return None
        log.info("soundcloud: retry with cookies")
        path = await download_ytdlp(
            url,
            audio_only=audio_only,
            progress_state=progress_state,
            cancel_event=cancel_event,
            start=start,
            end=end,
            extra_http_cookie=http_cookie,
            extra_cookiefile=cookiefile,
        )
    if not path:
        return None
    return await rename_download_to_title(url, path, generic_title="SoundCloud")


def get_last_soundcloud_error():
    return get_last_download_error()
