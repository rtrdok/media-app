"""Локальные настройки UI."""

from __future__ import annotations

import json
from pathlib import Path

from media_core.config import BASE_DIR, DOWNLOAD_DIR

_PATH = BASE_DIR / "config" / "app_settings.json"

_DEFAULTS = {
    "download_dir": DOWNLOAD_DIR,
    "theme": "dark",
    "accent": "blue",
    "rate_limit": "",
    "subtitles": "off",
    "minimize_to_tray": True,
    "notify_on_done": True,
    "desktop_shortcut": False,
    "autostart": False,
    "update_check_url": "",
    "cache_max_days": 7,
    "use_cookies": False,
    "extension_token": "",
    "ui_lang": "ru",
    "last_update_check": 0,
    "check_disk_space": True,
    "max_concurrent_downloads": 3,
    "use_proxy": False,
    "proxy_list": "",
    "onboarding_done": False,
    "folders_by_service": True,
}


def _load() -> dict:
    data = dict(_DEFAULTS)
    if _PATH.is_file():
        try:
            raw = json.loads(_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
        except (OSError, json.JSONDecodeError):
            pass
    return data


def _save(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_all() -> dict:
    return _load()


def update_settings(**kwargs) -> dict:
    data = _load()
    for k, v in kwargs.items():
        if v is None:
            continue
        if k in _DEFAULTS or k == "download_dir":
            data[k] = v
    if data.get("download_dir"):
        Path(str(data["download_dir"])).mkdir(parents=True, exist_ok=True)
    _save(data)
    return data


def get_download_dir() -> str:
    return str(_load().get("download_dir") or DOWNLOAD_DIR)


def set_download_dir(path: str) -> None:
    update_settings(download_dir=path)


_SERVICE_FOLDERS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "vk": "VK",
    "rutube": "RuTube",
    "soundcloud": "SoundCloud",
    "yandex_music": "Yandex Music",
    "coub": "Coub",
    "x": "X",
    "twitch": "Twitch",
    "venbox": "VenBox",
    "direct": "Direct",
    "generic": "Other",
}


def service_folder_name(platform: str | None) -> str:
    key = (platform or "").strip().lower()
    return _SERVICE_FOLDERS.get(key) or "Other"


def get_download_dir_for_url(url: str = "", platform: str | None = None) -> str:
    """Корневая папка загрузок или подпапка сервиса (YouTube, VK, …)."""
    root = Path(get_download_dir())
    if not get_bool("folders_by_service", True):
        root.mkdir(parents=True, exist_ok=True)
        return str(root)
    if not platform:
        from media_core.utils import detect_platform

        platform = detect_platform(url or "") if url else None
    folder = service_folder_name(platform)
    dest = root / folder
    dest.mkdir(parents=True, exist_ok=True)
    return str(dest)


def get_theme() -> str:
    return str(_load().get("theme") or "dark")


def get_rate_limit() -> str:
    return str(_load().get("rate_limit") or "").strip()


def get_subtitles_mode() -> str:
    mode = str(_load().get("subtitles") or "off").strip().lower()
    return mode if mode in ("off", "srt", "embed") else "off"


def get_bool(key: str, default: bool = False) -> bool:
    v = _load().get(key, default)
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def get_cache_max_days() -> int:
    try:
        n = int(_load().get("cache_max_days") or 7)
    except (TypeError, ValueError):
        n = 7
    return max(1, min(365, n))


def get_update_check_url() -> str:
    return str(_load().get("update_check_url") or "").strip()


def use_cookies_enabled() -> bool:
    return get_bool("use_cookies", False)


def get_extension_token() -> str:
    return str(_load().get("extension_token") or "").strip()


def get_ui_lang() -> str:
    lang = str(_load().get("ui_lang") or "ru").strip().lower()
    return lang if lang in ("ru", "en") else "ru"


def get_last_update_check() -> float:
    try:
        return float(_load().get("last_update_check") or 0)
    except (TypeError, ValueError):
        return 0.0


def set_last_update_check(ts: float | None = None) -> None:
    import time

    update_settings(last_update_check=float(ts if ts is not None else time.time()))


def parse_proxy_lines(text: str) -> list[str]:
    """Нормализует строки прокси для yt-dlp.

    Поддерживается:
    - http://host:port
    - http://user:pass@host:port
    - socks5://host:port
    - socks5://user:pass@host:port
    - socks5h://… (DNS через прокси)
    - host:port:user:pass  → http://…
    - socks5:host:port:user:pass / socks5h:host:port:user:pass
    """
    out: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if low.startswith(("http://", "https://", "socks4://", "socks5://", "socks5h://")):
            out.append(line)
            continue
        scheme = "http"
        rest = line
        for prefix in ("socks5h:", "socks5:", "socks4:", "http:", "https:"):
            if low.startswith(prefix) and "://" not in line[:12]:
                scheme = prefix.rstrip(":")
                rest = line[len(prefix) :].lstrip()
                break
        parts = rest.split(":")
        if len(parts) == 4 and "@" not in rest:
            host, port, user, password = parts
            out.append(f"{scheme}://{user}:{password}@{host}:{port}")
        elif len(parts) == 2 and parts[1].isdigit():
            out.append(f"{scheme}://{rest}")
        else:
            out.append(line)
    return out


def get_configured_proxies() -> list[str]:
    if not get_bool("use_proxy", False):
        return []
    from_settings = parse_proxy_lines(str(_load().get("proxy_list") or ""))
    if from_settings:
        return from_settings
    from media_core.config import PROXY_LIST

    return list(PROXY_LIST)
