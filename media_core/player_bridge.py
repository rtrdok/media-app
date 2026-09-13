"""Мост состояния плеера между главным окном и мини-плеером."""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_state: dict = {
    "title": "",
    "artist": "",
    "playing": False,
    "current": 0.0,
    "duration": 0.0,
    "volume": 0.85,
    "has_track": False,
    "thumb": "",
    "updated_at": 0.0,
}
_commands: list[dict] = []
_mini_open = False


def get_state() -> dict:
    with _lock:
        return dict(_state)


def publish_state(**kwargs) -> dict:
    with _lock:
        _state.update({k: v for k, v in kwargs.items() if v is not None})
        _state["updated_at"] = time.time()
        return dict(_state)


def push_command(action: str, **kwargs) -> dict:
    with _lock:
        cmd = {"action": action, **kwargs, "ts": time.time()}
        _commands.append(cmd)
        # не раздувать очередь
        if len(_commands) > 40:
            del _commands[:-20]
        return {"ok": True, "queued": len(_commands)}


def pop_commands() -> list[dict]:
    with _lock:
        out = list(_commands)
        _commands.clear()
        return out


def set_mini_open(v: bool) -> None:
    global _mini_open
    with _lock:
        _mini_open = bool(v)


def is_mini_open() -> bool:
    with _lock:
        return _mini_open


_mini_want = False


def set_mini_want(v: bool) -> None:
    global _mini_want
    with _lock:
        _mini_want = bool(v)


def get_mini_want() -> bool:
    with _lock:
        return _mini_want
