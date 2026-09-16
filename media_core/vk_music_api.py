"""Аудиозаписи ВКонтакте (vk.ru/audio), не подписка music.vk.com.

Список «Моя музыка» и плейлистов через m.vk.ru + cookies — без api.vk.com.
"""

from __future__ import annotations

import html
import re
from typing import Any

import httpx

from media_core.config import load_vk_cookie_jar, load_vk_cookies, load_vk_cookies_for
from media_core.download_vk_audio import (
    _fetch_vk_user_id,
    _track_label,
    _vk_headers,
)
from media_core.logging_setup import log
from media_core.utils import fmt_time, vk_audio_configured

_ALBUM_HREF_RE = re.compile(
    r'href="/audio\?act=audio_playlist(-?\d+)_(\d+)(?:[^"]*&access_hash=([\w]+))?"',
    re.I,
)
_ALBUM_TITLE_RE = re.compile(
    r"audioPlaylists__itemTitle[^>]*>(.*?)</(?:a|div|span)>",
    re.I | re.S,
)
_USER_ID_RE = re.compile(r'"id"\s*:\s*(\d{2,12})')
_USER_NAME_RE = re.compile(
    r'class="[^"]*(?:OwnerPageName|page_name|op_header)[^"]*"[^>]*>(.*?)<',
    re.I | re.S,
)


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def _mobile_client(cookies_header: str | None = None) -> httpx.AsyncClient:
    from media_core.net_proxy import httpx_client_kwargs

    jar = load_vk_cookie_jar()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        ),
        "Accept": "*/*",
    }
    # Если jar нет — fallback на Cookie header без дублей
    if jar is None and cookies_header:
        headers["Cookie"] = cookies_header
    return httpx.AsyncClient(
        **httpx_client_kwargs(
            force_direct=True,
            timeout=45,
            follow_redirects=True,
            headers=headers,
            cookies=jar,
        )
    )


def _req_headers(referer: str, cookies_header: str | None, *, use_jar: bool) -> dict[str, str]:
    return _vk_headers(
        None if use_jar else (cookies_header or ""),
        referer,
        mobile=True,
        include_cookie=not use_jar,
    )


def _track_from_list_item(item: list) -> dict[str, Any] | None:
    """Элемент list из m.vk.ru act=load_section."""
    if not isinstance(item, list) or len(item) < 5:
        return None
    try:
        aid = int(item[0])
        oid = int(item[1])
    except (TypeError, ValueError):
        return None
    title = _clean_text(str(item[3] if len(item) > 3 else "track")) or "track"
    artist = _clean_text(str(item[4] if len(item) > 4 else ""))
    duration_raw = item[5] if len(item) > 5 else None
    try:
        dur_n = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        dur_n = None
    cover = ""
    for idx in (14, 12, 11, 8):
        if len(item) > idx and isinstance(item[idx], str) and item[idx].startswith("http"):
            cover = item[idx]
            break
        if len(item) > idx and isinstance(item[idx], dict):
            thumb = item[idx]
            for key in ("photo_1200", "photo_600", "photo_300", "url"):
                if isinstance(thumb.get(key), str) and thumb[key].startswith("http"):
                    cover = thumb[key]
                    break
            if cover:
                break
    page_url = f"https://vk.com/audio{oid}_{aid}"
    return {
        "id": f"{oid}_{aid}",
        "title": title,
        "artist": artist,
        "album": "",
        "label": _track_label(artist, title),
        "duration": dur_n,
        "duration_label": fmt_time(dur_n) if dur_n else "",
        "url": page_url,
        "cover": cover,
    }


async def _resolve_user(client: httpx.AsyncClient, cookies: str, *, use_jar: bool) -> tuple[int | None, str]:
    cookies_m = load_vk_cookies_for("m.vk.ru", ".vk.ru", "vk.ru") or cookies
    uid = await _fetch_vk_user_id_jaraware(client, cookies_m, use_jar=use_jar)
    name = ""
    headers = _req_headers("https://m.vk.ru/", cookies_m, use_jar=use_jar)
    try:
        r = await client.get("https://m.vk.ru/", headers=headers)
        text = r.text or ""
        if uid is None:
            for pat in (
                _USER_ID_RE,
                re.compile(r"\bvk\.id\s*=\s*(\d{3,12})\b"),
                re.compile(r"/audios(\d{3,12})"),
            ):
                m = pat.search(text)
                if m:
                    try:
                        uid = int(m.group(1))
                        break
                    except ValueError:
                        pass
        nm = _USER_NAME_RE.search(text)
        if nm:
            name = _clean_text(nm.group(1))
    except Exception as e:
        log.warning("vk resolve user failed: %s", e)
    if not name and uid:
        name = str(uid)
    return uid, name


async def _fetch_vk_user_id_jaraware(
    client: httpx.AsyncClient,
    cookies: str,
    *,
    use_jar: bool,
) -> int | None:
    headers = _req_headers("https://m.vk.ru/", cookies, use_jar=use_jar)
    try:
        r = await client.post(
            "https://m.vk.ru/audio",
            data={"act": "reload_audio", "ids": "0_0"},
            headers=headers,
        )
        from media_core.download_vk_audio import _user_id_from_payload

        uid = _user_id_from_payload(r.json())
        if uid:
            return uid
    except Exception as e:
        log.warning("vk user_id reload_audio failed: %s", e)

    # fallback на общий резолвер (с Cookie header)
    if not use_jar:
        return await _fetch_vk_user_id(client, cookies)
    # с jar: HTML
    for url in ("https://m.vk.ru/audio", "https://m.vk.ru/", "https://vk.ru/feed"):
        try:
            r = await client.get(url, headers=_req_headers(url, cookies, use_jar=True))
            text = r.text or ""
            for pat in (
                re.compile(r"\bvk\.id\s*=\s*(\d{3,12})\b"),
                re.compile(r'["\']user_id["\']\s*:\s*(\d{3,12})'),
                re.compile(r"/audios(\d{3,12})"),
            ):
                m = pat.search(text)
                if m:
                    return int(m.group(1))
        except Exception:
            continue
    return await _fetch_vk_user_id(client, cookies)


async def _load_section_list(
    client: httpx.AsyncClient,
    cookies: str,
    *,
    owner_id: int,
    playlist_id: int = -1,
    access_hash: str = "",
    limit: int = 1000,
    use_jar: bool = False,
) -> list[list]:
    cookies_m = load_vk_cookies_for("m.vk.ru", ".vk.ru", "vk.ru") or cookies
    headers = _req_headers("https://m.vk.ru/audio", cookies_m, use_jar=use_jar)
    await client.get("https://m.vk.ru/audio", headers=headers)
    offset = 0
    out: list[list] = []
    for _ in range(20):
        data = {
            "act": "load_section",
            "owner_id": owner_id,
            "playlist_id": playlist_id,
            "offset": offset,
            "type": "playlist",
            "access_hash": access_hash or "",
            "is_loading_all": 1,
        }
        r = await client.post("https://m.vk.ru/audio", data=data, headers=headers)
        try:
            payload = r.json()
        except Exception:
            break
        block = (payload.get("data") or [None])[0]
        if block is False or not isinstance(block, dict):
            log.info(
                "vk load_section empty owner=%s playlist=%s keys=%s type=%s",
                owner_id,
                playlist_id,
                list(payload.keys()) if isinstance(payload, dict) else None,
                payload.get("type") if isinstance(payload, dict) else None,
            )
            break
        lst = block.get("list") or []
        for item in lst:
            if isinstance(item, list):
                out.append(item)
                if len(out) >= limit:
                    return out
        if not block.get("hasMore"):
            break
        offset += len(lst) or 100
        if not lst:
            break
    return out


async def _list_playlists_html(
    client: httpx.AsyncClient,
    cookies: str,
    owner_id: int,
    *,
    use_jar: bool = False,
) -> list[dict]:
    cookies_m = load_vk_cookies_for("m.vk.ru", ".vk.ru", "vk.ru") or cookies
    headers = _req_headers("https://m.vk.ru/", cookies_m, use_jar=use_jar)
    items: list[dict] = []
    seen: set[str] = set()
    offset = 0
    for _ in range(10):
        url = f"https://m.vk.ru/audio?act=audio_playlists{owner_id}&offset={offset}"
        try:
            r = await client.get(url, headers=headers)
        except Exception as e:
            log.warning("vk playlists page failed: %s", e)
            break
        text = r.text or ""
        if not text:
            break
        hrefs = list(_ALBUM_HREF_RE.finditer(text))
        titles = list(_ALBUM_TITLE_RE.finditer(text))
        if not hrefs:
            break
        for i, m in enumerate(hrefs):
            oid, pid, access = m.group(1), m.group(2), m.group(3) or ""
            key = f"{oid}:{pid}"
            if key in seen:
                continue
            seen.add(key)
            title = _clean_text(titles[i].group(1)) if i < len(titles) else f"Плейлист {pid}"
            items.append(
                {
                    "id": key,
                    "kind": pid,
                    "uid": oid,
                    "title": title or f"Плейлист {pid}",
                    "track_count": None,
                    "is_likes": False,
                    "access_hash": access,
                }
            )
        if len(hrefs) < 20:
            break
        offset += 100
    return items


async def vk_account_status() -> dict:
    cookies = load_vk_cookies()
    jar = load_vk_cookie_jar()
    if not cookies and not jar:
        return {
            "ok": False,
            "configured": False,
            "error": "Нет cookies VK. Залогинься на vk.ru и отправь cookies через расширение",
        }
    if cookies and "remixsid=" not in cookies.lower() and jar is None:
        return {
            "ok": False,
            "configured": True,
            "error": "В cookies нет remixsid. Открой vk.ru в браузере и снова отправь cookies",
        }
    use_jar = jar is not None
    try:
        async with _mobile_client(cookies) as client:
            uid, name = await _resolve_user(client, cookies, use_jar=use_jar)
            if not uid:
                return {
                    "ok": False,
                    "configured": True,
                    "error": "Cookies не приняты. Открой vk.ru (не music.vk.com), обнови страницу и снова отправь cookies",
                }
            sample = await _load_section_list(
                client, cookies, owner_id=uid, limit=1, use_jar=use_jar
            )
            return {
                "ok": True,
                "configured": True,
                "login": name or str(uid),
                "uid": str(uid),
                "tracks_probe": len(sample),
            }
    except Exception as e:
        log.warning("vk status failed: %s", e)
        return {"ok": False, "configured": True, "error": str(e)}


async def list_vk_playlists() -> dict:
    if not vk_audio_configured():
        return {
            "ok": False,
            "error": "Нет cookies VK. Отправь cookies через расширение.",
            "items": [],
        }
    cookies = load_vk_cookies()
    use_jar = load_vk_cookie_jar() is not None
    try:
        async with _mobile_client(cookies) as client:
            uid, _name = await _resolve_user(client, cookies, use_jar=use_jar)
            if not uid:
                return {
                    "ok": False,
                    "error": "Не удалось определить аккаунт VK",
                    "items": [],
                }
            items: list[dict] = [
                {
                    "id": "my",
                    "kind": "my",
                    "uid": str(uid),
                    "title": "Моя музыка",
                    "track_count": None,
                    "is_likes": True,
                    "access_hash": "",
                }
            ]
            try:
                items.extend(
                    await _list_playlists_html(client, cookies, uid, use_jar=use_jar)
                )
            except Exception as e:
                log.warning("vk playlists list failed: %s", e)
            return {"ok": True, "items": items}
    except Exception as e:
        log.warning("vk playlists failed: %s", e)
        return {"ok": False, "error": str(e), "items": []}


async def list_vk_playlist_tracks(
    kind: str,
    *,
    uid: str | None = None,
    limit: int = 1000,
    access_hash: str = "",
) -> dict:
    if not vk_audio_configured():
        return {"ok": False, "error": "Нет cookies VK", "tracks": []}

    cookies = load_vk_cookies()
    use_jar = load_vk_cookie_jar() is not None
    kind = (kind or "my").strip()
    title = "Моя музыка"
    playlist_id = -1

    try:
        async with _mobile_client(cookies) as client:
            if uid and str(uid).strip().lstrip("-").isdigit():
                owner_id = int(uid)
            else:
                resolved, _ = await _resolve_user(client, cookies, use_jar=use_jar)
                if not resolved:
                    return {"ok": False, "error": "Не удалось определить аккаунт VK", "tracks": []}
                owner_id = resolved

            if kind not in ("my", "likes", ""):
                try:
                    playlist_id = int(kind)
                except ValueError:
                    return {"ok": False, "error": "Некорректный плейлист", "tracks": []}
                title = f"Плейлист {playlist_id}"

            raw = await _load_section_list(
                client,
                cookies,
                owner_id=owner_id,
                playlist_id=playlist_id,
                access_hash=access_hash or "",
                limit=max(1, min(2000, limit)),
                use_jar=use_jar,
            )
            tracks = []
            for item in raw:
                payload = _track_from_list_item(item)
                if payload:
                    tracks.append(payload)
            if not tracks and kind in ("my", "likes", ""):
                return {
                    "ok": False,
                    "error": "Список пуст: VK не отдал аудио (нужна мобильная сессия/обнови cookies на vk.ru)",
                    "tracks": [],
                    "title": title,
                }
            return {"ok": True, "title": title, "tracks": tracks, "count": len(tracks)}
    except Exception as e:
        log.warning("vk playlist tracks failed: %s", e)
        return {"ok": False, "error": str(e), "tracks": []}
