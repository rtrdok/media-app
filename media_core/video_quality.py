"""Нормализация высот видео под ярлыки YouTube (в т.ч. ультраширокие)."""

from __future__ import annotations

QUALITY_LADDER = (2160, 1440, 1080, 720, 480, 360, 240, 144)


def effective_video_height(fmt: dict | None) -> int | None:
    """Высота для UI/выбора качества.

    У обычного 16:9 берём height.
    У ультрашироких (≈2:1) YouTube показывает 16:9-эквивалент по ширине
    (3840×1920 → 2160p, 1920×960 → 1080p), а не сырой height.
    """
    if not fmt:
        return None
    try:
        h = int(fmt["height"]) if fmt.get("height") is not None else None
    except (TypeError, ValueError):
        h = None
    try:
        w = int(fmt["width"]) if fmt.get("width") is not None else None
    except (TypeError, ValueError):
        w = None
    if h and h <= 0:
        h = None
    if w and w <= 0:
        w = None
    if h and w:
        aspect = w / h
        if aspect >= 1.85:
            return int(round(w * 9 / 16))
        return h
    if h:
        return h
    if w:
        return int(round(w * 9 / 16))
    return None


def snap_quality_height(height: int) -> int:
    """Привязка к стандартной лестнице 144p…2160p."""
    best = min(QUALITY_LADDER, key=lambda s: abs(s - height))
    if abs(best - height) <= max(48, int(best * 0.12)):
        return best
    return height


def format_richness(info: dict | None) -> int:
    """Насколько полный список видеоформатов (для выбора лучшего probe)."""
    info = info or {}
    heights = {
        snap_quality_height(h)
        for f in info.get("formats") or []
        if f.get("vcodec") not in (None, "none")
        for h in [effective_video_height(f)]
        if h
    }
    return len(heights) * 1000 + (max(heights) if heights else 0)
