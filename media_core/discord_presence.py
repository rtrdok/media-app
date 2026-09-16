"""Общие хелперы Discord Rich Presence."""

from __future__ import annotations


def discord_cover_image(thumb: str | None) -> str | None:
    """Публичный HTTPS URL обложки для large_image (лимит Discord ~256 символов).

    Локальные /api/file и относительные пути Discord не видит — только интернет-URL
    (как у VK/Яндекс). Иначе None → клиент покажет дефолтную иконку приложения
    или ассет `logo`, если загружен в Developer Portal → Rich Presence.
    """
    t = (thumb or "").strip()
    if not t.startswith("https://"):
        return None
    if len(t) <= 256:
        return t
    base = t.split("?", 1)[0]
    if len(base) <= 256 and base.startswith("https://"):
        return base
    return None
