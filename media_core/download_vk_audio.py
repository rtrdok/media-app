"""Скачивание треков VK Music (vk.com/audio…)."""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import subprocess
import threading
from typing import Any
from urllib.parse import urlparse

import httpx

from media_core.net_proxy import httpx_proxy

from media_core.config import VK_ACCESS_TOKEN, VK_API_VERSION, load_vk_cookies
from media_core.constants import CANCELLED
from media_core.logging_setup import log
from media_core.utils import parse_vk_audio_id, safe_filename, vk_audio_configured

_last_download_error: Exception | str | None = None
_last_vk_track_meta: dict | None = None

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)

_DATA_AUDIO_RE = re.compile(r'data-audio="([^"]+)"', re.I)
_AUDIO_ID_RE = re.compile(r"^(-?\d+)_(\d+)$")
_M3U8_TO_MP3_RE = re.compile(r"/[0-9a-f]+(/audios)?/([0-9a-f]+)/index.m3u8")
_VK1_TOKEN_RE = re.compile(r'"access_token"\s*:\s*"(vk1\.[^"]+)"')
_PRIVATE_PAGE_RE = re.compile(r"is_private|audio_private|private_audio", re.I)


def get_last_download_error() -> Exception | str | None:
    return _last_download_error


def get_last_vk_track_meta() -> dict | None:
    return dict(_last_vk_track_meta) if _last_vk_track_meta else None


def _set_last_vk_track_meta(info: dict | None, url: str = "") -> None:
    global _last_vk_track_meta
    if not info:
        _last_vk_track_meta = None
        return
    _last_vk_track_meta = {
        "title": info.get("title") or "",
        "artist": info.get("artist") or "",
        "album": info.get("album") or "",
        "duration": info.get("duration"),
        "thumbnail": info.get("cover") or info.get("thumbnail"),
        "label": info.get("label") or "",
        "url": url,
        "platform": "vk",
    }


def _set_last_error(err: Exception | str | None) -> None:
    global _last_download_error
    _last_download_error = err


def _cover_from_thumb_dict(thumb: dict[str, Any] | None) -> str | None:
    if not isinstance(thumb, dict):
        return None
    for key in (
        "photo_1200",
        "photo_600",
        "photo_300",
        "photo_270",
        "photo_135",
        "photo_68",
        "url",
        "src",
    ):
        url = thumb.get(key)
        if url and str(url).startswith("http"):
            return str(url)
    return None


def _cover_from_vk_item(item: dict[str, Any]) -> str | None:
    album = item.get("album") if isinstance(item.get("album"), dict) else None
    cover = _cover_from_thumb_dict(album.get("thumb") if album else None)
    if cover:
        return cover
    for key in ("cover", "cover_url", "coverUrl", "photo_1200", "photo_600", "photo_300"):
        url = item.get(key)
        if url and str(url).startswith("http"):
            return str(url)
    for nested_key in ("thumb", "image", "images"):
        nested = item.get(nested_key)
        if isinstance(nested, dict):
            cover = _cover_from_thumb_dict(nested)
            if cover:
                return cover
        if isinstance(nested, list):
            for entry in nested:
                if isinstance(entry, str) and entry.startswith("http"):
                    return entry
                if isinstance(entry, dict):
                    cover = _cover_from_thumb_dict(entry)
                    if cover:
                        return cover
    return None


def _cover_from_track_array(track: list) -> str | None:
    """Обложка из массива m.vk / al_audio (индексы как в vk_music_api)."""
    if not isinstance(track, list):
        return None
    for idx in (14, 19, 12, 11, 8, 15, 16, 17):
        if len(track) <= idx:
            continue
        cell = track[idx]
        if isinstance(cell, str) and cell.startswith("http") and any(
            x in cell for x in ("userapi", "vkuseraudio", "sun", ".jpg", ".png", ".jpeg", ".webp")
        ):
            return cell
        if isinstance(cell, dict):
            cover = _cover_from_thumb_dict(cell)
            if cover:
                return cover
    return None


def _meta_from_vk_item(item: dict[str, Any], *, user_id: int | None = None) -> dict[str, Any] | None:
    raw_url = item.get("url") or ""
    url = _finalize_audio_url(str(raw_url), user_id) if raw_url else None
    if not url and not item.get("id"):
        return None
    artist = str(item.get("artist") or "")
    title = str(item.get("title") or "track")
    album_obj = item.get("album") if isinstance(item.get("album"), dict) else None
    album = str(album_obj.get("title") or "") if album_obj else ""
    owner_id = item.get("owner_id")
    aid = item.get("id")
    page_url = ""
    if owner_id is not None and aid is not None:
        page_url = f"https://vk.com/audio{owner_id}_{aid}"
    return {
        "url": url or "",
        "artist": artist,
        "title": title,
        "album": album,
        "duration": item.get("duration"),
        "cover": _cover_from_vk_item(item),
        "label": _track_label(artist, title),
        "owner_id": owner_id,
        "id": aid,
        "page_url": page_url,
    }


def _track_label(artist: str, title: str) -> str:
    artist = (artist or "").strip()
    title = (title or "track").strip()
    if artist and title:
        return f"{artist} — {title}"
    return title or artist or "track"


def _split_audio_id(audio_id: str) -> tuple[str, str] | None:
    m = _AUDIO_ID_RE.match(audio_id.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def _is_user_library_copy(audio_id: str) -> bool:
    parts = _split_audio_id(audio_id)
    if not parts:
        return False
    try:
        return int(parts[0]) > 0
    except ValueError:
        return False


def _reload_id_from_track_array(track: list) -> str | None:
    if not isinstance(track, list) or len(track) < 2:
        return None
    # VK mobile list: [audio_id, owner_id, url, title, artist, duration, ...]
    audio_id, owner_id = track[0], track[1]
    if len(track) > 13 and isinstance(track[13], str):
        parts = track[13].split("/")
        h3 = parts[2] if len(parts) > 2 else ""
        h6 = parts[5] if len(parts) > 5 else ""
        if h3 and h6:
            return f"{owner_id}_{audio_id}_{h3}_{h6}"
    return f"{owner_id}_{audio_id}"


def _user_id_from_payload(payload: dict[str, Any] | None) -> int | None:
    if not payload:
        return None
    meta = payload.get("statsMeta") or {}
    uid = meta.get("id")
    try:
        return int(uid) if uid is not None else None
    except (TypeError, ValueError):
        return None


def _finalize_audio_url(url: str, user_id: int | None) -> str | None:
    url = html.unescape(url.strip())
    if not url.startswith("http"):
        return None
    if "audio_api_unavailable" in url or "?extra=" in url:
        if user_id is None:
            _set_last_error("Не удалось расшифровать ссылку VK Music (нет user_id)")
            return None
        try:
            from media_core.vk_audio_decode import VkAudioUrlDecodeError, decode_audio_url

            url = decode_audio_url(url, user_id)
        except VkAudioUrlDecodeError as e:
            log.warning("vk audio decode failed: %s", e)
            _set_last_error("Не удалось расшифровать ссылку VK Music")
            return None
    if "m3u8" in url:
        url = _M3U8_TO_MP3_RE.sub(r"\1/\2.mp3", url)
    return url


def _track_info_from_mobile_array(track: list, *, user_id: int | None = None) -> dict[str, Any] | None:
    if not isinstance(track, list) or len(track) < 5:
        return None
    url = track[2] if len(track) > 2 else None
    if not url or not str(url).startswith("http"):
        return None
    url = _finalize_audio_url(str(url), user_id)
    if not url:
        return None
    title = str(track[3] if len(track) > 3 else "track")
    artist = str(track[4] if len(track) > 4 else "")
    duration_raw = track[5] if len(track) > 5 else None
    duration = int(duration_raw) if str(duration_raw).isdigit() else None
    return {
        "url": url,
        "artist": artist,
        "title": title,
        "duration": duration,
        "cover": _cover_from_track_array(track),
        "label": _track_label(artist, title),
    }


def _track_info_from_al_array(track: list, *, user_id: int | None = None) -> dict[str, Any] | None:
    if not isinstance(track, list) or len(track) < 7:
        return None
    url = track[6]
    if not url or not str(url).startswith("http"):
        return None
    url = _finalize_audio_url(str(url), user_id)
    if not url:
        return None
    artist = str(track[3] or "")
    title = str(track[4] or "track")
    duration_raw = track[5]
    duration = int(duration_raw) if str(duration_raw).isdigit() else None
    return {
        "url": url,
        "artist": artist,
        "title": title,
        "duration": duration,
        "cover": _cover_from_track_array(track),
        "label": _track_label(artist, title),
    }


def _is_bad_hash_payload(data: dict[str, Any]) -> bool:
    payload = data.get("payload")
    if not isinstance(payload, list) or len(payload) < 2:
        return False
    audios = payload[1]
    if not isinstance(audios, list) or not audios:
        return False
    first = audios[0]
    if first == "bad_hash":
        return True
    if isinstance(first, str) and "bad_hash" in first:
        return True
    return False


def _parse_json_array(text: str, start: int) -> list | None:
    if start >= len(text) or text[start] != "[":
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(start, min(len(text), start + 12000)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    val = json.loads(text[start:j + 1])
                except json.JSONDecodeError:
                    return None
                return val if isinstance(val, list) else None
    return None


def _extract_reload_id_from_html(page_html: str, owner_id: str, track_id: str) -> str | None:
    oid = int(owner_id)
    tid = int(track_id)
    for match in _DATA_AUDIO_RE.finditer(page_html):
        raw = html.unescape(match.group(1))
        try:
            arr = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(arr, list) or len(arr) < 2:
            continue
        if arr[0] == tid and arr[1] == oid:
            return _reload_id_from_track_array(arr)
        if arr[0] == oid and arr[1] == tid:
            return _reload_id_from_track_array([arr[1], arr[0], *arr[2:]])

    for prefix in (f"[{track_id},{owner_id},", f"[{owner_id},{track_id},"):
        i = 0
        while i < len(page_html):
            idx = page_html.find(prefix, i)
            if idx == -1:
                break
            arr = _parse_json_array(page_html, idx)
            if isinstance(arr, list) and len(arr) >= 2:
                if arr[0] == tid and arr[1] == oid:
                    reload_id = _reload_id_from_track_array(arr)
                elif arr[0] == oid and arr[1] == tid:
                    reload_id = _reload_id_from_track_array([arr[1], arr[0], *arr[2:]])
                else:
                    reload_id = None
                if reload_id and reload_id != f"{owner_id}_{track_id}":
                    return reload_id
            i = idx + len(prefix)
    return None


async def _reload_id_from_load_section(
    client: httpx.AsyncClient,
    cookies: str,
    owner_id: str,
    track_id: str,
    *,
    include_cookie: bool = True,
) -> str | None:
    """Hash для reload_audio из плейлиста владельца (m.vk.ru/audio)."""
    try:
        owner = int(owner_id)
        tid = int(track_id)
    except ValueError:
        return None

    headers = _vk_headers(
        cookies, "https://m.vk.ru/audio", mobile=True, include_cookie=include_cookie
    )
    await client.get("https://m.vk.ru/audio", headers=headers)
    offset = 0
    for _ in range(8):
        data = {
            "act": "load_section",
            "owner_id": owner,
            "playlist_id": -1,
            "offset": offset,
            "type": "playlist",
            "access_hash": "",
            "is_loading_all": 1,
        }
        r = await client.post("https://m.vk.ru/audio", data=data, headers=headers)
        try:
            payload = r.json()
        except Exception:
            return None
        block = (payload.get("data") or [None])[0]
        if block is False:
            return None
        if not isinstance(block, dict):
            return None
        lst = block.get("list") or []
        for item in lst:
            if not isinstance(item, list) or len(item) < 2:
                continue
            try:
                if int(item[0]) != tid:
                    continue
            except (TypeError, ValueError):
                continue
            reload_id = _reload_id_from_track_array(item)
            if reload_id:
                log.info(
                    "vk audio: hash from load_section owner=%s track=%s",
                    owner_id,
                    track_id,
                )
                return reload_id
        if not block.get("hasMore"):
            break
        offset += len(lst) or 2000
    return None


def _candidate_page_urls(source_url: str | None, audio_id: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        if url and url not in seen:
            seen.add(url)
            out.append(url)

    if source_url:
        add(source_url.strip())
        if "vk.ru" in source_url:
            add(source_url.replace("vk.ru", "vk.com"))
        if "vk.com" in source_url:
            add(source_url.replace("vk.com", "vk.ru"))

    for domain in ("https://vk.ru", "https://vk.com", "https://m.vk.ru"):
        add(f"{domain}/audio{audio_id}")

    return out


def _vk_headers(
    cookies: str | None,
    referer: str,
    *,
    mobile: bool = False,
    include_cookie: bool = True,
) -> dict[str, str]:
    headers = {
        "User-Agent": _MOBILE_USER_AGENT if mobile else _USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
        "Accept": "*/*",
    }
    if include_cookie and cookies:
        headers["Cookie"] = cookies
    return headers


async def fetch_vk_audio_info(audio_id: str, *, source_url: str | None = None) -> dict[str, Any] | None:
    """Метаданные и прямая ссылка на mp3.

    Важно: web-token + api.vk.com часто даёт
    «access_token was given to another ip address» — сначала cookies/al_audio.
    """
    _set_last_error(None)

    if load_vk_cookies() or load_vk_cookie_jar_safe():
        track = await _fetch_via_al_audio(audio_id, source_url=source_url)
        if track and track.get("url"):
            return track

    if VK_ACCESS_TOKEN:
        # Только явный токен из .env (не web_token из cookies)
        track = await _fetch_via_api(audio_id)
        if track and track.get("url"):
            return track
    return None


def load_vk_cookie_jar_safe():
    try:
        from media_core.config import load_vk_cookie_jar

        return load_vk_cookie_jar()
    except Exception:
        return None


async def _fetch_session_from_feed(client: httpx.AsyncClient, cookies: str) -> tuple[str | None, int | None]:
    """Токен сессии: login.vk.ru web_token, иначе парсинг vk.ru/feed."""
    headers = {
        "User-Agent": _USER_AGENT,
        "Cookie": cookies,
        "Referer": "https://vk.ru/",
        "Origin": "https://vk.ru",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/plain, */*",
    }
    # Современный путь: web app token (как у VK Web)
    for login_host in ("https://login.vk.ru/?act=web_token", "https://login.vk.com/?act=web_token"):
        try:
            r = await client.post(
                login_host,
                headers=headers,
                content="version=1&app_id=6287487",
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if data.get("type") != "okay":
                log.info(
                    "vk web_token %s: %s",
                    login_host,
                    data.get("error_info") or data.get("type") or r.text[:200],
                )
                continue
            payload = data.get("data") or {}
            token = payload.get("access_token")
            uid = payload.get("user_id")
            if token:
                try:
                    uid_i = int(uid) if uid is not None else None
                except (TypeError, ValueError):
                    uid_i = None
                if uid_i is None:
                    uid_i = await _fetch_vk_user_id(client, cookies)
                return str(token), uid_i
        except Exception as e:
            log.warning("vk web_token failed %s: %s", login_host, e)

    # Fallback: старый embed token со страницы ленты
    try:
        r = await client.get(
            "https://vk.ru/feed",
            headers={
                "User-Agent": _USER_AGENT,
                "Cookie": cookies,
                "Referer": "https://vk.ru/",
            },
        )
        if r.status_code != 200:
            r = await client.get(
                "https://vk.com/feed",
                headers={
                    "User-Agent": _USER_AGENT,
                    "Cookie": cookies,
                    "Referer": "https://vk.com/",
                },
            )
        if r.status_code != 200:
            return None, None
        m = _VK1_TOKEN_RE.search(r.text)
        token = m.group(1) if m else None
        uid = await _fetch_vk_user_id(client, cookies)
        return token, uid
    except Exception as e:
        log.warning("vk feed token fetch failed: %s", e)
        return None, None


async def _mark_access_denied_if_invisible(
    client: httpx.AsyncClient,
    cookies: str,
    audio_id: str,
    source_url: str | None,
) -> None:
    """Страница трека без hash — обычно нет доступа у аккаунта cookies."""
    parts = _split_audio_id(audio_id)
    if not parts:
        return
    owner_id, track_id = parts
    for page_url in _candidate_page_urls(source_url, audio_id)[:4]:
        try:
            r = await client.get(page_url, headers=_vk_headers(cookies, page_url))
            if r.status_code != 200 or not r.text:
                continue
            if _extract_reload_id_from_html(r.text, owner_id, track_id):
                return
            text = r.text
            if _PRIVATE_PAGE_RE.search(text) or (
                track_id in text and not _DATA_AUDIO_RE.search(text)
            ):
                _set_last_error(_access_denied_message(audio_id))
                log.info("vk audio: access denied for %s", audio_id)
                return
        except Exception as e:
            log.warning("vk audio access check failed %s: %s", page_url, e)
    if _is_user_library_copy(audio_id):
        _set_last_error(_access_denied_message(audio_id))
        return
    _set_last_error(
        "VK Music: нет доступа к аудио (трек недоступен аккаунту бота или удалён)"
    )


def _access_denied_message(audio_id: str) -> str:
    if _is_user_library_copy(audio_id):
        return (
            "VK Music: ссылка на личную копию трека в музыке пользователя "
            "(закрытый плейлист). Попроси скинуть ссылку на оригинал — "
            "из сообщества (audio-200...) или из поиска VK Music."
        )
    return (
        "VK Music: нет доступа к аудио (приватная запись или закрыто для аккаунта бота)"
    )


async def _fetch_via_web_api(audio_id: str, *, source_url: str | None = None) -> dict[str, Any] | None:
    """audio.getById через access_token со страницы vk.ru/feed."""
    cookies = load_vk_cookies()
    if not cookies:
        return None
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, trust_env=False, proxy=httpx_proxy(force_direct=True)) as client:
        token, user_id = await _fetch_session_from_feed(client, cookies)
        if not token:
            log.warning("vk web api: no access_token on /feed")
            return None
        try:
            r = await client.get(
                "https://api.vk.com/method/audio.getById",
                params={"audios": audio_id, "access_token": token, "v": VK_API_VERSION},
            )
            data = r.json()
        except Exception as e:
            log.warning("vk web api request failed: %s", e)
            return None
        if "error" in data:
            err = data["error"]
            log.warning("vk web api error: %s", err)
            _set_last_error(f"VK API: {err.get('error_msg', err)}")
            return None
        items = data.get("response") or []
        if not items:
            await _mark_access_denied_if_invisible(client, cookies, audio_id, source_url)
            return None
        item = items[0]
        meta = _meta_from_vk_item(item, user_id=user_id)
        if not meta or not meta.get("url"):
            if not item.get("url"):
                await _mark_access_denied_if_invisible(client, cookies, audio_id, source_url)
            return None
        return meta


async def _fetch_via_api(audio_id: str) -> dict[str, Any] | None:
    params = {
        "audios": audio_id,
        "access_token": VK_ACCESS_TOKEN,
        "v": VK_API_VERSION,
    }
    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False, proxy=httpx_proxy(force_direct=True)) as client:
            r = await client.get("https://api.vk.com/method/audio.getById", params=params)
            data = r.json()
    except Exception as e:
        log.warning("vk audio api request failed: %s", e)
        return None

    if "error" in data:
        err = data["error"]
        log.warning("vk audio api error: %s", err)
        _set_last_error(f"VK API: {err.get('error_msg', err)}")
        return None

    items = data.get("response") or []
    if not items:
        return None

    item = items[0]
    meta = _meta_from_vk_item(item)
    if not meta or not meta.get("url"):
        _set_last_error("VK не отдал ссылку на трек (нет доступа или трек удалён)")
        return None
    meta["url"] = html.unescape(meta["url"])
    return meta


def _parse_al_audio_payload(data: dict[str, Any], *, user_id: int | None = None) -> dict[str, Any] | None:
    if _is_bad_hash_payload(data):
        _set_last_error("VK не принял id трека (bad_hash) — нужны hash-параметры со страницы")
        return None

    payload = data.get("payload")
    if not isinstance(payload, list) or len(payload) < 2:
        return None

    audios = payload[1]
    if not isinstance(audios, list) or not audios:
        return None

    first = audios[0]
    if not isinstance(first, list):
        return None

    return _track_info_from_al_array(first, user_id=user_id)


def _parse_mobile_reload_payload(data: dict[str, Any], *, user_id: int | None = None) -> dict[str, Any] | None:
    rows = data.get("data")
    if not isinstance(rows, list) or not rows:
        return None
    block = rows[0]
    if not isinstance(block, list) or not block:
        return None
    first = block[0]
    if not isinstance(first, list):
        return None
    return _track_info_from_mobile_array(first, user_id=user_id)


async def _resolve_reload_id(
    client: httpx.AsyncClient,
    cookies: str,
    audio_id: str,
    source_url: str | None,
    *,
    include_cookie: bool = True,
) -> str:
    parts = _split_audio_id(audio_id)
    if not parts:
        return audio_id
    owner_id, track_id = parts

    for page_url in _candidate_page_urls(source_url, audio_id):
        try:
            host = urlparse(page_url).netloc or "vk.ru"
            referer = f"https://{host}/"
            r = await client.get(
                page_url,
                headers=_vk_headers(cookies, referer, mobile=True, include_cookie=include_cookie),
            )
            if r.status_code != 200 or not r.text:
                continue
            reload_id = _extract_reload_id_from_html(r.text, owner_id, track_id)
            if reload_id and reload_id != f"{owner_id}_{track_id}":
                log.info("vk audio: resolved reload id from %s", page_url)
                return reload_id
        except Exception as e:
            log.warning("vk audio page fetch failed %s: %s", page_url, e)

    section_id = await _reload_id_from_load_section(
        client, cookies, owner_id, track_id, include_cookie=include_cookie
    )
    if section_id:
        return section_id

    return audio_id


async def _post_reload_audio(
    client: httpx.AsyncClient,
    cookies: str | None,
    reload_id: str,
    endpoint: str,
    referer: str,
    *,
    include_cookie: bool = True,
    mobile: bool = True,
) -> dict[str, Any] | None:
    headers = _vk_headers(cookies, referer, mobile=mobile, include_cookie=include_cookie)
    data = {"act": "reload_audio", "ids": reload_id, "al": "1"}
    try:
        r = await client.post(endpoint, data=data, headers=headers)
        if not r.text:
            return None
        text = r.text.lstrip()
        if text.startswith("{"):
            return r.json()
        i = text.find("{")
        if i >= 0:
            return json.loads(text[i:])
    except Exception as e:
        log.warning("vk reload_audio failed %s: %s", endpoint, e)
    return None


async def _fetch_vk_user_id(
    client: httpx.AsyncClient,
    cookies: str,
    *,
    include_cookie: bool = True,
) -> int | None:
    """user_id из сессии: reload_audio statsMeta → HTML (без api.vk.com)."""
    headers = _vk_headers(cookies, "https://m.vk.ru/", mobile=True, include_cookie=include_cookie)
    try:
        r = await client.post(
            "https://m.vk.ru/audio",
            data={"act": "reload_audio", "ids": "0_0"},
            headers=headers,
        )
        uid = _user_id_from_payload(r.json())
        if uid:
            return uid
    except Exception as e:
        log.warning("vk user_id reload_audio failed: %s", e)

    patterns = (
        re.compile(r"\bvk\.id\s*=\s*(\d{3,12})\b"),
        re.compile(r'["\']user_id["\']\s*:\s*(\d{3,12})'),
        re.compile(r"user_id[\"'=:\s]+(\d{3,12})", re.I),
        re.compile(r"/audios(\d{3,12})"),
        re.compile(r'href="/id(\d{3,12})"'),
    )
    for url in (
        "https://m.vk.ru/audio",
        "https://m.vk.ru/",
        "https://vk.ru/feed",
        "https://vk.com/feed",
    ):
        try:
            r = await client.get(
                url,
                headers=_vk_headers(cookies, url, mobile=True, include_cookie=include_cookie),
            )
            text = r.text or ""
            for pat in patterns:
                m = pat.search(text)
                if not m:
                    continue
                try:
                    uid = int(m.group(1))
                except ValueError:
                    continue
                if uid > 0:
                    return uid
        except Exception as e:
            log.debug("vk user_id page %s failed: %s", url, e)

    # web_token только для uid, не для api.vk.com
    if include_cookie and cookies:
        try:
            _token, uid = await _fetch_session_from_feed(client, cookies)
            if uid:
                return uid
        except Exception as e:
            log.warning("vk user_id web_token failed: %s", e)
    return None


async def _fetch_via_al_audio(audio_id: str, *, source_url: str | None = None) -> dict[str, Any] | None:
    from media_core.config import load_vk_cookie_jar, load_vk_cookies_for

    jar = load_vk_cookie_jar()
    cookies = load_vk_cookies_for("m.vk.ru", ".vk.ru", "vk.ru") or load_vk_cookies()
    if not jar and not cookies:
        return None

    use_jar = jar is not None
    client_headers: dict[str, str] = {
        "User-Agent": _MOBILE_USER_AGENT,
        "Accept": "*/*",
    }
    if not use_jar and cookies:
        client_headers["Cookie"] = cookies

    async with httpx.AsyncClient(
        timeout=35,
        follow_redirects=True,
        trust_env=False,
        headers=client_headers,
        cookies=jar,
        proxy=httpx_proxy(force_direct=True),
    ) as client:
        vk_user_id = await _fetch_vk_user_id(
            client, cookies or "", include_cookie=not use_jar
        )
        reload_id = await _resolve_reload_id(
            client,
            cookies or "",
            audio_id,
            source_url,
            include_cookie=not use_jar,
        )
        if not reload_id:
            return None

        endpoints = (
            ("https://m.vk.ru/audio", "https://m.vk.ru/audio", True),
            ("https://vk.ru/al_audio.php", "https://vk.ru/audios", False),
            ("https://vk.com/al_audio.php", "https://vk.com/audios", False),
        )
        tried: set[str] = {reload_id}
        candidates = [reload_id]
        bare = (
            f"{_split_audio_id(audio_id)[0]}_{_split_audio_id(audio_id)[1]}"
            if _split_audio_id(audio_id)
            else audio_id
        )
        if bare not in tried:
            candidates.append(bare)

        for candidate in candidates:
            for endpoint, referer, mobile in endpoints:
                payload = await _post_reload_audio(
                    client,
                    cookies,
                    candidate,
                    endpoint,
                    referer,
                    include_cookie=not use_jar,
                    mobile=mobile,
                )
                if not payload:
                    continue
                if endpoint.endswith("/audio"):
                    track = _parse_mobile_reload_payload(payload, user_id=vk_user_id)
                else:
                    track = _parse_al_audio_payload(payload, user_id=vk_user_id)
                if track and track.get("url"):
                    _set_last_error(None)
                    return track
                if payload and _is_bad_hash_payload(payload):
                    log.warning("vk audio bad_hash for %s via %s", candidate, endpoint)

        if _last_download_error is None or "bad_hash" in str(_last_download_error).lower():
            await _mark_access_denied_if_invisible(client, cookies or "", audio_id, source_url)
    return None


def _is_hls_url(url: str) -> bool:
    u = url.lower()
    return ".m3u8" in u or "mpegurl" in u


def _ffmpeg_request_headers(cookies: str) -> str:
    lines = [
        "Referer: https://vk.ru/audios",
        f"User-Agent: {_USER_AGENT}",
    ]
    if cookies:
        lines.append(f"Cookie: {cookies}")
    return "\r\n".join(lines) + "\r\n"


def _download_hls_via_ffmpeg_sync(
    hls_url: str,
    dest_path: str,
    cookies: str,
    cancel_event: threading.Event | None,
) -> str | None:
    if cancel_event is not None and cancel_event.is_set():
        return None
    # Всегда .mp3 на выходе — иначе ffmpeg не угадает формат (как с *.part)
    out = dest_path
    if not out.lower().endswith(".mp3"):
        out = dest_path + ".mp3"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-headers", _ffmpeg_request_headers(cookies),
        "-i", hls_url,
        "-vn", "-acodec", "libmp3lame", "-q:a", "2",
        "-f", "mp3",
        out,
    ]
    try:
        from media_core.utils import subprocess_no_window_kwargs

        subprocess.run(
            cmd, check=True, capture_output=True, timeout=300, **subprocess_no_window_kwargs()
        )
        if os.path.isfile(out) and os.path.getsize(out) > 32_000:
            if out != dest_path:
                try:
                    os.replace(out, dest_path)
                except OSError:
                    return out
            return dest_path if os.path.isfile(dest_path) else out
        _set_last_error("VK HLS: получен слишком маленький файл после конвертации")
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode(errors="replace")[:300]
        log.warning("vk hls ffmpeg failed: %s", err)
        _set_last_error("ffmpeg: не удалось собрать трек из HLS")
    except Exception as e:
        log.warning("vk hls ffmpeg failed: %s", e)
        _set_last_error(e)
    for p in {dest_path, out}:
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass
    return None


async def _download_mp3(
    mp3_url: str,
    dest_path: str,
    cancel_event: threading.Event | None,
    *,
    cookies: str = "",
) -> str | None:
    if _is_hls_url(mp3_url):
        return await asyncio.to_thread(
            _download_hls_via_ffmpeg_sync, mp3_url, dest_path, cookies, cancel_event,
        )

    headers = {
        "User-Agent": _USER_AGENT,
        "Referer": "https://vk.ru/audios",
    }
    if cookies:
        headers["Cookie"] = cookies

    def _sync() -> str | None:
        if cancel_event is not None and cancel_event.is_set():
            return None
        try:
            with httpx.Client(timeout=120, follow_redirects=True, trust_env=False, proxy=httpx_proxy(force_direct=True)) as client:
                with client.stream("GET", mp3_url, headers=headers) as resp:
                    resp.raise_for_status()
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if "mpegurl" in ctype or mp3_url.lower().endswith(".m3u8"):
                        return _download_hls_via_ffmpeg_sync(
                            mp3_url, dest_path, cookies, cancel_event,
                        )
                    with open(dest_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=65536):
                            if cancel_event is not None and cancel_event.is_set():
                                return None
                            if chunk:
                                f.write(chunk)
            if os.path.isfile(dest_path):
                size = os.path.getsize(dest_path)
                if size > 0:
                    with open(dest_path, "rb") as f:
                        head = f.read(16)
                    if head.startswith(b"#EXTM3U"):
                        # CDN отдал плейлист вместо mp3 — собираем через ffmpeg из файла
                        pl = dest_path + ".m3u8"
                        try:
                            os.replace(dest_path, pl)
                        except OSError:
                            pl = dest_path
                        got = _download_hls_via_ffmpeg_sync(
                            pl, dest_path if pl != dest_path else dest_path + ".out.mp3",
                            cookies, cancel_event,
                        )
                        if pl != dest_path and os.path.isfile(pl):
                            try:
                                os.remove(pl)
                            except OSError:
                                pass
                        if got and os.path.isfile(got):
                            if got != dest_path:
                                try:
                                    os.replace(got, dest_path)
                                    return dest_path
                                except OSError:
                                    return got
                            return dest_path
                        return None
                    if size < 4096:
                        try:
                            os.remove(dest_path)
                        except OSError:
                            pass
                        # попробуем угадать HLS-URL от «фейкового» .mp3
                        for cand in _hls_url_guesses(mp3_url):
                            got = _download_hls_via_ffmpeg_sync(
                                cand, dest_path, cookies, cancel_event,
                            )
                            if got:
                                return got
                        return _download_hls_via_ffmpeg_sync(
                            mp3_url, dest_path, cookies, cancel_event,
                        )
                    return dest_path
        except Exception as e:
            log.warning("vk audio download failed: %s", e)
            _set_last_error(e)
        if os.path.isfile(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        return None

    return await asyncio.to_thread(_sync)


def _hls_url_guesses(url: str) -> list[str]:
    """Если из m3u8 сделали *.mp3 — попробуем вернуть index.m3u8."""
    u = (url or "").strip()
    if not u:
        return []
    out: list[str] = []
    low = u.lower()
    if ".mp3" in low:
        base, _, q = u.partition(".mp3")
        suffix = q if q.startswith("?") else ""
        out.append(f"{base}/index.m3u8{suffix}")
        # .../audios/ID.mp3 → .../ID/index.m3u8 уже выше; иногда нужен без query
        out.append(f"{base}/index.m3u8")
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


async def download_vk_audio(url: str, cancel_event: threading.Event | None = None) -> str | None:
    """Скачивает один трек VK Music в mp3."""
    from media_core.constants import CANCELLED

    if cancel_event is not None and cancel_event.is_set():
        return CANCELLED

    audio_id = parse_vk_audio_id(url)
    if not audio_id:
        _set_last_error("Некорректная ссылка VK Music")
        return None

    if not vk_audio_configured():
        _set_last_error(
            "VK Music не настроен. Положи cookies в vk_cookies.txt или задай VK_COOKIES в .env"
        )
        return None

    info = await fetch_vk_audio_info(audio_id, source_url=url)
    if not info or not info.get("url"):
        if _last_download_error is None:
            _set_last_error("Не удалось получить трек. Проверь доступность записи.")
        return None

    filename = safe_filename(info["label"], ".mp3")
    path = await _download_mp3(info["url"], filename, cancel_event, cookies=load_vk_cookies())
    if path is None and cancel_event is not None and cancel_event.is_set():
        return CANCELLED
    if not path:
        if _last_download_error is None:
            _set_last_error("Не удалось скачать mp3")
        return None
    try:
        from media_core.media_tags import tag_mp3

        tag_mp3(
            path,
            title=info.get("title"),
            artist=info.get("artist"),
            album=info.get("album"),
            cover_url=info.get("cover"),
        )
    except Exception as e:
        log.warning("vk tag failed: %s", e)
    _set_last_vk_track_meta(info, url)
    return path
