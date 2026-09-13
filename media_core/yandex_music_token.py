"""Обмен cookies Яндекса на music OAuth token."""

from __future__ import annotations

import threading
import time

import httpx

from media_core.config import resolve_yandex_cookies
from media_core.cookie_netscape import resolve_cookie_header
from media_core.logging_setup import log

_X_TOKEN_CLIENT_ID = "c0ebe342af7d48fbbbfcf2d2eedb8f9e"
_X_TOKEN_CLIENT_SECRET = "ad0a908f0aa341a182a37ecd75bc319e"
_MUSIC_CLIENT_ID = "23cabbbdc6cd418abb4b39c32c41195d"
_MUSIC_CLIENT_SECRET = "53bc75238f0c4d08a118e51fe9203300"

_lock = threading.Lock()
_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 3600


def _cookie_key() -> str:
    _, cookiefile = resolve_yandex_cookies()
    return resolve_cookie_header(None, cookiefile)


def clear_yandex_token_cache() -> None:
    with _lock:
        _cache.clear()


async def get_yandex_music_token() -> str | None:
    cookies = _cookie_key()
    if not cookies:
        return None

    with _lock:
        cached = _cache.get(cookies)
        if cached and time.time() - cached[1] < _CACHE_TTL:
            return cached[0]

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            x_resp = await client.post(
                "https://mobileproxy.passport.yandex.net/1/bundle/oauth/token_by_sessionid",
                params={"app_id": "ru.yandex.mobile.music"},
                data={
                    "client_id": _X_TOKEN_CLIENT_ID,
                    "client_secret": _X_TOKEN_CLIENT_SECRET,
                    "grant_type": "sessionid",
                    "host": "yandex.ru",
                },
                headers={
                    "Ya-Client-Host": "passport.yandex.ru",
                    "Ya-Client-Cookie": cookies,
                },
            )
            x_resp.raise_for_status()
            x_data = x_resp.json()
            if x_data.get("status") == "error":
                errors = x_data.get("errors") or []
                if "sessionid.invalid" in errors:
                    log.warning("yandex token: cookies expired (sessionid.invalid)")
                    from media_core.download_ytdlp import _set_last_error
                    _set_last_error(
                        "Яндекс Музыка: cookies устарели. "
                        "Залогинься на music.yandex.ru заново и обнови yandex_cookies.txt"
                    )
                else:
                    log.warning("yandex token exchange errors: %s", errors)
                return None
            x_token = x_data.get("access_token")
            if not x_token:
                log.warning("yandex token: no x_token in response")
                return None

            m_resp = await client.post(
                "https://oauth.mobile.yandex.net/1/token",
                data={
                    "client_id": _MUSIC_CLIENT_ID,
                    "client_secret": _MUSIC_CLIENT_SECRET,
                    "grant_type": "x-token",
                    "access_token": x_token,
                },
            )
            m_resp.raise_for_status()
            m_data = m_resp.json()
            music_token = m_data.get("access_token")
            if not music_token:
                log.warning("yandex token: no music token in response")
                return None
    except Exception as e:
        log.warning("yandex token exchange failed: %s", e)
        return None

    with _lock:
        _cache[cookies] = (music_token, time.time())
    return music_token
