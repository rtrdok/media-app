"""Тексты песен через lrclib.net (без ключа API)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


def fetch_lyrics(title: str, artist: str = "", duration_sec: float | None = None) -> dict:
    title = (title or "").strip()
    artist = (artist or "").strip()
    if not title:
        return {"ok": False, "error": "Нет названия трека"}

    params = {"track_name": title, "artist_name": artist}
    url = "https://lrclib.net/api/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "MediaApp/1.4", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if not isinstance(data, list) or not data:
        return {"ok": False, "error": "Текст не найден", "lyrics": "", "synced": False}

    best = data[0]
    if duration_sec and duration_sec > 0:
        scored = []
        for it in data:
            d = it.get("duration")
            try:
                dd = float(d) if d is not None else None
            except (TypeError, ValueError):
                dd = None
            score = abs(dd - duration_sec) if dd is not None else 9999
            scored.append((score, it))
        scored.sort(key=lambda x: x[0])
        best = scored[0][1]

    synced = str(best.get("syncedLyrics") or "").strip()
    plain = str(best.get("plainLyrics") or "").strip()
    text = synced or plain
    if not text:
        return {"ok": False, "error": "Текст не найден", "lyrics": "", "synced": False}
    return {
        "ok": True,
        "lyrics": text,
        "synced": bool(synced),
        "title": best.get("trackName") or title,
        "artist": best.get("artistName") or artist,
        "source": "lrclib.net",
    }
