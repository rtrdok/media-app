"""Оценка размера и метаданные форматов."""

from __future__ import annotations

from media_core.video_quality import effective_video_height, snap_quality_height


def _fmt_bytes(n: int | None) -> str:
    if not n or n <= 0:
        return ""
    mb = n / (1024 * 1024)
    if mb >= 1024:
        return f"~{mb / 1024:.1f} ГБ"
    return f"~{mb:.0f} МБ"


def estimate_sizes(info: dict | None) -> dict[str, dict]:
    """value quality -> {bytes, label} для UI."""
    info = info or {}
    formats = info.get("formats") or []
    audio = [
        f for f in formats
        if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none")
    ]
    best_audio = 0
    for f in audio:
        sz = f.get("filesize") or f.get("filesize_approx") or 0
        if sz > best_audio:
            best_audio = int(sz)

    by_height: dict[int, int] = {}
    for f in formats:
        if f.get("vcodec") in (None, "none"):
            continue
        h = effective_video_height(f)
        if not h:
            continue
        h = snap_quality_height(h)
        sz = f.get("filesize") or f.get("filesize_approx") or 0
        # progressive (video+audio in one)
        if f.get("acodec") not in (None, "none"):
            total = int(sz)
        else:
            total = int(sz) + best_audio if sz else 0
        if total and total > by_height.get(h, 0):
            by_height[h] = total

    out: dict[str, dict] = {}
    for h, total in by_height.items():
        out[str(h)] = {"bytes": total, "label": _fmt_bytes(total)}
    if by_height:
        mh = max(by_height)
        out["best"] = {"bytes": by_height[mh], "label": _fmt_bytes(by_height[mh])}
    else:
        for f in formats:
            sz = f.get("filesize") or f.get("filesize_approx") or info.get("filesize") or 0
            if sz:
                out["best"] = {"bytes": int(sz), "label": _fmt_bytes(int(sz))}
                break
    return out
