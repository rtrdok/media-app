"""Единый доступ к прокси для всех загрузчиков (не только yt-dlp).

Важно: системный VPN/прокси Windows НЕ меняем.
Если в настройках приложения прокси выключен — ходим напрямую и явно
игнорируем WinINET/HTTP_PROXY (иначе «VPN для Cursor» тормозит всё приложение).
"""

from __future__ import annotations


# VK / Яндекс в РФ обычно без блокировок — прокси приложения к ним не гоняем
# (cookies при этом всё равно нужны).
_DIRECT_HOST_MARKERS = (
    "vk.com",
    "vk.ru",
    "vk.me",
    "userapi.com",
    "vkuseraudio",
    "yandex.",
    "yandex.ru",
    "yandex.com",
    "yandex.net",
    "music.yandex",
)


def configured_proxy_urls() -> list[str]:
    from media_core.settings_store import get_configured_proxies

    return get_configured_proxies()


def primary_proxy() -> str | None:
    """Первый настроенный прокси приложения или None (прямое соединение)."""
    urls = configured_proxy_urls()
    return urls[0] if urls else None


def is_direct_only_host(url_or_host: str | None) -> bool:
    """True = ходить только напрямую (VK / Яндекс и родственные CDN)."""
    s = (url_or_host or "").strip().lower()
    if not s:
        return False
    return any(m in s for m in _DIRECT_HOST_MARKERS)


def requests_proxies(proxy: str | None = None, *, force_direct: bool = False) -> dict[str, str | None]:
    """Словарь proxies= для requests.

    Всегда явный словарь: если прокси приложения нет — None (не брать системный).
    """
    if force_direct:
        return {"http": None, "https": None}
    p = primary_proxy() if proxy is None else proxy
    if not p:
        return {"http": None, "https": None}
    return {"http": p, "https": p}


def httpx_proxy(proxy: str | None = None, *, force_direct: bool = False) -> str | None:
    """Аргумент proxy= для httpx.Client / AsyncClient."""
    if force_direct:
        return None
    return primary_proxy() if proxy is None else proxy


def httpx_client_kwargs(proxy: str | None = None, *, force_direct: bool = False, **extra) -> dict:
    """kwargs для httpx: trust_env=False, чтобы не подхватывать системный VPN."""
    kw = {"trust_env": False, "proxy": httpx_proxy(proxy, force_direct=force_direct), **extra}
    return kw


def apply_requests_kwargs(kwargs: dict, *, force_direct: bool = False) -> dict:
    """Добавить proxies + trust_env=False, если ещё нет."""
    out = dict(kwargs)
    if "proxies" not in out:
        out["proxies"] = requests_proxies(force_direct=force_direct)
    # не читать HTTP_PROXY / WinINET — VPN системы остаётся для других программ
    out.setdefault("trust_env", False)
    return out


def ytdlp_proxy_opt(proxy: str | None) -> str:
    """Значение proxy для yt-dlp: пустая строка = только напрямую (без системного)."""
    return proxy or ""
