"""Общие хелперы Discord Rich Presence."""

from __future__ import annotations


def discord_cover_image(thumb: str | None) -> str | None:
    """Публичный URL обложки для large_image (лимит Discord ~256 символов)."""
    t = (thumb or "").strip()
    if t.startswith("//"):
        t = "https:" + t
    if t.startswith("http://"):
        t = "https://" + t[len("http://") :]
    if not t.startswith("https://"):
        return None
    if len(t) <= 256:
        return t
    base = t.split("?", 1)[0]
    if len(base) <= 256 and base.startswith("https://"):
        return base
    return None
