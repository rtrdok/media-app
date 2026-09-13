"""Теги и обложка для MP3."""

from __future__ import annotations

import os
from pathlib import Path

from media_core.logging_setup import log


def tag_mp3(
    path: str,
    *,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    cover_url: str | None = None,
) -> None:
    if not path or not os.path.isfile(path) or not path.lower().endswith(".mp3"):
        return
    try:
        from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, ID3NoHeaderError
        from mutagen.mp3 import MP3
    except Exception as e:
        log.warning("mutagen unavailable: %s", e)
        return

    try:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()

        if title:
            tags["TIT2"] = TIT2(encoding=3, text=title)
        if artist:
            tags["TPE1"] = TPE1(encoding=3, text=artist)
        if album:
            tags["TALB"] = TALB(encoding=3, text=album)

        if cover_url:
            try:
                import requests

                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                }
                low = cover_url.lower()
                if any(x in low for x in ("userapi.com", "vkuseraudio", "vk.com", "vk.ru", "sun")):
                    headers["Referer"] = "https://vk.com/"
                    try:
                        from media_core.config import load_vk_cookies

                        cookies = load_vk_cookies()
                        if cookies:
                            headers["Cookie"] = cookies
                    except Exception:
                        pass
                from media_core.net_proxy import apply_requests_kwargs

                kw = apply_requests_kwargs({"timeout": 20, "headers": headers})
                r = requests.get(cover_url, **kw)
                r.raise_for_status()
                data = r.content
                if not data or len(data) < 64:
                    raise RuntimeError("empty cover")
                mime = "image/jpeg"
                ctype = (r.headers.get("content-type") or "").lower()
                if "png" in ctype or data[:8].startswith(b"\x89PNG"):
                    mime = "image/png"
                elif "webp" in ctype or data[:4] == b"RIFF":
                    mime = "image/webp"
                tags.delall("APIC")
                tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
            except Exception as e:
                log.warning("cover download failed: %s", e)

        tags.save(path)
        # touch for some players
        Path(path).touch(exist_ok=True)
        _ = MP3(path)
        log.info("mp3 tags saved: %s", os.path.basename(path))
    except Exception as e:
        log.warning("tag_mp3 failed: %s", e)


def split_artist_title(label: str) -> tuple[str | None, str | None]:
    if " — " in label:
        a, t = label.split(" — ", 1)
        return a.strip() or None, t.strip() or None
    if " - " in label:
        a, t = label.split(" - ", 1)
        return a.strip() or None, t.strip() or None
    return None, label.strip() or None
