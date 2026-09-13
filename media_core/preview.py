"""Превью ссылки перед выбором действия."""

from __future__ import annotations

import re

from media_core.download_tiktok import fetch_tiktok_preview
from media_core.download_ytdlp import probe_video_info
from media_core.format_sizes import estimate_sizes
from media_core.utils import PLATFORM_NAMES, detect_platform, fmt_time
from media_core.video_quality import effective_video_height, snap_quality_height


def available_qualities(info: dict | None) -> list[dict]:
    """Только реально доступные высоты (ярлыки как на YouTube, без апскейла)."""
    info = info or {}
    sizes = estimate_sizes(info)
    buckets: dict[int, float] = {}
    for f in info.get("formats") or []:
        if f.get("vcodec") in (None, "none"):
            continue
        h = effective_video_height(f)
        if not h:
            continue
        h = snap_quality_height(h)
        fps = float(f.get("fps") or 0)
        buckets[h] = max(buckets.get(h, 0.0), fps)

    out: list[dict] = []
    for h in sorted(buckets.keys(), reverse=True):
        fps = buckets[h]
        if h >= 2160:
            base = f"{h}p (4K)"
        elif h >= 1440:
            base = f"{h}p"
        elif h >= 1080:
            base = f"{h}p (HD)"
        else:
            base = f"{h}p"
        if fps >= 50:
            label = f"{h}p{int(round(fps))}" + (" (4K)" if h >= 2160 else (" (HD)" if h >= 1080 else ""))
        else:
            label = base
        size = sizes.get(str(h), {})
        if size.get("label"):
            label = f"{label} · {size['label']}"
        out.append({"value": str(h), "label": label, "size": size.get("label") or ""})

    if out:
        best_size = sizes.get("best", {})
        bl = "Лучшее"
        if best_size.get("label"):
            bl = f"Лучшее · {best_size['label']}"
        out.append({"value": "best", "label": bl, "size": best_size.get("label") or ""})
    else:
        best_size = sizes.get("best", {})
        bl = "Оригинал"
        if best_size.get("label"):
            bl = f"Оригинал · {best_size['label']}"
        out.append({"value": "best", "label": bl, "size": best_size.get("label") or ""})
    return out


def available_audio_tracks(info: dict | None) -> list[dict]:
    """Языки/дорожки аудио из formats yt-dlp."""
    info = info or {}
    seen: dict[str, str] = {}
    for f in info.get("formats") or []:
        if f.get("acodec") in (None, "none"):
            continue
        lang = (f.get("language") or f.get("audio_lang") or "").strip()
        note = (f.get("format_note") or "").strip()
        if not lang and note and re.search(r"^[a-z]{2,3}(-[A-Za-z0-9]+)?$", note):
            lang = note
        if not lang:
            # иногда language в format_id
            fid = str(f.get("format_id") or "")
            m = re.search(r"\b([a-z]{2,3})(?:-[A-Za-z]+)?\b", fid)
            if m and m.group(1) not in ("mp", "hd", "sd", "tv"):
                lang = m.group(1)
        if not lang:
            continue
        label = lang
        if note and note != lang:
            label = f"{lang} · {note}"
        abr = f.get("abr")
        if abr:
            label = f"{label} · {int(abr)}kbps"
        if lang not in seen:
            seen[lang] = label
    out = [{"value": k, "label": v} for k, v in sorted(seen.items())]
    if out:
        out.insert(0, {"value": "", "label": "По умолчанию"})
    return out


async def fetch_preview(url: str) -> dict:
    """title, duration, thumbnail, uploader, platform."""
    from media_core.utils import is_soundcloud_url, is_vk_audio_url, is_yandex_music_url, parse_vk_audio_id, vk_audio_configured

    platform = detect_platform(url)
    if not platform:
        return {"platform": None}

    if is_vk_audio_url(url):
        preview: dict = {"platform": platform, "is_audio": True, "title": "VK Music"}
        if vk_audio_configured():
            from media_core.download_vk_audio import fetch_vk_audio_info

            audio_id = parse_vk_audio_id(url)
            if audio_id:
                info = await fetch_vk_audio_info(audio_id, source_url=url)
                if info:
                    preview["title"] = info.get("label") or preview["title"]
                    preview["duration"] = info.get("duration")
        return {**preview, "qualities": [{"value": "best", "label": "Аудио"}]}

    if is_yandex_music_url(url):
        from media_core.config import yandex_music_configured
        from media_core.yandex_music_api import fetch_yandex_track_info

        preview: dict = {"platform": platform, "is_audio": True, "title": "Яндекс Музыка"}
        if yandex_music_configured():
            info = await fetch_yandex_track_info(url)
            if info:
                preview.update({
                    "title": info.label,
                    "duration": info.duration,
                    "uploader": info.artist or None,
                })
        return {**preview, "qualities": [{"value": "best", "label": "Аудио"}]}

    if is_soundcloud_url(url):
        from media_core.config import resolve_soundcloud_cookies

        http_cookie, cookiefile = resolve_soundcloud_cookies()
        info = await probe_video_info(url)
        if (not info or not info.get("title")) and (http_cookie or cookiefile):
            info = await probe_video_info(
                url, extra_http_cookie=http_cookie, extra_cookiefile=cookiefile,
            )
        title = info.get("title") or info.get("track") or "SoundCloud"
        artist = info.get("uploader") or info.get("artist")
        label = title
        if artist and artist.lower() not in title.lower():
            label = f"{artist} — {title}"
        return {
            "platform": platform,
            "is_audio": True,
            "title": label,
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "uploader": artist,
            "qualities": [{"value": "best", "label": "Аудио"}],
        }

    if platform == "tiktok":
        meta = await fetch_tiktok_preview(url)
        if meta:
            meta["platform"] = platform
            meta["qualities"] = available_qualities(meta) if meta.get("formats") else [
                {"value": "best", "label": "Оригинал"},
            ]
            return meta
        return {
            "platform": platform,
            "title": "TikTok",
            "qualities": [{"value": "best", "label": "Оригинал"}],
        }

    info = await probe_video_info(url)
    if not info:
        return {"platform": platform, "title": platform.capitalize(), "qualities": available_qualities({}), "audio_tracks": []}

    return {
        "platform": platform,
        "title": info.get("title") or platform.capitalize(),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader") or info.get("channel"),
        "qualities": available_qualities(info),
        "audio_tracks": available_audio_tracks(info),
        "_raw_formats": len(info.get("formats") or []),
    }


def format_preview_caption(preview: dict, url: str) -> str:
    platform_names = PLATFORM_NAMES
    p = preview.get("platform")
    name = platform_names.get(p, p or "?")
    lines = [f"📎 {name}"]
    if preview.get("is_audio"):
        if preview.get("title"):
            lines.append(f"🎵 {preview['title']}")
    elif preview.get("title"):
        lines.append(f"🎬 {preview['title']}")
    if preview.get("uploader"):
        lines.append(f"👤 {preview['uploader']}")
    if preview.get("duration"):
        lines.append(f"⏱ {fmt_time(preview['duration'])}")
    lines.append("")
    lines.append("Выбери действие:")
    return "\n".join(lines)
