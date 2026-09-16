"""Elevated Discord RPC agent — для Discord, запущенного от администратора.

Не-admin Media App не может открыть IPC Discord (WinError 5).
Агент стартует с UAC (один раз), слушает 127.0.0.1 и шлёт Rich Presence.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from media_core.logging_setup import log

AGENT_HOST = "127.0.0.1"
AGENT_PORT = 17965
AGENT_URL = f"http://{AGENT_HOST}:{AGENT_PORT}"

_rpc = None
_connected_id = ""
_lock = threading.Lock()
_last_sig = ""
_last_push = 0.0


def _clip(s: str, n: int = 120) -> str:
    t = (s or "").strip()
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def _close() -> None:
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


def _ensure(cid: str) -> bool:
    global _rpc, _connected_id
    if _rpc is not None and _connected_id == cid:
        return True
    _close()
    from pypresence import Presence

    rpc = Presence(cid)
    rpc.connect()
    _rpc = rpc
    _connected_id = cid
    log.info("Discord RPC agent connected (%s…)", cid[:6])
    return True


def apply_state(data: dict[str, Any]) -> dict[str, Any]:
    global _last_sig, _last_push
    cid = str(data.get("client_id") or "").strip()
    if not cid.isdigit():
        return {"ok": False, "error": "client_id required"}

    has_track = bool(data.get("has_track"))
    playing = bool(data.get("playing"))
    title = _clip(str(data.get("title") or ""))
    artist = _clip(str(data.get("artist") or ""))
    kind = str(data.get("kind") or "audio").lower()
    thumb = str(data.get("thumb") or "")
    try:
        current = float(data.get("current") or 0)
    except (TypeError, ValueError):
        current = 0.0
    try:
        duration = float(data.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0

    with _lock:
        if not has_track or not title:
            if _rpc is not None:
                try:
                    _rpc.clear()
                except Exception:
                    _close()
            _last_sig = ""
            return {"ok": True, "cleared": True}

        sig = "|".join(
            [title, artist, kind, "1" if playing else "0", str(int(duration)), thumb[:96], cid]
        )
        now = time.time()
        if sig == _last_sig and (now - _last_push) < 12 and _rpc is not None:
            return {"ok": True, "skipped": True}

        try:
            from media_core.discord_presence import discord_cover_image
            from pypresence.types import ActivityType, StatusDisplayType

            _ensure(cid)
            assert _rpc is not None

            start_ts = int(now - max(0.0, current)) if playing else None
            end_ts = None
            if playing and duration > 1 and current < duration and start_ts is not None:
                end_ts = int(start_ts + duration)
            is_video = kind == "video"
            cover = discord_cover_image(thumb)
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
                kwargs["large_image"] = "logo"
            try:
                _rpc.update(**kwargs)
            except Exception:
                kwargs.pop("large_image", None)
                _rpc.update(**kwargs)
            _last_sig = sig
            _last_push = now
            return {"ok": True}
        except Exception as e:
            log.warning("Discord RPC agent update failed: %s", e)
            _close()
            return {"ok": False, "error": str(e)}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/health"):
            self._json(200, {"ok": True, "service": "mediaapp-discord-rpc-agent"})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "bad json"})
            return
        if not isinstance(data, dict):
            self._json(400, {"ok": False, "error": "object required"})
            return
        if path == "/sync":
            self._json(200, apply_state(data))
            return
        if path == "/clear":
            with _lock:
                _close()
            self._json(200, {"ok": True})
            return
        if path == "/shutdown":
            self._json(200, {"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.2), _stop_server()), daemon=True).start()
            return
        self._json(404, {"ok": False, "error": "not found"})


_httpd: ThreadingHTTPServer | None = None


def _stop_server() -> None:
    global _httpd
    with _lock:
        _close()
    if _httpd is not None:
        try:
            _httpd.shutdown()
        except Exception:
            pass


def run_agent() -> None:
    """Блокирующий запуск агента (вызывать из elevated процесса)."""
    global _httpd
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # отдельный mutex — не конфликтовать с основным Media App
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "Local\\MediaAppDiscordRpcAgent")
        last = kernel32.GetLastError()
        if last == 183:  # ERROR_ALREADY_EXISTS
            log.info("Discord RPC agent already running")
            return
        _ = handle
    except Exception:
        pass

    _httpd = ThreadingHTTPServer((AGENT_HOST, AGENT_PORT), _Handler)
    log.info("Discord RPC agent listening on %s", AGENT_URL)
    try:
        _httpd.serve_forever(poll_interval=0.5)
    finally:
        with _lock:
            _close()
        try:
            loop.close()
        except Exception:
            pass
