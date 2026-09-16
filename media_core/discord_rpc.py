"""Discord Rich Presence: «Listening to Media App» при воспроизведении."""

from __future__ import annotations

import threading
import time
from typing import Any

from media_core.logging_setup import log

_lock = threading.Lock()
_rpc = None
_connected_id = ""
_last_sig = ""
_last_push = 0.0
_warned = False

# Минимальный интервал обновления (Discord не любит спам)
_MIN_INTERVAL_SEC = 2.0


def _client_id() -> str:
    from media_core.settings_store import get_all

    data = get_all()
    custom = str(data.get("discord_client_id") or "").strip()
    if custom.isdigit() and len(custom) >= 17:
        return custom
    from media_core.constants import DISCORD_CLIENT_ID

    return str(DISCORD_CLIENT_ID or "").strip()


def _enabled() -> bool:
    from media_core.settings_store import get_bool

    return get_bool("discord_rpc", True)


def _disconnect() -> None:
    global _rpc, _connected_id, _last_sig
    if _rpc is not None:
        try:
            _rpc.clear()
        except Exception:
            pass
        try:
            _rpc.close()
        except Exception:
            pass
    _rpc = None
    _connected_id = ""
    _last_sig = ""


def _ensure() -> bool:
    global _rpc, _connected_id, _warned
    if not _enabled():
        _disconnect()
        return False
    cid = _client_id()
    if not cid or not cid.isdigit():
        if not _warned:
            log.info(
                "Discord RPC: задай Client ID в Настройках "
                "(discord.com/developers/applications → New Application → Application ID)"
            )
            _warned = True
        return False
    if _rpc is not None and _connected_id == cid:
        return True
    _disconnect()
    try:
        from pypresence import Presence

        rpc = Presence(cid)
        rpc.connect()
        _rpc = rpc
        _connected_id = cid
        log.info("Discord RPC connected (%s…)", cid[:6])
        return True
    except Exception as e:
        if not _warned:
            log.warning("Discord RPC unavailable: %s", e)
            _warned = True
        _rpc = None
        _connected_id = ""
        return False


def _clip(s: str, n: int = 120) -> str:
    t = (s or "").strip()
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def clear_presence() -> None:
    global _last_sig
    with _lock:
        if _rpc is None:
            _last_sig = ""
            return
        try:
            _rpc.clear()
        except Exception:
            _disconnect()
        _last_sig = ""


def sync_from_player(state: dict[str, Any]) -> None:
    """Обновить presence по состоянию плеера (вызывать из publish)."""
    global _last_sig, _last_push

    if not _enabled():
        with _lock:
            _disconnect()
        return

    has_track = bool(state.get("has_track"))
    playing = bool(state.get("playing"))
    title = _clip(str(state.get("title") or "Трек"))
    artist = _clip(str(state.get("artist") or ""))
    kind = str(state.get("kind") or "audio").lower()
    thumb = str(state.get("thumb") or "").strip()
    try:
        current = float(state.get("current") or 0)
    except (TypeError, ValueError):
        current = 0.0
    try:
        duration = float(state.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0

    if not has_track or not title:
        clear_presence()
        return

    # Пауза: оставляем карточку, но без «бегущего» таймера конца
    now = time.time()
    start_ts = int(now - max(0.0, current)) if playing else None
    end_ts = None
    if playing and duration and duration > 1 and current < duration:
        end_ts = int(start_ts + duration) if start_ts is not None else None

    is_video = kind == "video"
    # Сигнатура без текущего времени — не долбить Discord каждую секунду
    sig = "|".join(
        [
            title,
            artist,
            kind,
            "1" if playing else "0",
            str(int(duration)),
            thumb[:80],
            _client_id(),
        ]
    )
    with _lock:
        if sig == _last_sig and (now - _last_push) < 15:
            return
        if not _ensure() or _rpc is None:
            return
        try:
            from pypresence.types import ActivityType, StatusDisplayType

            kwargs: dict[str, Any] = {
                "activity_type": ActivityType.WATCHING if is_video else ActivityType.LISTENING,
                "status_display_type": StatusDisplayType.DETAILS,
                "details": title,
                "state": artist or ("видео" if is_video else "музыка"),
                "name": "Media App",
                "large_text": title,
            }
            if start_ts is not None:
                kwargs["start"] = start_ts
            if end_ts is not None:
                kwargs["end"] = end_ts
            use_art = thumb.startswith("http://") or thumb.startswith("https://")
            if use_art:
                kwargs["large_image"] = thumb
            try:
                _rpc.update(**kwargs)
            except Exception:
                if use_art:
                    kwargs.pop("large_image", None)
                    _rpc.update(**kwargs)
                else:
                    raise
            _last_sig = sig
            _last_push = now
        except Exception as e:
            log.warning("Discord RPC update failed: %s", e)
            _disconnect()


def on_settings_changed() -> None:
    """После сохранения настроек — переподключить / выключить."""
    global _warned
    _warned = False
    with _lock:
        if not _enabled():
            _disconnect()
            return
        # сброс, чтобы следующий sync переподключился с новым ID
        _disconnect()
