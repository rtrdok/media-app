"""Discord Rich Presence: «Listening to Media App» при воспроизведении.

pypresence + FastAPI: работа только в отдельном потоке со своим asyncio loop.
WinError 5 часто из‑за Discord «от имени администратора» — ретраи + подсказка.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from typing import Any

from media_core.logging_setup import log

_q: queue.Queue = queue.Queue(maxsize=8)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_warned_no_id = False
_fail_count = 0


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


def _clip(s: str, n: int = 120) -> str:
    t = (s or "").strip()
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def _close_rpc(rpc) -> None:
    if rpc is None:
        return
    try:
        rpc.clear()
    except Exception:
        pass
    try:
        rpc.close()
    except Exception:
        pass


def _connect(cid: str):
    """Подключение в текущем потоке; у потока должен быть свой event loop."""
    from pypresence import Presence

    last_err: Exception | None = None
    for attempt in range(1, 6):
        rpc = None
        try:
            rpc = Presence(cid)
            rpc.connect()
            return rpc
        except Exception as e:
            last_err = e
            _close_rpc(rpc)
            # Access denied / pipe busy — подождать и ещё раз
            winerr = getattr(e, "winerror", None) or getattr(e, "errno", None)
            msg = str(e).lower()
            retryable = winerr in (5, 32, 231) or "access" in msg or "pipe" in msg or "denied" in msg
            if not retryable or attempt >= 5:
                break
            time.sleep(0.6 * attempt)
    assert last_err is not None
    raise last_err


def _push_update(rpc, state: dict[str, Any]) -> None:
    from pypresence.types import ActivityType, StatusDisplayType

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
        try:
            rpc.clear()
        except Exception:
            pass
        return

    now = time.time()
    start_ts = int(now - max(0.0, current)) if playing else None
    end_ts = None
    if playing and duration and duration > 1 and current < duration and start_ts is not None:
        end_ts = int(start_ts + duration)

    is_video = kind == "video"
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
    # Обложки по URL Discord часто отвергает — не мешаем статусу
    try:
        rpc.update(**kwargs)
    except Exception:
        raise


def _worker_main() -> None:
    global _warned_no_id, _fail_count

    # Свой loop — иначе pypresence цепляется к FastAPI и падает
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    rpc = None
    connected_id = ""
    last_sig = ""
    last_push = 0.0

    while True:
        try:
            item = _q.get(timeout=1.0)
        except queue.Empty:
            continue

        if item is None:
            _close_rpc(rpc)
            rpc = None
            try:
                loop.close()
            except Exception:
                pass
            break

        cmd, payload = item
        if cmd == "reset":
            _close_rpc(rpc)
            rpc = None
            connected_id = ""
            last_sig = ""
            _warned_no_id = False
            _fail_count = 0
            continue

        if cmd != "sync":
            continue

        state = payload or {}
        if not _enabled():
            _close_rpc(rpc)
            rpc = None
            connected_id = ""
            last_sig = ""
            continue

        cid = _client_id()
        if not cid or not cid.isdigit():
            if not _warned_no_id:
                log.info(
                    "Discord RPC: задай Client ID в Настройках "
                    "(discord.com/developers/applications → New Application → Application ID)"
                )
                _warned_no_id = True
            continue

        has_track = bool(state.get("has_track"))
        playing = bool(state.get("playing"))
        title = _clip(str(state.get("title") or ""))
        artist = _clip(str(state.get("artist") or ""))
        kind = str(state.get("kind") or "audio").lower()
        thumb = str(state.get("thumb") or "").strip()
        try:
            duration = float(state.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0

        if not has_track or not title:
            if rpc is not None:
                try:
                    rpc.clear()
                except Exception:
                    _close_rpc(rpc)
                    rpc = None
                    connected_id = ""
            last_sig = ""
            continue

        sig = "|".join(
            [title, artist, kind, "1" if playing else "0", str(int(duration)), thumb[:80], cid]
        )
        now = time.time()
        if sig == last_sig and (now - last_push) < 15 and rpc is not None:
            continue

        try:
            if rpc is None or connected_id != cid:
                _close_rpc(rpc)
                rpc = _connect(cid)
                connected_id = cid
                log.info("Discord RPC connected (%s…)", cid[:6])
                _fail_count = 0
            _push_update(rpc, state)
            last_sig = sig
            last_push = now
        except Exception as e:
            _fail_count += 1
            winerr = getattr(e, "winerror", None)
            # Лог: первые 3 раза и потом каждые 10
            if _fail_count <= 3 or _fail_count % 10 == 0:
                log.warning("Discord RPC failed (%s): %s", _fail_count, e)
                if winerr == 5 or "access is denied" in str(e).lower() or "отказано" in str(e).lower():
                    log.warning(
                        "Discord RPC: закрой Discord полностью (трей тоже) и запусти "
                        "БЕЗ «от имени администратора», затем снова Play в Media App"
                    )
            _close_rpc(rpc)
            rpc = None
            connected_id = ""
            last_sig = ""
            # пауза перед следующим sync из очереди
            time.sleep(min(2.0 + _fail_count * 0.3, 8.0))


def _ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_worker_main, name="discord-rpc", daemon=True)
        _worker.start()


def _enqueue(cmd: str, payload: Any = None) -> None:
    _ensure_worker()
    try:
        if cmd == "sync":
            while not _q.empty():
                try:
                    _q.get_nowait()
                except queue.Empty:
                    break
        _q.put_nowait((cmd, payload))
    except queue.Full:
        pass


def sync_from_player(state: dict[str, Any]) -> None:
    """Обновить presence по состоянию плеера (вызывать из publish)."""
    _enqueue("sync", dict(state or {}))


def clear_presence() -> None:
    _enqueue("sync", {"has_track": False, "playing": False, "title": ""})


def on_settings_changed() -> None:
    """После сохранения настроек — переподключить / выключить."""
    _enqueue("reset")
