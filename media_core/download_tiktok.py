"""Скачивание TikTok через tikwm.com API."""

from __future__ import annotations

import asyncio
import os
import threading

from media_core.constants import CANCELLED
from media_core.logging_setup import log
from media_core.utils import create_slideshow, safe_get, write_bytes

TIKWM_API = "https://www.tikwm.com/api/"
TIKWM_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


async def download_tiktok(
    url: str,
    audio_only: bool = False,
    cancel_event: threading.Event | None = None,
):
    try:
        if cancel_event is not None and cancel_event.is_set():
            return CANCELLED

        r = await safe_get(TIKWM_API, params={"url": url, "hd": 1}, headers=TIKWM_HEADERS, timeout=15)
        data = r.json()
        if data.get("code") != 0:
            return None

        post = data["data"]
        vid = post.get("id", "tiktok")

        if audio_only:
            music = (post.get("music_info") or {}).get("play") or post.get("music")
            if not music:
                return None
            ar = await safe_get(music, headers=TIKWM_HEADERS, timeout=20)
            filename = f"audio_{vid}.mp3"
            await asyncio.to_thread(write_bytes, filename, ar.content)
            return filename

        video_url = post.get("hdplay") or post.get("play")
        if video_url and not post.get("images"):
            vr = await safe_get(video_url, headers=TIKWM_HEADERS, timeout=60)
            filename = f"tiktok_{vid}.mp4"
            await asyncio.to_thread(write_bytes, filename, vr.content)
            return filename

        images = post.get("images")
        if images:
            img_files = []
            for i, img_url in enumerate(images):
                if cancel_event is not None and cancel_event.is_set():
                    for f in img_files:
                        try:
                            os.remove(f)
                        except OSError:
                            pass
                    return CANCELLED
                ir = await safe_get(img_url, headers=TIKWM_HEADERS, timeout=15)
                name = f"tmp_{vid}_{i}.jpg"
                await asyncio.to_thread(write_bytes, name, ir.content)
                img_files.append(name)

            audio_path = None
            music = (post.get("music_info") or {}).get("play") or post.get("music")
            if music:
                ar = await safe_get(music, headers=TIKWM_HEADERS, timeout=15)
                audio_path = f"tmp_audio_{vid}.mp3"
                await asyncio.to_thread(write_bytes, audio_path, ar.content)

            output = f"tiktok_photo_{vid}.mp4"
            ok = await create_slideshow(img_files, audio_path, output)
            for f in img_files + ([audio_path] if audio_path else []):
                try:
                    os.remove(f)
                except OSError:
                    pass
            return output if ok else None

        return None
    except Exception as e:
        log.exception("TikTok error: %s", e)
        return None


async def fetch_tiktok_preview(url: str) -> dict | None:
    """Метаданные TikTok для превью."""
    try:
        r = await safe_get(TIKWM_API, params={"url": url, "hd": 1}, headers=TIKWM_HEADERS, timeout=15)
        data = r.json()
        if data.get("code") != 0:
            return None
        post = data["data"]
        title = post.get("title") or "TikTok"
        author = post.get("author", {}).get("nickname") if isinstance(post.get("author"), dict) else post.get("author")
        duration = post.get("duration")
        cover = post.get("cover") or post.get("origin_cover")
        return {"title": title, "uploader": author, "duration": duration, "thumbnail": cover}
    except Exception as e:
        log.warning("TikTok preview: %s", e)
    return None


async def fetch_tiktok_music_meta(url: str) -> str | None:
    """Название трека из метаданных TikTok (без Shazam)."""
    try:
        r = await safe_get(TIKWM_API, params={"url": url, "hd": 1}, headers=TIKWM_HEADERS, timeout=15)
        data = r.json()
        if data.get("code") != 0:
            return None
        post = data["data"]
        music_title = None
        music_author = None
        if post.get("music_info"):
            music_title = post["music_info"].get("title")
            music_author = post["music_info"].get("author")
        elif post.get("music"):
            music_title = post.get("music")
        if music_title:
            return f"{music_author} — {music_title}" if music_author else music_title
    except Exception as e:
        log.warning("TikTok music API: %s", e)
    return None
