"""Яндекс Музыка через api.music.yandex.net."""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

from media_core.logging_setup import log
from media_core.download_state import current_download_state
from media_core.utils import safe_filename
from media_core.yandex_music_token import get_yandex_music_token

_ALBUM_TRACK_RE = re.compile(
    r"music\.yandex\.(?P<tld>ru|com|by|kz|uz|ua)/album/(?P<album_id>\d+)/track/(?P<track_id>\d+)",
    re.I,
)
_TRACK_ONLY_RE = re.compile(
    r"music\.yandex\.(?P<tld>ru|com|by|kz|uz|ua)/track/(?P<track_id>\d+)",
    re.I,
)


@dataclass
class YandexTrackRef:
    tld: str
    track_id: str
    album_id: str


@dataclass
class YandexTrackInfo:
    label: str
    artist: str
    title: str
    duration: float | None
    album: str | None = None
    cover_url: str | None = None


_last_track_meta: dict | None = None


def get_last_yandex_track_meta() -> dict | None:
    state = current_download_state()
    meta = state.get("yandex_meta") if state is not None else _last_track_meta
    return dict(meta) if meta else None


def _set_last_yandex_track_meta(info: YandexTrackInfo | None, url: str = "") -> None:
    global _last_track_meta
    meta = {
        "title": info.title,
        "artist": info.artist,
        "album": info.album,
        "duration": info.duration,
        "thumbnail": info.cover_url,
        "label": info.label,
        "url": url,
        "platform": "yandex_music",
    } if info else None
    state = current_download_state()
    if state is not None:
        state["yandex_meta"] = meta
    else:
        _last_track_meta = meta


def parse_yandex_track_url(url: str) -> YandexTrackRef | None:
    m = _ALBUM_TRACK_RE.search(url)
    if m:
        return YandexTrackRef(m.group("tld"), m.group("track_id"), m.group("album_id"))
    m = _TRACK_ONLY_RE.search(url)
    if m:
        return YandexTrackRef(m.group("tld"), m.group("track_id"), "")
    return None


def _track_key(ref: YandexTrackRef) -> str:
    if ref.album_id:
        return f"{ref.track_id}:{ref.album_id}"
    return ref.track_id


def track_page_url(track_id: str | int, album_id: str | int | None = None, tld: str = "ru") -> str:
    tid = str(track_id)
    if album_id:
        return f"https://music.yandex.{tld}/album/{album_id}/track/{tid}"
    return f"https://music.yandex.{tld}/track/{tid}"


def _artists_label(track) -> str:
    artists = getattr(track, "artists", None) or []
    names = [a.name for a in artists if getattr(a, "name", None)]
    return ", ".join(names)


def _fmt_dur(sec: float | None) -> str:
    if not sec:
        return ""
    m = int(sec) // 60
    s = int(sec) % 60
    return f"{m}:{s:02d}"


def _cover_url(track) -> str | None:
    cover_uri = getattr(track, "cover_uri", None) or getattr(track, "og_image", None)
    if not cover_uri or not isinstance(cover_uri, str):
        albums = getattr(track, "albums", None) or []
        if albums:
            cover_uri = getattr(albums[0], "cover_uri", None) or getattr(albums[0], "og_image", None)
    if not cover_uri or not isinstance(cover_uri, str):
        return None
    u = cover_uri.replace("%%", "1000x1000")
    if "%%" not in cover_uri and "/400x400" in u:
        u = u.replace("/400x400", "/1000x1000")
    if u.startswith("http"):
        return u
    return f"https://{u}"


def _track_info(track) -> YandexTrackInfo:
    title = (getattr(track, "title", None) or "Track").strip()
    artist = _artists_label(track)
    duration_ms = getattr(track, "duration_ms", None)
    duration = float(duration_ms) / 1000 if duration_ms else None
    album = None
    albums = getattr(track, "albums", None) or []
    if albums:
        album = getattr(albums[0], "title", None)
    label = f"{artist} — {title}" if artist else title
    return YandexTrackInfo(
        label=label,
        artist=artist,
        title=title,
        duration=duration,
        album=album,
        cover_url=_cover_url(track),
    )


def _track_payload(track, *, tld: str = "ru") -> dict | None:
    if track is None:
        return None
    real = getattr(track, "track", None) or track
    tid = getattr(real, "id", None) or getattr(track, "id", None)
    if tid is None:
        return None
    albums = getattr(real, "albums", None) or []
    album_id = getattr(albums[0], "id", None) if albums else None
    info = _track_info(real)
    return {
        "id": str(tid),
        "album_id": str(album_id) if album_id is not None else "",
        "title": info.title,
        "artist": info.artist,
        "album": info.album or "",
        "label": info.label,
        "duration": info.duration,
        "duration_label": _fmt_dur(info.duration),
        "url": track_page_url(tid, album_id, tld),
        "cover": info.cover_url or "",
    }


async def _get_client():
    from yandex_music import ClientAsync

    token = await get_yandex_music_token()
    if not token:
        return None
    client = ClientAsync(token)
    await client.init()
    return client


async def yandex_account_status() -> dict:
    client = await _get_client()
    if not client:
        return {"ok": False, "configured": False, "error": "Нет cookies / токена Яндекс Музыки"}
    try:
        me = getattr(client, "me", None)
        account = getattr(me, "account", None) if me else None
        login = getattr(account, "login", None) or getattr(account, "display_name", None) or ""
        uid = getattr(account, "uid", None) or getattr(client, "account_uid", None)
        return {"ok": True, "configured": True, "login": str(login or ""), "uid": str(uid or "")}
    except Exception as e:
        log.warning("yandex status failed: %s", e)
        return {"ok": False, "configured": True, "error": str(e)}


async def list_yandex_playlists() -> dict:
    client = await _get_client()
    if not client:
        return {
            "ok": False,
            "error": "Нет cookies Яндекс Музыки. Отправь cookies из расширения.",
            "items": [],
        }
    try:
        uid = getattr(client, "account_uid", None)
        playlists = await client.users_playlists_list()
        items = [{
            "id": "likes",
            "kind": "likes",
            "uid": str(uid or ""),
            "title": "Мне нравится",
            "track_count": None,
            "is_likes": True,
        }]
        for pl in playlists or []:
            kind = getattr(pl, "kind", None)
            if kind is None:
                continue
            items.append({
                "id": f"{getattr(pl, 'uid', uid)}:{kind}",
                "kind": str(kind),
                "uid": str(getattr(pl, "uid", None) or uid or ""),
                "title": (getattr(pl, "title", None) or f"Плейлист {kind}").strip(),
                "track_count": getattr(pl, "track_count", None),
                "is_likes": False,
            })
        return {"ok": True, "items": items}
    except Exception as e:
        log.warning("yandex playlists failed: %s", e)
        return {"ok": False, "error": str(e), "items": []}


async def list_yandex_likes_tracks(*, limit: int = 500) -> dict:
    client = await _get_client()
    if not client:
        return {"ok": False, "error": "Нет cookies Яндекс Музыки", "tracks": []}
    try:
        likes = await client.users_likes_tracks()
        if not likes:
            return {"ok": True, "title": "Мне нравится", "tracks": [], "count": 0}
        tracks = await likes.fetch_tracks_async()
        out = []
        for t in tracks or []:
            payload = _track_payload(t)
            if payload:
                out.append(payload)
            if len(out) >= limit:
                break
        return {"ok": True, "title": "Мне нравится", "tracks": out, "count": len(out)}
    except Exception as e:
        log.warning("yandex likes failed: %s", e)
        return {"ok": False, "error": str(e), "tracks": []}


async def list_yandex_playlist_tracks(kind: str, *, uid: str | None = None, limit: int = 1000) -> dict:
    if kind == "likes":
        return await list_yandex_likes_tracks(limit=limit)
    client = await _get_client()
    if not client:
        return {"ok": False, "error": "Нет cookies Яндекс Музыки", "tracks": []}
    try:
        pl = await client.users_playlists(int(kind) if str(kind).isdigit() else kind, user_id=uid or None)
        if isinstance(pl, list):
            pl = pl[0] if pl else None
        if not pl:
            return {"ok": False, "error": "Плейлист не найден", "tracks": []}
        title = (getattr(pl, "title", None) or f"Плейлист {kind}").strip()
        tracks = getattr(pl, "tracks", None)
        if not tracks and hasattr(pl, "fetch_tracks_async"):
            tracks = await pl.fetch_tracks_async()
        out = []
        for t in tracks or []:
            payload = _track_payload(t)
            if payload:
                out.append(payload)
            if len(out) >= limit:
                break
        return {"ok": True, "title": title, "kind": str(kind), "tracks": out, "count": len(out)}
    except Exception as e:
        log.warning("yandex playlist tracks failed: %s", e)
        return {"ok": False, "error": str(e), "tracks": []}


async def fetch_yandex_track_info(url: str) -> YandexTrackInfo | None:
    ref = parse_yandex_track_url(url)
    if not ref:
        return None
    client = await _get_client()
    if not client:
        return None
    try:
        tracks = await client.tracks(_track_key(ref))
        if not tracks:
            return None
        return _track_info(tracks[0])
    except Exception as e:
        log.warning("yandex track info failed: %s", e)
        return None


async def download_yandex_track(
    url: str,
    *,
    cancel_event: threading.Event | None = None,
) -> tuple[str | None, YandexTrackInfo | None]:
    ref = parse_yandex_track_url(url)
    if not ref:
        return None, None

    client = await _get_client()
    if not client:
        return None, None

    if cancel_event is not None and cancel_event.is_set():
        return None, None

    try:
        tracks = await client.tracks(_track_key(ref))
        if not tracks:
            return None, None
        track = tracks[0]
        info = _track_info(track)

        downloads = await track.get_download_info_async(get_direct_links=True)
        if not downloads:
            return None, info

        best = max(downloads, key=lambda d: getattr(d, "bitrate_in_kbps", 0) or 0)
        if cancel_event is not None and cancel_event.is_set():
            return None, info

        filename = safe_filename(info.label)
        dest = os.path.join(os.getcwd(), filename)

        await best.download_async(dest)

        if not os.path.isfile(dest) or os.path.getsize(dest) < 4096:
            if os.path.isfile(dest):
                try:
                    os.remove(dest)
                except OSError:
                    pass
            return None, info

        # Иногда библиотека сохраняет без .mp3 / в другом расширении
        if not dest.lower().endswith(".mp3"):
            mp3 = dest + ".mp3" if "." not in os.path.basename(dest) else os.path.splitext(dest)[0] + ".mp3"
            try:
                if os.path.isfile(dest):
                    os.replace(dest, mp3)
                    dest = mp3
            except OSError:
                pass

        try:
            from media_core.media_tags import tag_mp3

            tag_mp3(
                dest,
                title=info.title,
                artist=info.artist,
                album=info.album,
                cover_url=info.cover_url,
            )
        except Exception as e:
            log.warning("yandex tag failed: %s", e)

        _set_last_yandex_track_meta(info, url)
        return dest, info
    except Exception as e:
        log.warning("yandex download failed: %s", e)
        return None, None
