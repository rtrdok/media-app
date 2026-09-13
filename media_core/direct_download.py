"""Прямые ссылки на файлы (Telegram/Discord CDN и т.п.)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from media_core.logging_setup import log

_DIRECT_HOSTS = (
    "cdn.discordapp.com",
    "media.discordapp.net",
    "discord.com",
    "telegram.org",
    "telesco.pe",
    "cdn-telegram.org",
    "googleusercontent.com",
)

_EXT_RE = re.compile(r"\.(mp4|webm|mkv|mov|avi|mp3|m4a|wav|flac|ogg|opus|jpg|jpeg|png|gif|webp)(?:\?|$)", re.I)


def is_direct_file_url(url: str) -> bool:
    u = (url or "").lower()
    if not u.startswith("http"):
        return False
    host = urlparse(url).netloc.lower()
    if any(h in host for h in _DIRECT_HOSTS):
        return True
    if _EXT_RE.search(u):
        return True
    return False


def download_direct(url: str, dest_dir: str, progress_state: dict | None = None) -> str | None:
    import requests

    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    name = unquote(Path(urlparse(url).path).name) or "download.bin"
    name = re.sub(r"[^\w.\- ()\[\]]+", "_", name)[:180]
    dest = str(Path(dest_dir) / name)
    if progress_state is not None:
        progress_state["stage"] = "Скачиваю прямой файл…"
        progress_state["indeterminate"] = True
    try:
        from media_core.net_proxy import requests_proxies

        with requests.get(url, stream=True, timeout=60, proxies=requests_proxies()) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress_state is not None and total:
                        pct = 100.0 * done / total
                        progress_state["percent"] = f"{pct:.1f}%"
                        progress_state["indeterminate"] = False
                        progress_state["stage"] = "Скачиваю файл"
        return dest if os.path.isfile(dest) else None
    except Exception as e:
        log.warning("direct download failed: %s", e)
        return None
