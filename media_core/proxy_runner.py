"""Перебор прокси (совместимость с yt-dlp)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from media_core.database import mask_proxy, record_proxy_result
from media_core.logging_setup import log

FATAL_PROXY_MARKERS = (
    "unsupported url",
    "no video formats",
    "private video",
    "video unavailable",
    "drm protected",
    "this video is drm",
    "not found",
    "401",
    "403",
)


def is_fatal_proxy_error(error: Exception | str) -> bool:
    msg = str(error).lower()
    return any(m in msg for m in FATAL_PROXY_MARKERS)


async def run_with_proxies(
    proxies: list[str | None],
    work: Callable[[str | None], Awaitable[object]],
    *,
    timeout: float = 20,
    log_prefix: str = "proxy",
) -> tuple[object | None, Exception | None]:
    last_error: Exception | None = None
    for proxy in proxies:
        t0 = time.time()
        label = "direct" if proxy is None else mask_proxy(proxy)
        try:
            result = await asyncio.wait_for(work(proxy), timeout=timeout)
            if proxy is not None:
                await record_proxy_result(proxy, success=True, latency_ms=(time.time() - t0) * 1000)
            return result, None
        except Exception as e:
            last_error = e
            log.warning("%s: %s не сработал: %s", log_prefix, label, e)
            if proxy is not None:
                await record_proxy_result(proxy, success=False, error=str(e))
            if is_fatal_proxy_error(e):
                break
    return None, last_error
