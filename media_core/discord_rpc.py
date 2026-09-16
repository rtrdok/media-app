"""Discord Rich Presence: «Listening to Media App» при воспроизведении.

Если Discord от администратора — локальный IPC даёт WinError 5.
Тогда поднимаем elevated-агент (UAC один раз) и шлём статус по localhost.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from media_core.discord_rpc_agent import AGENT_URL
from media_core.logging_setup import log

_q: queue.Queue = queue.Queue(maxsize=8)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_warned_no_id = False
_fail_count = 0
_use_agent = False
_agent_launch_attempted = False
_agent_launch_ts = 0.0


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


def _is_access_denied(exc: BaseException) -> bool:
    winerr = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    msg = str(exc).lower()
    return winerr == 5 or "access is denied" in msg or "отказано" in msg or "access denied" in msg


def _agent_healthy() -> bool:
    try:
        with urllib.request.urlopen(f"{AGENT_URL}/health", timeout=0.6) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        return bool(data.get("ok"))
    except Exception:
        return False


def _launch_elevated_agent() -> bool:
    """UAC: MediaApp.exe --discord-rpc-agent (или python main.py …)."""
    global _agent_launch_attempted, _agent_launch_ts
    now = time.time()
    if _agent_launch_attempted and (now - _agent_launch_ts) < 45:
        return _agent_healthy()
    _agent_launch_attempted = True
    _agent_launch_ts = now

    if _agent_healthy():
        return True

    try:
        from pathlib import Path

        import ctypes

        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = "--discord-rpc-agent"
            cwd = str(Path(sys.executable).resolve().parent)
        else:
            root = Path(__file__).resolve().parent.parent
            exe = sys.executable
            params = f'"{root / "main.py"}" --discord-rpc-agent'
            cwd = str(root)

        rc = int(
            ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                exe,
                params,
                cwd,
                0,  # SW_HIDE
            )
        )
        if rc <= 32:
            log.warning("Discord RPC agent UAC launch failed (code %s)", rc)
            return False
        log.info("Discord RPC: запрошен elevated-агент (подтверди UAC)")
        for _ in range(40):
            time.sleep(0.25)
            if _agent_healthy():
                log.info("Discord RPC agent is up")
                return True
        log.warning("Discord RPC agent не ответил — UAC отклонён или агент не стартовал")
        return False
    except Exception as e:
        log.warning("Discord RPC agent launch error: %s", e)
        return False


def _post_agent(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{AGENT_URL}{path}",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError:
        return None
    except Exception as e:
        log.warning("Discord RPC agent POST failed: %s", e)
        return None


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


def _connect_local(cid: str):
    from pypresence import Presence

    last_err: Exception | None = None
    for attempt in range(1, 4):
        rpc = None
        try:
            rpc = Presence(cid)
            rpc.connect()
            return rpc
        except Exception as e:
            last_err = e
            _close_rpc(rpc)
            if _is_access_denied(e):
                break
            if attempt >= 3:
                break
            time.sleep(0.4 * attempt)
    assert last_err is not None
    raise last_err


def _push_local(rpc, state: dict[str, Any], cid: str) -> None:
    from pypresence.types import ActivityType, StatusDisplayType

    from media_core.discord_presence import discord_cover_image

    has_track = bool(state.get("has_track"))
    playing = bool(state.get("playing"))
    title = _clip(str(state.get("title") or "Трек"))
    artist = _clip(str(state.get("artist") or ""))
    kind = str(state.get("kind") or "audio").lower()
    cover = discord_cover_image(str(state.get("thumb") or ""))
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
    if playing and duration > 1 and current < duration and start_ts is not None:
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
    if cover:
        kwargs["large_image"] = cover
    else:
        # опциональный ассет из Developer Portal → Rich Presence → Art Assets
        kwargs["large_image"] = "logo"
    try:
        rpc.update(**kwargs)
    except Exception:
        if cover or kwargs.get("large_image") == "logo":
            kwargs.pop("large_image", None)
            rpc.update(**kwargs)
        else:
            raise


def _sync_via_agent(state: dict[str, Any], cid: str) -> bool:
    if not _agent_healthy():
        if not _launch_elevated_agent():
            return False
    payload = dict(state)
    payload["client_id"] = cid
    res = _post_agent("/sync", payload)
    return bool(res and res.get("ok"))


def _worker_main() -> None:
    global _warned_no_id, _fail_count, _use_agent

    import asyncio

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
            if _use_agent:
                _post_agent("/clear", {})
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
            # режим агента сохраняем — Discord всё ещё admin
            continue

        if cmd != "sync":
            continue

        state = payload or {}
        if not _enabled():
            _close_rpc(rpc)
            rpc = None
            connected_id = ""
            last_sig = ""
            if _use_agent:
                _post_agent("/clear", {})
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
        title = _clip(str(state.get("title") or ""))
        artist = _clip(str(state.get("artist") or ""))
        kind = str(state.get("kind") or "audio").lower()
        playing = bool(state.get("playing"))
        thumb = str(state.get("thumb") or "")
        try:
            duration = float(state.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0

        if not has_track or not title:
            if _use_agent:
                _post_agent("/sync", {"client_id": cid, "has_track": False, "title": ""})
            elif rpc is not None:
                try:
                    rpc.clear()
                except Exception:
                    _close_rpc(rpc)
                    rpc = None
                    connected_id = ""
            last_sig = ""
            continue

        sig = "|".join(
            [
                title,
                artist,
                kind,
                "1" if playing else "0",
                str(int(duration)),
                thumb[:96],
                cid,
                "a" if _use_agent else "l",
            ]
        )
        now = time.time()
        if sig == last_sig and (now - last_push) < 15 and (rpc is not None or _use_agent):
            continue

        try:
            if _use_agent or _agent_healthy():
                _use_agent = True
                _close_rpc(rpc)
                rpc = None
                connected_id = ""
                if not _sync_via_agent(state, cid):
                    raise RuntimeError("agent sync failed")
                last_sig = sig
                last_push = now
                _fail_count = 0
                continue

            if rpc is None or connected_id != cid:
                _close_rpc(rpc)
                rpc = _connect_local(cid)
                connected_id = cid
                log.info("Discord RPC connected locally (%s…)", cid[:6])
                _fail_count = 0
            _push_local(rpc, state, cid)
            last_sig = sig
            last_push = now
        except Exception as e:
            _fail_count += 1
            _close_rpc(rpc)
            rpc = None
            connected_id = ""
            last_sig = ""

            if _is_access_denied(e) or (not _use_agent and _fail_count >= 1):
                # Discord от админа → elevated agent
                if _fail_count <= 3:
                    log.warning(
                        "Discord RPC: локальный IPC недоступен (%s) — "
                        "запускаю агент с правами администратора (UAC)",
                        e,
                    )
                if _sync_via_agent(state, cid):
                    _use_agent = True
                    last_sig = sig
                    last_push = time.time()
                    _fail_count = 0
                    continue

            if _fail_count <= 3 or _fail_count % 10 == 0:
                log.warning("Discord RPC failed (%s): %s", _fail_count, e)
            time.sleep(min(1.5 + _fail_count * 0.2, 6.0))


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
    _enqueue("sync", dict(state or {}))


def clear_presence() -> None:
    _enqueue("sync", {"has_track": False, "playing": False, "title": ""})


def on_settings_changed() -> None:
    global _agent_launch_attempted
    _agent_launch_attempted = False
    _enqueue("reset")
