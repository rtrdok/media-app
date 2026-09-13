"""Поиск аниме по кадру через trace.moe API."""

from __future__ import annotations

import asyncio
import os
import time

import aiohttp

from media_core.config import (
    TRACE_MOE_API_KEY,
    TRACE_MOE_GUESS_MIN,
    TRACE_MOE_MIN_GAP,
    TRACE_MOE_MIN_SIMILARITY,
    TRACE_MOE_REJECT_SIMILARITY,
    TRACE_MOE_URL,
)
from media_core.logging_setup import log
from media_core.utils import fmt_time


def _extract_title(entry: dict) -> str:
    anilist = entry.get("anilist")
    if isinstance(anilist, dict):
        title = anilist.get("title") or {}
        if isinstance(title, dict):
            for key in ("russian", "romaji", "english", "native"):
                val = title.get(key)
                if val:
                    return str(val)
        if anilist.get("id"):
            return f"AniList #{anilist['id']}"
    if isinstance(anilist, int):
        return f"AniList #{anilist}"
    filename = entry.get("filename") or ""
    if filename:
        return filename.split(" - ")[0].strip() or filename
    return "Неизвестно"


def _extract_anilist_id(entry: dict) -> int | None:
    anilist = entry.get("anilist")
    if isinstance(anilist, dict):
        return anilist.get("id")
    if isinstance(anilist, int):
        return anilist
    return None


def _not_anime_message(similarity: float) -> str:
    pct = similarity * 100
    return (
        f"Не похоже на кадр из аниме ({pct:.0f}%).\n\n"
        "trace.moe ищет только скриншоты из серий.\n"
        "Не подходят: рабочий стол, мемы, фото, арты, фанарт, картинки из Google."
    )


def _weak_match_message(similarity: float, title: str) -> str:
    pct = similarity * 100
    if similarity >= TRACE_MOE_GUESS_MIN:
        return (
            f"Слабое совпадение ({pct:.0f}%).\n"
            f"Может быть: {title} — но уверенности мало.\n\n"
            "Пришли чёткий кадр из серии, без рамок и водяных знаков."
        )
    return (
        f"Совпадение слишком слабое ({pct:.0f}%).\n"
        "Скорее всего, это не кадр из аниме.\n\n"
        "Нужен именно скриншот из эпизода, а не случайная картинка."
    )


def _anilist_url(anilist_id: int | None) -> str | None:
    if anilist_id:
        return f"https://anilist.co/anime/{anilist_id}"
    return None


def format_trace_result(data: dict) -> tuple[bool, str, dict]:
    """success, user_text, meta for DB."""
    err = (data.get("error") or "").strip()
    if err:
        return False, f"trace.moe: {err}", {"error": err}

    results = data.get("result") or []
    if not results:
        return False, (
            "Не нашёл совпадений.\n"
            "Нужен чёткий кадр из аниме (скриншот серии). Фанарт и арты не подходят."
        ), {"error": "no_results"}

    best = results[0]
    similarity = float(best.get("similarity") or 0)
    second_sim = float(results[1].get("similarity") or 0) if len(results) > 1 else 0.0
    gap = similarity - second_sim
    title = _extract_title(best)
    episode = best.get("episode")
    from_sec = float(best.get("from") or 0)
    preview = best.get("image") or best.get("video")
    anilist_id = _extract_anilist_id(best)

    meta = {
        "title": title,
        "episode": episode,
        "moment_sec": from_sec,
        "similarity": similarity,
        "anilist_id": anilist_id,
        "anilist_url": _anilist_url(anilist_id),
        "preview_url": preview,
    }

    if similarity < TRACE_MOE_REJECT_SIMILARITY:
        return False, _not_anime_message(similarity), {**meta, "error": "not_anime"}

    if similarity < TRACE_MOE_MIN_SIMILARITY:
        return False, _weak_match_message(similarity, title), {**meta, "error": "low_similarity"}

    if len(results) > 1 and gap < TRACE_MOE_MIN_GAP:
        second_title = _extract_title(results[1])
        ep_line = f"Серия: {episode}" if episode is not None else "Серия: —"
        anilist_line = f"\n📖 AniList: {_anilist_url(anilist_id)}" if anilist_id else ""
        text = (
            f"🎬 {title}\n"
            f"{ep_line}\n"
            f"Момент: {fmt_time(int(from_sec))}\n"
            f"Совпадение: {similarity * 100:.1f}%{anilist_line}\n\n"
            f"⚠️ Похожий вариант: {second_title} ({second_sim * 100:.0f}%). "
            "Если не то — пришли кадр покрупнее, без лишнего по краям."
        )
        return True, text, {**meta, "error": "ambiguous"}

    ep_line = f"Серия: {episode}" if episode is not None else "Серия: —"
    anilist_line = f"\n📖 AniList: {_anilist_url(anilist_id)}" if anilist_id else ""
    text = (
        f"🎬 {title}\n"
        f"{ep_line}\n"
        f"Момент: {fmt_time(int(from_sec))}\n"
        f"Совпадение: {similarity * 100:.1f}%{anilist_line}"
    )
    return True, text, meta


def candidates_from_api(body: dict) -> list[dict]:
    out = []
    for entry in (body.get("result") or [])[:5]:
        anilist_id = _extract_anilist_id(entry)
        out.append({
            "title": _extract_title(entry),
            "episode": entry.get("episode"),
            "from_sec": float(entry.get("from") or 0),
            "similarity": float(entry.get("similarity") or 0),
            "preview_url": entry.get("image") or entry.get("video"),
            "video_url": entry.get("video"),
            "anilist_id": anilist_id,
            "anilist_url": _anilist_url(anilist_id),
        })
    return out


async def search_anime_image(image_path: str) -> tuple[bool, str, dict, dict]:
    """Возвращает success, text, meta, raw_api."""
    headers = {}
    if TRACE_MOE_API_KEY:
        headers["x-trace-key"] = TRACE_MOE_API_KEY

    url = f"{TRACE_MOE_URL}/search?anilistInfo=1&cutBorders=1"
    try:
        image_bytes = await asyncio.to_thread(lambda: open(image_path, "rb").read())
        data = aiohttp.FormData()
        data.add_field("image", image_bytes, filename="photo.jpg", content_type="image/jpeg")
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=data, headers=headers) as resp:
                body = await resp.json(content_type=None)
                if resp.status == 429:
                    return False, "Слишком много запросов к trace.moe. Подожди минуту.", {"error": "rate_limit"}, {}
                if resp.status >= 400:
                    msg = body.get("error") if isinstance(body, dict) else str(body)
                    return False, f"trace.moe недоступен ({resp.status}).", {"error": msg or resp.status}, {}
    except aiohttp.ClientError as e:
        log.warning("trace.moe request failed: %s", e)
        return False, "Не удалось связаться с trace.moe. Попробуй позже.", {"error": str(e)}, {}
    except OSError as e:
        return False, "Не удалось прочитать фото.", {"error": str(e)}, {}

    if not isinstance(body, dict):
        return False, "Некорректный ответ trace.moe.", {"error": "bad_json"}, {}

    ok, text, meta = format_trace_result(body)
    return ok, text, meta, body
