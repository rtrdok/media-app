"""Распознавание музыки через Shazam (TikTok — так же, без TikTok API)."""

from __future__ import annotations

import asyncio
import os
import shutil
import threading
from pathlib import Path

from media_core.config import BASE_DIR, DEFAULT_RECOGNIZE_CLIP_SECONDS
from media_core.constants import CANCELLED
from media_core.database import cache_get, cache_set
from media_core.download_process import process_url
from media_core.logging_setup import log
from media_core.utils import detect_platform, fmt_time, trim_audio


def _cover_from_track(track: dict) -> str | None:
    images = track.get("images") or {}
    for key in ("coverarthq", "coverart", "background"):
        url = images.get(key)
        if url:
            return str(url)
    return None


def _parse_shazam_result(result: dict) -> dict | None:
    if not result or not result.get("track"):
        return None
    track = result["track"]
    title = track.get("title") or "Неизвестно"
    artist = track.get("subtitle") or "Неизвестный исполнитель"
    label = f"{artist} — {title}"
    cover = _cover_from_track(track)
    # иногда есть короткий превью-URL у Apple Music hub
    preview_remote = None
    try:
        hub = track.get("hub") or {}
        for a in hub.get("actions") or []:
            if a.get("type") == "uri" and a.get("uri"):
                pass
        for section in track.get("sections") or []:
            if section.get("type") == "AUDIO_PREVIEW" or section.get("type") == "SONG":
                meta = section.get("meta") or {}
                # ignore
            for act in section.get("actions") or []:
                u = act.get("uri") or act.get("url")
                if u and str(u).endswith((".m4a", ".mp3")):
                    preview_remote = str(u)
    except Exception:
        pass
    return {
        "track": label,
        "title": title,
        "artist": artist,
        "cover_url": cover,
        "preview_remote": preview_remote,
    }


async def recognize_music_from_file(path: str) -> dict | None:
    """Shazam по локальному аудиофайлу → dict с track/cover."""
    try:
        from shazamio import Shazam

        shazam = Shazam()
        try:
            result = await asyncio.wait_for(shazam.recognize(path), timeout=25)
        except asyncio.TimeoutError:
            log.warning("Shazam: таймаут (file)")
            return None
        parsed = _parse_shazam_result(result or {})
        if parsed:
            log.info("Shazam нашёл (file): %s", parsed["track"])
            return parsed
    except Exception as e:
        log.exception("Shazam file error: %s", e)
    return None


def _save_preview_clip(src: str) -> str | None:
    """Копия клипа в file_cache для <audio> в UI."""
    try:
        if not src or not os.path.isfile(src):
            return None
        cache = Path(BASE_DIR) / "file_cache" / "shazam_preview"
        cache.mkdir(parents=True, exist_ok=True)
        suffix = Path(src).suffix or ".m4a"
        dest = cache / f"preview{suffix}"
        shutil.copy2(src, dest)
        return str(dest)
    except OSError as e:
        log.warning("shazam preview save: %s", e)
        return None


async def recognize_music_from_url(
    url: str,
    cancel_event: threading.Event | None = None,
    progress_state: dict | None = None,
    start: float | None = None,
    end: float | None = None,
) -> dict | object | None:
    use_cache = start is None
    if use_cache:
        cached = await cache_get(url)
        if cached:
            log.info("Кэш распознавания для %s: %s", url, cached)
            # старый кэш — строка; новый — JSON-строка с track
            if isinstance(cached, str) and cached.startswith("{"):
                import json
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass
            if isinstance(cached, str):
                return {"track": cached, "title": cached, "artist": "", "cover_url": None}

    result = await _recognize_uncached(url, cancel_event, progress_state, start, end)
    if use_cache and result and result is not CANCELLED and isinstance(result, dict):
        import json
        await cache_set(url, json.dumps({"track": result.get("track"), "title": result.get("title"),
                                         "artist": result.get("artist"), "cover_url": result.get("cover_url")},
                                        ensure_ascii=False))
    return result


async def _recognize_uncached(
    url: str,
    cancel_event: threading.Event | None,
    progress_state: dict | None,
    start: float | None,
    end: float | None,
):
    platform = detect_platform(url)
    log.info("Распознавание музыки: platform=%s start=%s end=%s", platform, start, end)

    def is_cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def set_stage(text: str) -> None:
        if progress_state is not None:
            progress_state["stage"] = text

    if is_cancelled():
        return CANCELLED

    clip_start = start if start is not None else 0
    clip_end = end if end is not None else clip_start + DEFAULT_RECOGNIZE_CLIP_SECONDS
    set_stage(f"Скачиваю отрезок {fmt_time(clip_start)}–{fmt_time(clip_end)} для распознавания...")

    if platform == "tiktok":
        path = await process_url(url, audio_only=True, cancel_event=cancel_event, record_stats=False, use_cache=False)
    else:
        path = await process_url(
            url, audio_only=True, progress_state=progress_state,
            cancel_event=cancel_event, start=clip_start, end=clip_end,
            record_stats=False, use_cache=False,
        )

    if path is CANCELLED:
        return CANCELLED
    if not path:
        return None

    clip_path = path
    if platform == "tiktok":
        trim_start = clip_start
        trim_dur = clip_end - clip_start
        trimmed = await trim_audio(path, trim_start, trim_dur)
        if trimmed:
            clip_path = trimmed

    try:
        if is_cancelled():
            return CANCELLED

        set_stage("Ищу через Shazam...")
        parsed = await recognize_music_from_file(clip_path)
        if not parsed:
            log.info("Shazam: трек не найден")
            return None
        preview_path = _save_preview_clip(clip_path)
        if preview_path:
            parsed["preview_path"] = preview_path
        return parsed
    finally:
        for p in {path, clip_path}:
            try:
                if p and os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass

